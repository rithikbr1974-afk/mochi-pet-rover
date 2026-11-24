# Pet rover: design

Step-by-step build: [HARDWARE.md](HARDWARE.md). Project overview: [../README.md](../README.md).

A small rover pet built on a Raspberry Pi 3. It lives on the Pi, learns, makes its own choices, and uses one old
phone as its eyes and ears. The working name is **Mochi**; set the name in `pet/config.yaml`.

Status (2026-11-24): design agreed with the owner's changes. The headless SD card setup and the phase 0 software are
written (`pet/`), and are waiting for the SD card. Items marked *(verify)* are checked or measured on the real
hardware before building on them.

Changes after his review:
- One phone only, no face or eyes on a screen. Emotions show in **how the car moves**, plus sounds.
- Two voices: a **girl's voice** and the **Pochi voice** (a creature voice made of chirps and babble).
- A cheap toy-motor chassis.
- Distance from vision for now; LiDAR comes later as an add-on.
- The Pi's display output is broken, so the setup is fully **headless**: flash the card, power on, done.

---

## 1. What the hardware can really do

The Pi 3 has 1 GB RAM and a 1.2 GHz quad-core Cortex-A53, with no usable GPU and no AI chip. That shapes everything:

| Job | Where it runs | Notes |
|---|---|---|
| Reflexes: motors, obstacle/cliff stop, watchdog | Pi, 50 Hz | Must work even if everything else crashes |
| Drives, emotions, behaviour choice (the RL "mind") | Pi, small numpy network | ~1 ms per decision |
| Memory (events, people, places, routines, skills) | Pi, SQLite | Light, survives power cuts |
| Camera vision | Phone streams video → Pi at 320×240 | Pi 3 does detection at ~2-5 fps *(measure)*; a fast tracker fills the frames between |
| Wake word | Pi, openWakeWord + a personal model | Its README says a Pi 3 core runs 15-20 models live *(verify)* |
| Speech to text | Pi, Vosk `small-en-in` (Indian English, ~36 MB) | Command grammars make it accurate |
| Girl's voice | Pi, Piper (pitched up) + lines Kokoro made on the PC | Kokoro itself is too heavy for a Pi 3 |
| Pochi voice and sounds | Pi, generated in code | Already written (`pet/pet/chirps.py`) |
| Real questions | a home assistant on the PC when online; a tiny LLM offline | See below |

**The LLM, honestly:** a ~0.5B model (for example Qwen2.5-0.5B-Instruct, GGUF Q4, ~400 MB) through llama.cpp should
give a few words a second on a Pi 3 *(measure first)*. That's enough for short pet sentences, but not for real Q&A.

- **Offline:** the tiny LLM, plus sentence templates for common moments.
- **Online:** real questions go to a home assistant on the PC over Wi-Fi.

Its mind, memory and choices always stay on the Pi. One huge network that learns everything won't fit on a Pi 3, so
the pet uses many small learners instead (section 5).

---

## 2. Which phone: Lenovo K3 Note

| | **Lenovo K3 Note** | Panasonic P101 |
|---|---|---|
| Chip | MediaTek MT6752: **8 × A53 @ 1.7 GHz** | MediaTek MT6739: 4 × A53 @ 1.3 GHz |
| GPU | Mali-T760 MP2 | PowerVR GE8100 (entry level) |
| RAM | 2 GB | 2 GB |
| Main / front camera | **13 MP** f/2.0 / 5 MP | 8 MP f/2.2 / 5 MP |
| Gyroscope | **yes** | no |
| Wi-Fi | **2.4 + 5 GHz** | 2.4 GHz |
| Battery | 3000 mAh (from 2015, check it isn't swollen) | 2500 mAh |
| Android | 5.0 (official 6.0 update) | **7.1** |

Sources: mobosdata.com spec pages for both phones (GSMArena blocks automated readers).

**Pick: K3 Note.** It has about 2.5× the CPU power, a better camera, and a gyroscope, which helps judge turns and
bumps. The P101's only advantage is a newer Android, which matters only if a needed app won't install on Android
5/6. The video is streamed to the Pi either way, so old Android is fine.

- **Mount:** OpenBot style, at the front, **rear camera facing forward** (the better camera), tilted about 10° down
  so the floor in front is in view. The camera's height and tilt are measured once; distance by vision depends on
  them.
- **Streaming app (phase 2):** a free IP-camera app gives the Pi video and the phone's mic *(verify which app still
  installs on Android 5/6)*. If the Pi turns out too slow, phase 2b is a small app of Mochi's own that runs detection
  on the phone and sends only results.
