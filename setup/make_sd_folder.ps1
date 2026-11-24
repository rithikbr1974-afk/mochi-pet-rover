<#
Builds a "paste onto the SD card" folder, for when you don't have the card yet.
Later: flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager, type your Wi-Fi into network-config,
then copy everything in the folder onto the card's "bootfs" drive and replace the files it asks about.
The folder's README.txt has the steps.

    powershell -ExecutionPolicy Bypass -File setup\make_sd_folder.ps1 [-Out D:\Mochi-SD-Card]

No Wi-Fi password is asked or written here: you type it into network-config yourself, just before pasting.
#>
param(
    [string]$Out = "D:\Mochi-SD-Card",
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
function Write-Win([string]$path, [string]$text) {      # README for Notepad: CRLF
    [IO.File]::WriteAllText($path, ($text -replace "`r?`n", "`r`n"), $utf8)
}

$Hostname = ($Hostname.ToLower() -replace '[^a-z0-9-]', '')
$src = Split-Path $PSScriptRoot -Parent          # ...\pet
if (Test-Path "$Out\network-config") {
    $old = [IO.File]::ReadAllText("$Out\network-config")
    if ($old -notmatch 'YOUR-WIFI-NAME') {
        Write-Host "$Out\network-config already has your Wi-Fi in it; it is kept." -ForegroundColor Yellow
        $keepNet = $true
    }
}
if (Test-Path "$Out\pet") { Remove-Item -Recurse -Force "$Out\pet" }
New-Item -ItemType Directory -Force $Out | Out-Null

# --- SSH key: the PC logs in to the Pi with it (the Pi has no password login) ----------------
$keyPath = Join-Path $env:USERPROFILE ".ssh\id_ed25519.pub"
if (Test-Path $keyPath) {
    $keyLine = "  ssh_authorized_keys:`n    - $(Quote-Yaml ([IO.File]::ReadAllText($keyPath).Trim()))"
    $keyNote = "Your PC's SSH key is included, so 'ssh $User@$Hostname.local' works."
} else {
    $keyLine = "  # no SSH key yet: run  ssh-keygen -t ed25519  on the PC, then build this folder again"
    $keyNote = "No SSH key was found on this PC, so nobody can log in to the Pi over SSH. The pet and the app work " +
               "without it; you only need it to update her code (deploy.ps1) or look at logs. To add it: run " +
               "'ssh-keygen -t ed25519' in PowerShell, then build this folder again."
}

# --- user-data: hostname, login, timezone, first-boot installer --------------------------------
Write-Unix "$Out\user-data" @"
#cloud-config
manage_resolv_conf: false
hostname: $Hostname
manage_etc_hosts: true
timezone: $Timezone
user:
  name: $User
  shell: /bin/bash
  lock_passwd: true
$keyLine
  sudo: ALL=(ALL) NOPASSWD:ALL
ssh_pwauth: false
runcmd:
  - [ systemctl, enable, --now, ssh ]
  - [ cp, /boot/firmware/pet/setup/pet-install.service, /etc/systemd/system/pet-install.service ]
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, pet-install.service ]
  - [ systemctl, start, --no-block, pet-install.service ]
"@
Write-Unix "$Out\meta-data" "instance-id: $Hostname-$(Get-Date -Format yyyyMMddHHmmss)`n"

# --- network-config: placeholders you replace in Notepad --------------------------------------
if (-not $keepNet) {
    Write-Unix "$Out\network-config" @"
# Mochi's Wi-Fi. Replace the two YOUR-... values below, keeping the single quotes around them.
# If your name or password contains a ' character, type it twice: Sam's Wi-Fi -> 'Sam''s Wi-Fi'
# The Pi 3 only sees 2.4 GHz Wi-Fi, and WPA3-only networks don't work (WPA2 or mixed is fine).
# To add a backup network (e.g. your phone hotspot), remove the # from the last two lines and fill them in.
# Keep the spaces at the start of each line exactly as they are.
network:
  version: 2
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: "$Country"
      access-points:
        'YOUR-WIFI-NAME':
          password: 'YOUR-WIFI-PASSWORD'
#        'PHONE-HOTSPOT-NAME':
#          password: 'HOTSPOT-PASSWORD'
"@
}

