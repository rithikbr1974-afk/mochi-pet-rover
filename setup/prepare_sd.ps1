<#
Prepares a freshly flashed Raspberry Pi OS Lite (64-bit, Trixie) SD card so Mochi boots headless:
Wi-Fi, SSH with your key, hostname, country, and the pet code with its first-boot installer.

1. Flash "Raspberry Pi OS Lite (64-bit)" for Raspberry Pi 3 with Raspberry Pi Imager (no customisation needed).
2. Leave the card in the PC and run:   powershell -ExecutionPolicy Bypass -File pet\setup\prepare_sd.ps1
   It asks for the Wi-Fi password here, in your own terminal. Nothing is sent anywhere.
#>
param(
    [string]$Drive = "",                 # boot partition, e.g. "F:". Found automatically if empty.
    [string]$Hostname = "mochi",
    [string]$User = "pet-admin",
    [string]$Country = "IN",
    [string]$Timezone = "Asia/Kolkata"
)
$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)   # no BOM: cloud-init and the bootloader want plain UTF-8

function Write-Unix([string]$path, [string]$text) {
    [IO.File]::WriteAllText($path, ($text -replace "`r`n", "`n"), $utf8)
}
function Quote-Yaml([string]$s) { "'" + ($s -replace "'", "''") + "'" }
function Read-Plain([string]$prompt) {
    $sec = Read-Host $prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

# --- 1. find the boot partition -------------------------------------------------------------
if (-not $Drive) {
    $cands = Get-PSDrive -PSProvider FileSystem | Where-Object {
        (Test-Path "$($_.Root)cmdline.txt") -and (Test-Path "$($_.Root)config.txt") -and (Test-Path "$($_.Root)bootcode.bin")
    }
    if (@($cands).Count -ne 1) {
        Write-Host "Found $(@($cands).Count) Raspberry Pi boot partitions. Run again with -Drive X:" -ForegroundColor Red
        exit 1
    }
    $Drive = @($cands)[0].Root.TrimEnd('\')
}
$Boot = $Drive.TrimEnd('\') + '\'
if (-not (Test-Path "$Boot\cmdline.txt")) { throw "$Boot has no cmdline.txt; is this the Pi's boot partition?" }
$cmdline = ([IO.File]::ReadAllText("$Boot\cmdline.txt")).Trim()
if ($cmdline -match 'raspberrypi-sys-mods/firstboot' -or -not (Test-Path "$Boot\user-data")) {
    Write-Host "This card has an older image (Bookworm) without cloud-init. Flash the current Raspberry Pi OS Lite (64-bit) and run again." -ForegroundColor Red
    exit 1
}
Write-Host "Raspberry Pi boot partition: $Boot" -ForegroundColor Cyan

# --- 2. SSH key (your PC logs in with it; the Pi has no password login) -----------------------
$keyPath = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
if (-not (Test-Path "$keyPath.pub")) {
    $ans = Read-Host "No SSH key on this PC yet. Create one now (needed to log in to the Pi)? [y/n]"
    if ($ans -ne 'y') { Write-Host "Stopped: an SSH key is needed."; exit 1 }
    New-Item -ItemType Directory -Force (Split-Path $keyPath) | Out-Null
    ssh-keygen -t ed25519 -f $keyPath -C "pc-to-$Hostname"
    if (-not (Test-Path "$keyPath.pub")) { throw "ssh-keygen did not create a key" }
}
$pubkey = ([IO.File]::ReadAllText("$keyPath.pub")).Trim()

# --- 3. Wi-Fi (asked here; written only to the card) ------------------------------------------
Write-Host "`nThe Pi 3 only sees 2.4 GHz Wi-Fi, and WPA3-only networks don't work (WPA2 or mixed is fine)." -ForegroundColor Yellow
$nets = @()
$ssid = Read-Host "Home Wi-Fi name (SSID)"
$pw = Read-Plain "Password for '$ssid'"
$nets += ,@($ssid, $pw)
$ssid2 = Read-Host "Backup network, e.g. your phone hotspot (Enter to skip)"
if ($ssid2) { $nets += ,@($ssid2, (Read-Plain "Password for '$ssid2'")) }

$aps = ($nets | ForEach-Object { "        $(Quote-Yaml $_[0]):`n          password: $(Quote-Yaml $_[1])" }) -join "`n"
Write-Unix "$Boot\network-config" @"
network:
  version: 2
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: "$Country"
      access-points:
$aps
"@
$pw = $null; $nets = $null

# --- 4. user-data: hostname, login, timezone, first-boot installer --------------------------
$Hostname = ($Hostname.ToLower() -replace '[^a-z0-9-]', '')
Write-Unix "$Boot\user-data" @"
#cloud-config
manage_resolv_conf: false
hostname: $Hostname
manage_etc_hosts: true
timezone: $Timezone
user:
  name: $User
  shell: /bin/bash
  lock_passwd: true
  ssh_authorized_keys:
    - $(Quote-Yaml $pubkey)
  sudo: ALL=(ALL) NOPASSWD:ALL
ssh_pwauth: false
runcmd:
  - [ systemctl, enable, --now, ssh ]
  - [ cp, /boot/firmware/pet/setup/pet-install.service, /etc/systemd/system/pet-install.service ]
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, pet-install.service ]
  - [ systemctl, start, --no-block, pet-install.service ]
"@
if (-not (Test-Path "$Boot\meta-data")) {
    Write-Unix "$Boot\meta-data" "instance-id: $Hostname-$(Get-Date -Format yyyyMMddHHmmss)`n"
}

# --- 5. country in cmdline.txt (one line), I2C/SPI/audio in config.txt -------------------------
$cmdline = ($cmdline -replace '\s*cfg80211\.ieee80211_regdom=\S+', '') + " cfg80211.ieee80211_regdom=$Country"
Write-Unix "$Boot\cmdline.txt" ($cmdline + "`n")

$cfg = [IO.File]::ReadAllText("$Boot\config.txt")
if ($cfg -notmatch '# --- mochi ---') {
    $cfg = $cfg.TrimEnd() + "`n`n[all]`n# --- mochi ---`ndtparam=i2c_arm=on`ndtparam=spi=on`ndtparam=audio=on`n"
    Write-Unix "$Boot\config.txt" $cfg
}

# --- 6. copy the pet code (text files converted to LF) ---------------------------------------
$src = Split-Path $PSScriptRoot -Parent          # ...\pet
$dst = "$Boot\pet"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
$textExt = '.py', '.sh', '.service', '.yaml', '.yml', '.html', '.js', '.css', '.txt', '.md', '.json'
Get-ChildItem -Recurse -File $src | Where-Object { $_.FullName -notmatch '\\__pycache__\\|\\data\\|\\android\\' } | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    $out = Join-Path $dst $rel
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    if ($textExt -contains $_.Extension.ToLower()) { Write-Unix $out ([IO.File]::ReadAllText($_.FullName)) }
    else { Copy-Item $_.FullName $out }
}

Write-Host "`nDone. The card is ready." -ForegroundColor Green
Write-Host @"
Next:
  1. Eject the card safely, put it in the Pi, power the Pi on.
  2. First boot installs everything (about 15-30 min). The green LED blinks fast while it works and
     changes to a heartbeat (double blink) when Mochi is ready; a chirp plays if the speaker is wired.
  3. On this PC:  powershell -ExecutionPolicy Bypass -File pet\setup\find_pet.ps1
  4. On your phone: http://$Hostname.local:8080
The Wi-Fi password is wiped from the card by the Pi once it is online.
"@