- **Power:** the phone charges from the power bank's second port.

---

## 3. Body (low budget)

### Chassis: two cheap options

**A. 2WD "smart car" acrylic kit (recommended).** About ₹300-450 online: acrylic plate, 2 yellow TT gear motors,
2 wheels, a caster wheel, a 4×AA holder, often with slotted encoder discs. Two driven wheels can spin in place, which
the emotion moves need.

**B. An old toy car.** Free, but most toy cars steer with the front wheels, so they can't spin on the spot. Use only
its rear motor and gearbox, plus a caster, or fit two motors.

*Not 4WD:* it needs more power, and skid steering on four wheels drains the batteries and wiggles badly.

### Parts and rough prices (India, online)

| Part | ≈ ₹ | Use |
|---|---|---|
| 2WD acrylic car kit (2 TT motors, wheels, caster) | 300-450 | body |
| TB6612FNG motor driver (or L298N ≈ ₹120, same wiring) | 150-200 | TB6612 wastes less battery |
| 2× 18650 cells + 2S holder/BMS + switch, **or** the kit's 4×AA | 0-350 | **motors' own battery**; the switch is the kill switch |
| HC-SR04 ultrasonic + 2 resistors (1k + 2k) | 60 | front distance, and the "ruler" vision learns from |
| 2× TCRT5000 IR modules, pointing down | 80 | **cliff/stairs stop** |
| 2× LM393 speed sensor modules (slotted) | 80 | wheel encoders |
| MPU6050 | 130 | accurate turns, knows when it's lifted or tipped |
| TTP223 touch pad | 20 | head pats (reward) |
| PAM8403 amp + small 3 W speaker | 90 | voice and sounds, from the **Pi's 3.5 mm jack** |
| Jumper wires, small breadboard, phone clip | 150 | |
| **Total** | **≈ ₹1,100-1,700** | plus a 2-port power bank if you don't have one |

The mic is the phone's at first (streamed with the video), so no USB mic is needed. A USB mic (≈₹150) can be added
later if the phone's mic is poor.

**Power rule:** the motors never run from the Pi's power bank. Motor surges brown out the Pi and can corrupt its SD
card. Use separate packs with a shared ground (GND to GND).

```
                 [ K3 Note ]  rear camera forward, tilted down
       ______________|______________
      | speaker  Pi 3   power bank  |   touch pad on top = head pat
      | TB6612   motor pack + switch|   RESERVED expansion header (section 7)
      |_____________________________|   later: LiDAR, robot arm on top
   (o) ultrasonic front, 2 cliff IR   (o)
   wheel + encoder         caster     wheel + encoder
```

---

## 4. Software on the Pi

The OS is Raspberry Pi OS Lite 64-bit (Debian 13 Trixie), headless. The code is Python with no frameworks (small, swappable
modules). Parts talk through **MQTT** (mosquitto), which is also how the phone, a home assistant and add-ons connect.

```
 body.py ─ reflexes ─ moves.py ─ mind.py ─ vision.py ─ voice.py ─ memory.py ─ plugins.py ─ web.py
 motors   watchdog   emotion    drives,   detect,     wake, STT, SQLite      finds GPIO    phone page:
 sensors  cliff/obst movements  RL policy track,depth girl/Pochi             add-ons       drive, teach
```

- Code lives in `/opt/pet`, owned by root, so the pet can't rewrite itself. Its data is in `/var/lib/pet`.
- The pet runs as its own `pet` user with no sudo.

### Headless setup (works with no display)

1. Flash **Raspberry Pi OS Lite (64-bit)** for Raspberry Pi 3 with Raspberry Pi Imager. Customisation isn't needed.
2. With the card still in the PC, run `pet\setup\prepare_sd.ps1`. It asks for the Wi-Fi name and password **in your
   own terminal**, plus an optional phone hotspot as a backup network. It then writes, on the card's boot partition:
   - cloud-init `user-data`: hostname, timezone, your login with your PC's SSH key (no password login);
   - `network-config`: Wi-Fi, which also unblocks the radio. Trixie ignores the old `wpa_supplicant.conf`, and the
     radio starts blocked;
   - the country (`IN`) in `cmdline.txt`;
   - the pet code.
