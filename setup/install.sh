#!/bin/bash
# Mochi first-boot installer. Run by pet-install.service (as root) until it succeeds once.
# Safe to run again: every step checks or overwrites. Log: /var/log/pet-install.log
set -u
exec >>/var/log/pet-install.log 2>&1
echo "=== $(date '+%F %T') pet install start"

BOOT=/boot/firmware
SRC=$BOOT/pet
LED=$(ls -d /sys/class/leds/ACT /sys/class/leds/led0 2>/dev/null | head -1)
led() { [ -n "$LED" ] && echo "$1" > "$LED/trigger" 2>/dev/null; true; }
led timer   # fast blink = installing

# 1. internet (Wi-Fi may still be joining)
for i in $(seq 1 60); do
    getent hosts deb.debian.org >/dev/null && break
    echo "waiting for internet ($i)"; sleep 5
done
getent hosts deb.debian.org >/dev/null || { echo "no internet, systemd retries in 60 s"; exit 1; }

# 2. packages: core list must succeed, extras are best effort
export DEBIAN_FRONTEND=noninteractive
apt-get update || exit 1
apt-get install -y --no-install-recommends \
    python3-numpy python3-yaml python3-gpiozero python3-lgpio python3-venv \
    mosquitto alsa-utils i2c-tools || exit 1
for p in python3-paho-mqtt python3-opencv python3-smbus mosquitto-clients; do
    apt-get install -y --no-install-recommends "$p" || echo "optional package $p failed"
done

# 3. hardware interfaces and Wi-Fi power saving (it drops SSH on the Pi 3)
raspi-config nonint do_i2c 0 || true
raspi-config nonint do_spi 0 || true
mkdir -p /etc/NetworkManager/conf.d
printf '[connection]\nwifi.powersave = 2\n' > /etc/NetworkManager/conf.d/pet-wifi-powersave.conf
grep -q 'act_led_trigger' $BOOT/config.txt || printf 'dtparam=act_led_trigger=heartbeat\n' >> $BOOT/config.txt

# 4. the pet user: no sudo, no login shell; code read-only to it, data in /var/lib/pet
id pet >/dev/null 2>&1 || useradd --system --home-dir /var/lib/pet --shell /usr/sbin/nologin pet
for g in gpio i2c spi audio video; do getent group $g >/dev/null && usermod -aG $g pet; done
mkdir -p /var/lib/pet && chown pet:pet /var/lib/pet && chmod 750 /var/lib/pet

rm -rf /opt/pet.new && cp -r "$SRC" /opt/pet.new
rm -rf /opt/pet && mv /opt/pet.new /opt/pet
rm -rf /opt/pet/android            # the phone app's source isn't needed on the Pi
chown -R root:root /opt/pet && chmod -R go-w /opt/pet

# 5. the girl's voice: Piper in its own venv (sees apt's numpy), and the default voice model
if [ ! -x /opt/pet-env/bin/python ]; then python3 -m venv --system-site-packages /opt/pet-env || exit 1; fi
/opt/pet-env/bin/pip install --no-cache-dir "piper-tts==1.8.0" || echo "piper install failed: the pet runs with chirps only"
VOICE=en_US-amy-medium; VDIR=/var/lib/pet/voices; mkdir -p $VDIR
for ext in onnx.json onnx; do
    [ -s "$VDIR/$VOICE.$ext" ] || curl -fsSL -o "$VDIR/$VOICE.$ext.part" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/$VOICE.$ext" \
        && mv "$VDIR/$VOICE.$ext.part" "$VDIR/$VOICE.$ext"
done
chown -R pet:pet /var/lib/pet

# 6. the pet may manage Wi-Fi (saved networks, her hotspot) and nothing else
mkdir -p /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/50-pet-network.rules <<'EOF'
// Mochi (user "pet") may manage Wi-Fi connections and her own hotspot. Nothing else.
polkit.addRule(function (action, subject) {
    var ok = ["org.freedesktop.NetworkManager.settings.modify.system",
              "org.freedesktop.NetworkManager.network-control",
              "org.freedesktop.NetworkManager.wifi.share.protected",
              "org.freedesktop.NetworkManager.wifi.share.open",
              "org.freedesktop.NetworkManager.enable-disable-wifi",
              "org.freedesktop.NetworkManager.wifi.scan"];
    if (subject.user == "pet" && ok.indexOf(action.id) >= 0) return polkit.Result.YES;
});
EOF

# 7. tell phones on the network where she is (the Android app looks for _mochi._tcp)
mkdir -p /etc/avahi/services
cat > /etc/avahi/services/mochi.service <<'EOF'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">Mochi on %h</name>
  <service><type>_mochi._tcp</type><port>8080</port></service>
</service-group>
EOF
systemctl reload avahi-daemon 2>/dev/null || systemctl restart avahi-daemon 2>/dev/null || true

# 8. services
cp /opt/pet/setup/pet.service /etc/systemd/system/pet.service
systemctl daemon-reload
systemctl enable mosquitto pet
systemctl restart mosquitto
systemctl restart pet

# 9. wipe the Wi-Fi password from the readable boot partition and the cloud-init logs
#    (NetworkManager keeps its own root-only copy in /etc/NetworkManager/system-connections)
if nmcli -t -f DEVICE,STATE device | grep -q '^wlan0:connected'; then
    printf '# Wi-Fi was set up on first boot; the password was removed from this file.\n' > $BOOT/network-config
    rm -f /var/log/cloud-init.log /var/log/cloud-init-output.log
fi

touch /var/lib/pet-installed
led heartbeat   # double blink = ready
echo "=== $(date '+%F %T') pet install done"