# --- the pet code (text files converted to LF; no phone-app source, data or build output) -----
$textExt = '.py', '.sh', '.service', '.yaml', '.yml', '.html', '.js', '.css', '.txt', '.md', '.json', '.svg', '.webmanifest'
Get-ChildItem -Recurse -File $src | Where-Object {
    $_.FullName -notmatch '\\__pycache__\\|\\data\\|\\android\\|\\build\\|\\\.git\\'
} | ForEach-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    $dst = Join-Path "$Out\pet" $rel
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    if ($textExt -contains $_.Extension.ToLower()) { Write-Unix $dst ([IO.File]::ReadAllText($_.FullName)) }
    else { Copy-Item $_.FullName $dst }
}

# --- README.txt: the steps --------------------------------------------------------------------
Write-Win "$Out\README.txt" @"
MOCHI SD CARD FOLDER
====================
Everything here goes onto the SD card AFTER the card has been flashed with Raspberry Pi OS.
This README.txt doesn't need to go on the card.

What you need: a microSD card (16 GB or more, 64 GB is fine), a card reader for the PC,
and Raspberry Pi Imager (https://www.raspberrypi.com/software/).

STEP 1 - Flash the card (about 10 minutes)
  1. Put the card in the PC and open Raspberry Pi Imager.
  2. Device: Raspberry Pi 3.
     OS: Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit).
     Storage: your SD card (check the size, so you don't pick another drive!).
  3. When it asks about OS customisation, choose NO. (This folder does that job.)
  4. Write. It erases the card. When it says done, take the card out and put it back in,
     because Imager ejects it.
  5. Windows shows a small drive called "bootfs". If Windows offers to FORMAT another drive
     from the same card, click CANCEL. That is the Linux part; never format it.

STEP 2 - Type your Wi-Fi (1 minute)
  1. In this folder, right-click network-config > Open with > Notepad.
  2. Replace YOUR-WIFI-NAME and YOUR-WIFI-PASSWORD (keep the ' quotes around them).
  3. Save (Ctrl+S) and close.

STEP 3 - Paste onto the card (1 minute)
  1. Select these 4 things in this folder:  pet   user-data   network-config   meta-data
  2. Copy (Ctrl+C), open the "bootfs" drive, paste (Ctrl+V).
  3. Windows asks about files that already exist (user-data, network-config, meta-data):
     choose "Replace the files in the destination".
  4. Right-click the bootfs drive > Eject. Wait for "Safe to remove".

STEP 4 - First boot (15-30 minutes)
  Put the card in the Pi and power it on. It installs everything by itself.
  Green LED blinking fast = installing.  Double blink (heartbeat) = Mochi is ready.
  Then on the PC:     powershell -ExecutionPolicy Bypass -File setup\find_pet.ps1
  Or on your phone:   http://$Hostname.local:8080   (or the Mochi app)
  The Pi removes your Wi-Fi password from the card by itself once it is online.

Settings baked into this folder: name $Hostname, login $User, country $Country, timezone $Timezone.
$keyNote

AFTER PASTING: this folder's network-config holds your Wi-Fi password. Delete that file
(or put the YOUR-... placeholders back) once the card is done.

If the LED never reaches the heartbeat: the Wi-Fi name/password is wrong, or the network is
5 GHz-only or WPA3-only. Fix network-config on the card's bootfs drive and power on again.
"@

$n = (Get-ChildItem -Recurse -File $Out).Count
Write-Host "SD card folder ready: $Out ($n files)" -ForegroundColor Green
Write-Host $keyNote