3. Put the card in the Pi and power it on. First boot:
   - joins Wi-Fi and turns on SSH;
   - installs the packages: mosquitto, numpy, OpenCV, gpiozero, I2C tools and audio;
   - turns on I2C and SPI, and creates the `pet` user;
   - starts `pet.service` and plays a hello chirp from the speaker.
   This takes about 15-30 min on a Pi 3. It retries if the internet isn't up yet.
4. **How you know it's ready, with no screen:**
   - the green ACT LED blinks fast while installing and changes to a **heartbeat** (double blink) when done;
   - you hear the chirp if the speaker is wired;
   - `pet\setup\find_pet.ps1` on the PC finds it (mochi.local, or by its Raspberry Pi MAC) and shows the install
     log;
   - then open `http://mochi.local:8080` on your phone.
5. Later code updates go over SSH with `pet\setup\deploy.ps1`.

The Wi-Fi password is removed from the boot partition and the cloud-init log once the Pi is online.
NetworkManager keeps it in a root-only file. The Pi 3 has **2.4 GHz Wi-Fi only**, and a WPA3-only network won't
work; use WPA2 or a mixed WPA2/WPA3 network.

---

## 5. The mind: machine learning, all of it

| Learner | Method | Learns from | Runs |
|---|---|---|---|
| Behaviour choice | Actor-critic network (2 layers, ~5k weights, numpy) | rewards below | Pi, online + nightly replay |
| Curiosity | Forward model: predicts the next state; the error is the reward | its own experience | Pi |
| Wake word "Mochi" | openWakeWord embeddings + personal classifier (trained from your clips) | your recordings | trained on the PC |
| Commands | Vosk grammar + a small intent classifier (embeddings, nearest neighbour) | your phrasings, corrected when wrong | Pi |
| Praise or scold tone | small classifier on voice pitch and energy | your "good girl" vs "no!" | Pi, later |
| People | person detector (MobileNet-SSD class, int8) | pretrained | Pi |
| Who is the owner | face embedding (when the face is visible) + clothing colour of the day | your face, re-learned each day | Pi |
| Objects | detector + image embeddings, k-nearest neighbour | "this is my cup" | Pi |
| Distance by vision | self-supervised regressor (section 6) | ultrasonic readings as labels | Pi |
| Free floor | online floor colour/texture model | the floor it just drove over safely | Pi |
| Places | image embedding per spot, topological graph | where it drives | Pi |
| Your routines | counts per hour of the week | when you wake, leave, come home | Pi |
| Movement skills | cross-entropy method on move parameters | IMU/encoder results ("turn exactly 90°") | Pi |
| Teach mode | records your driving as a named move | you, through the phone page | Pi |

### Drives, emotions, rewards

- **Drives** rise over time: energy (real battery), social (time since it saw you), curiosity, boredom, sleepiness
  (time of day and your routine).
- **Emotion** is two numbers, valence (happy↔upset) and arousal (calm↔excited). Events push them.
- **Actions are behaviours**, not raw motor commands:
  - explore, follow you, greet, come here, nap;
  - play, dance, ask for attention, patrol, go and charge;
  - practise a skill, stay quiet, follow a line.
- **Reward** =
  - plus: praise or a pat, and needs going down;
  - plus: curiosity (something it didn't predict);
  - minus: "no", "bad", "stop";
  - minus: bumps, getting stuck, a low battery.
- **Sleep = learning:** while charging at night it replays the day's events (stored in SQLite) and trains on them, so
  it gets better overnight.
- **Its own initiative:** it doesn't wait for commands. Your commands come first, but its mood still shows: a
  sleepy grumble shake before it obeys.
- **Habits:** it learns your times and acts ahead of them. It waits near the door around when you usually get home,
  and stays quiet after you usually sleep.

### Memory (SQLite)

- **Tables:** `events`, `people`, `things`, `places`, `skills`, `routines`, `facts`.
- **Thinning:** old events are summarised and thinned out, so the card never fills.
- **Overheard speech:** anything it hears that isn't meant for it is forgotten after 24 h.

---

## 6. Vision: obstacles, distance, human tracking

### Distance without LiDAR (cheap methods, combined)

1. **Ground-plane geometry (main method, nearly free):** the camera's height and tilt are known, so the image row
   where an object touches the floor gives its distance in cm (one formula, calibrated once).
2. **Free floor:** it learns what the floor looks like (colour and texture) from the strip it just drove over
   safely. Image columns where the floor stops early are blocked, and it steers to the widest free gap.
3. **Looming:** optical flow (OpenCV Farnebäck at 160×120) shows things growing fast in front, giving
   time-to-contact even for objects with no visible bottom, like a chair seat.
4. **Learning to judge distance:** every ultrasonic reading is a free, correct label for the middle of the image. A
   small regressor learns image → distance from those labels and keeps improving: natural learning.
5. **A depth network** (a MiDaS-small-class model) is optional. On a Pi 3 it is likely under 1 frame a second
   *(measure)*, so it's only for slow "look around" moments, not driving.

The ultrasonic sensor and the cliff sensors stay as the last line of defence. **LiDAR later** (for example a TF-Luna
on I2C or UART, or an RPLIDAR on USB) plugs into the add-on system (section 7). Its distances feed the same obstacle
map and become the new labels for method 4.

### Human tracking

1. **Detect** people every ~0.3-0.5 s (MobileNet-SSD-class int8, 300×300 or smaller).
2. **Track** between detections with a fast tracker (optical flow on the box corners, or MOSSE), plus a Kalman
   filter, so the box moves smoothly at 15+ fps.
3. **Re-identify:** is this the owner? A face embedding when the face is visible, plus today's clothing colour
   histogram, so it knows you from behind too.
4. **Follow controller:** steering keeps you in the middle of the image (PID on the box centre); speed holds a set
   distance (ground-plane distance of your feet).
5. **Lost you:** it turns toward the side you left from, waits, calls the owner's name in the Pochi voice, then goes to
   where you usually are at that hour (its routine memory).

### Line following and objects

- **Line following:** threshold + centroid on the bottom strip of the image, with PID steering. Classical, fast and
  reliable.
- **Objects:** the COCO detector plus its own learned things. "Find my cup" means: search nearby, check the
  embeddings, then go there.

---

## 7. Expansion: the reserved GPIO block and add-ons

### Pin plan (BCM numbers), as set in `pet/config.yaml`

| Used by the core | Pins |
|---|---|
| Motors (TB6612 or L298N) | PWMA/ENA 12, AIN1/IN1 5, AIN2/IN2 6, PWMB/ENB 13, BIN1/IN3 20, BIN2/IN4 21, STBY 26 (TB6612 only) |
| Wheel encoders | 17, 27 |
| Ultrasonic | TRIG 23, ECHO 24 (through the 1k/2k divider: ECHO is 5 V) |
| Cliff sensors | 16, 25 |
| Touch pad | 22 |
| Tray switch (item on the tray) | 19 |
| Audio | the 3.5 mm jack (no GPIO) |

| **Reserved for add-ons (the core never uses these)** | Pins |
|---|---|
| I2C (most add-ons; MPU6050 lives here too) | 2 (SDA), 3 (SCL) |
| SPI | 7, 8, 9, 10, 11 |
| UART (LiDAR) | 14, 15 |
| 1-Wire | 4 |
| Spare PWM | 18 |
| Add-on ID EEPROM (HAT standard) | 0, 1 |

I2C addresses:
- MPU6050: `0x68`.
- Battery monitor (INA219, later): `0x41`.
- `0x40` is kept free for the robot arm's PCA9685 servo board.

### How it finds out what was plugged in

1. Every 10 s it scans I2C, UART and 1-Wire for new devices.
2. A known-device table matches addresses and probe answers to drivers: PCA9685 servo board `0x40`, VL53L0X `0x29`,
   TF-Luna `0x10`, BME280 `0x76`.
3. **Best way:** the add-on carries a tiny EEPROM (AT24C02) that says what it is.
4. **Unknown device:** it says "Something new is plugged in at 0x5A, what is it?" You (or an AI coding assistant) can write a driver,
   which goes on the pet only after **your OK**.
5. A driver adds new senses and new moves. The policy network grows new inputs and outputs while keeping its old
   weights, so it starts trying the new ability.

### Robot arm, solar (later)

- **Arm:** 4-6 servos on a PCA9685 with its own 5-6 V 3 A supply. Fixed poses first (fold/reach/grab/drop), then
  camera-guided pick-up.
- **Charging:** a charging dock first: two contacts and a printed marker it recognises, so being "hungry" sends it
  home.
- **Solar:** a 10-20 W panel, a charge controller, and a power bank that can charge while in use.

---

## 8. Personality: voices and body language (no screen)

### Two voices

- **Girl's voice:** short, sweet, warm sentences ("You're home~ I missed you!"). Frequent lines are
  pre-made in high quality with Kokoro on the PC and copied to the pet. New sentences are spoken live by Piper,
  pitched up.
- **Pochi voice:** creature babble made of chirps whose melody follows the emotion. Happy is fast rising trills,
  angry a low buzz, sad a falling whine, curious ends going up like a question, sleepy is a yawn, loving is a soft
  warble.
- **Both together:** it reacts in Pochi first, then speaks in the girl's voice when it has something to say. Say
  "only Pochi" or "talk normally" to switch; the mind can also pick Pochi for moods and the girl for information.

### Emotions in the car's movement

Already built in `pet/pet/moves.py`; try them from the phone page.

| Emotion | Movement |
|---|---|
| Happy | fast continuous left-right wiggle (rapid opposite wheel pulses) |
| Excited | wiggle + a full spin + wiggle |
| Angry | sharp short forward/back shakes, then turns away |
| Sad | slow backing off, a small droop turn |
| Curious | creep forward, pause, creep, a little tilt left/right |
| Sleepy | very slow small sways |
| Loving | slow approach, tiny wiggles, a gentle nudge |
| "No" | short left-right head shake in place |
| "Yes" | small forward/back nods |

Quiet hours and gentle speeds apply at night.

---

## 9. Connections

- **Wi-Fi + internet:** weather, news, and the home assistant's brain when online. Every core feature works offline.
- **Smart home:** the pet asks a **home assistant** on the PC, which controls Alexa and asks a spoken yes/no for high-power
  appliances. The pet holds **no** Amazon or Google tokens.
- **Home assistant ↔ pet:** an MCP server `pet` ("where's Mochi?", "tell Mochi to come to my room"). The pet can
  ask the assistant for things too.
- **Your two Android phones:** the phone page at `http://mochi.local:8080` (drive, emotions, status; later teach
  mode and the camera), and Telegram alerts through the home assistant ("Mochi is stuck under the bed").

## 10. Freedom and the safety line

**It is free to:** move wherever is safe, choose its behaviours, speak first, learn moves and habits, explore, and
ask for things.

**It can never** (enforced by the system):

- **Accounts:** it runs as the `pet` user with no sudo, and its code is read-only to it.
- **Secrets:** it holds none. Everything outside goes through the home assistant's tools and their confirms.
- **Network:** a firewall allows only the home LAN and a short list of sites (planned, phase 7). No scanning, no
  logins.
- **Code:** no arbitrary code. Its models only pick from known actions, and new drivers or skills need your OK.
- **Camera and mic:** they stay on the pet. Nothing is uploaded unless you ask, and overheard speech is forgotten
  after 24 h.
- **Physical safety:**
  - a motor watchdog (no command for 0.3 s = stop);
  - cliff and obstacle stops;
  - a speed limit;
  - the hardware kill switch on the motor pack.

---

## 11. The phone app (added 2026-11-24)

**Mochi.apk** for your main phone: `pet\android\build_apk.ps1` builds it on this PC with no Gradle and no download,
using a local JDK + Android SDK folder (`-Tools`). It is a small native shell (21 KB):
1. **Finds her anywhere:**
   - the address used last time;
   - her own hotspot (she is the Wi-Fi gateway, 10.42.0.1);
   - `mochi.local`;
   - the network service `_mochi._tcp` (avahi on the Pi, Android NsdManager);
   - or an address you type.
2. **Opens her app from the Pi itself** (`pet/web/`), so app updates arrive with every pet update; there's no
   reinstall.
3. **Voice input** with Android speech recognition (the mic button), and keeps the screen on while open.

The same app also works in any phone browser at `http://<pet>:8080`, without voice input.

| Tab | What's there |
|---|---|
| Home | **Animated eyes** for her mood, all on a canvas: blink, glance, happy ^^, angry lids, sad tear, hearts, sparkles, sleepy z's, a glow that pulses while she talks. Also what she just said, the current task with "It's on the tray" / Stop, "Ask her" (typed or spoken), feeling buttons, "Make her say", status |
| Drive | joystick + speed, the robot phone's camera, STOP, the "teaching a route" banner |
| Places | where she is, where you are, teach a route, places, routes, recent tasks |
| Wi-Fi | current network, saved networks (connect/forget/priority), scan and add, her own hotspot on/off |
| Settings | everything she lets the app change (about 28 settings, made from the Pi's list): name, voice, cuteness, speeds, trim, sensors, camera address, task timings, hotspot; restart |

### Wi-Fi in new places

- Saved networks connect by themselves when in range, highest priority first. Add home, college and a friend's
  place ahead of time.
- No known Wi-Fi for 90 s means she starts her own hotspot **Mochi-setup** (password `mochipet`; change it in
  Settings) and says so. Join it from the phone, and the app finds her at 10.42.0.1, where you can add the new
  Wi-Fi.
- While nobody is on her hotspot, every 5 min she drops it for 45 s to look for known networks.
- Passwords stay in NetworkManager's root-only files and are never sent back to the app.
- The `pet` user gets **only** the NetworkManager rights for this, through a polkit rule; still no sudo.

### Tasks: "bring my remote from the bedroom"

1. **Teach once.** Set where she is, pick a destination, and drive her there. She saves the wheel steps. Every route
   also works backwards, and routes join up through other places.
2. **Ask:** "bring my remote from the bedroom". She plans the chain of routes and drives it.
   - If the path is blocked, she says "Excuse me, can I get through?" and waits; time spent waiting doesn't count.
   - She asks whoever is there to put the remote on her tray.
   - She waits for the tray sensor, a head pat, or the app button, asking again halfway.
   - She comes back to the room you said you're in and says "Here's your remote!"
3. Also: "go to the kitchen", "come here", "stop".

**Honest limit:** routes are timing-based until the wheel encoders (phase 1) and the camera checks (phase 2)
are added. Short, simple routes repeat well. Long ones drift with battery level and floor type, so re-teach a route
when she misses.

**Tray (₹30-60):** a small box or lid on the back with a microswitch underneath (GPIO 19 to GND). "Pressed"
means something is on it. Without it, a head pat or the app button means "done".

### The girl's voice

Piper on the Pi with **en_US-amy-medium** by default. Six other female English voices can be chosen in Settings and
download themselves. "Cuteness" raises the pitch without speeding her up. Every line she says is cached, so
repeats are instant. A new sentence takes about a second or more on a Pi 3 *(measure)*; if it's slow, pick
`en_US-amy-low`. The Pochi chirps still come first for feelings.

### The robot's look

- **Shell:** a white or pastel round plastic food box (≈₹80) upside down over the chassis, with two felt or
  3D-printed cat ears on top. Cut holes for the ultrasonic "eyes" at the front and the cliff sensors underneath.
- **Phone:** in a padded clip at the front like a visor, rear camera forward.
- **Tray:** on the back, in a contrasting colour, so people know where to put things.
- **Colours:** mint and white with sunny-yellow inner ears, to match the app. Stick-on rubber feet on the bumper
  corners so bumps are soft.
- **Later:** a WS2812 LED ring on the reserved SPI pin for a coloured "mood glow" that matches the app's eyes.

---

## 12. Build phases

| Phase | Result | Test |
|---|---|---|
| **0. Headless + bench** (written) | SD prep, first-boot install, motors and emotion moves, Pochi chirps | it drives, stops when the page closes, and wiggles happy |
| **0b. App, Wi-Fi, voice, tasks** (written) | Mochi.apk, eyes, settings, saved Wi-Fi + own hotspot, girl's voice, places/routes, fetch task | add a Wi-Fi from the app; teach living room → bedroom; "bring my remote from the bedroom" |
| 1. Safe body | ultrasonic, cliff sensors, encoders, IMU, reflexes | it stops at a table edge every time |
| 2. Eyes | phone stream, person detection + tracking, line following, ground-plane distance | it follows you around the room |
| 3. Voices + ears | wake word "Mochi", Vosk, girl's voice (Piper + Kokoro lines), Pochi babble | 5 spoken commands |
| 4. Emotions | drives and emotion state driving moves and sounds | praise → happy wiggle, scold → angry shake |
| 5. Mind | RL behaviour policy, memory, nightly learning, routines | greets you at the door after a few days |
| 6. Skills | teach mode, practice, object naming, self-learned distance | "this is my cup" → later "find my cup" |
| 7. Home assistant + IoT | `pet` MCP server, firewall, Telegram alerts | "where's Mochi?" |
| 8. Add-ons | I2C/UART auto-detect, drivers, policy growth | plug in a sensor, and it uses it |
| 9. Later | LiDAR, charging dock, solar, robot arm | it charges itself; it picks up a ball |
