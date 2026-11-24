<#
Finds Mochi on the home network (no screen needed) and shows how the first-boot install is going.
  powershell -ExecutionPolicy Bypass -File pet\setup\find_pet.ps1          # status + last log lines
  powershell -ExecutionPolicy Bypass -File pet\setup\find_pet.ps1 -Follow  # keep watching the log
#>
param([string]$Hostname = "mochi", [string]$User = "pet-admin", [switch]$Follow)
$ErrorActionPreference = "SilentlyContinue"

function Find-Pi {
    # 1. by name (mDNS: mochi.local)
    $r = Resolve-DnsName "$Hostname.local" -Type A -ErrorAction SilentlyContinue | Where-Object IPAddress | Select-Object -First 1
    if ($r) { return $r.IPAddress }
    # 2. by Raspberry Pi network chip (MAC prefix) after pinging the whole local /24
    $ip = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
        Select-Object -First 1 | ForEach-Object { $_.IPv4Address.IPAddress }
    if (-not $ip) { return $null }
    $base = $ip -replace '\.\d+$', ''
    Write-Host "Not found by name; scanning $base.1-254 ..."
    $tasks = 1..254 | ForEach-Object { (New-Object Net.NetworkInformation.Ping).SendPingAsync("$base.$_", 400) }
    [Threading.Tasks.Task]::WaitAll($tasks) | Out-Null
    $piMacs = '^(B8-27-EB|DC-A6-32|E4-5F-01|D8-3A-DD|2C-CF-67|28-CD-C1)'   # Raspberry Pi; B8-27-EB = Pi 3
    $n = Get-NetNeighbor -AddressFamily IPv4 | Where-Object { $_.LinkLayerAddress -match $piMacs -and $_.IPAddress -like "$base.*" } |
        Select-Object -First 1
    if ($n) { return $n.IPAddress }
    return $null
}

$ip = Find-Pi
if (-not $ip) {
    Write-Host @"
Mochi isn't on the network yet. Check:
  - the first boot takes 1-3 min before Wi-Fi joins (the green LED flickers);
  - the Wi-Fi is 2.4 GHz and WPA2 (the Pi 3 can't see 5 GHz or WPA3-only);
  - the power bank gives at least 2.4 A.
Then run this again.
"@ -ForegroundColor Yellow
    exit 1
}
Write-Host "Mochi is at $ip" -ForegroundColor Green

$ssh = @("-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8", "$User@$ip")
if ($Follow) { ssh @ssh "sudo tail -n 40 -f /var/log/pet-install.log"; exit }
# one line, no double quotes: Windows PowerShell 5.1 mangles quotes and newlines in native arguments
$remote = @(
    "echo '--- install log (last lines)'",
    "sudo tail -n 15 /var/log/pet-install.log 2>/dev/null || echo 'not started yet'",
    "echo '--- state'",
    "if [ -f /var/lib/pet-installed ]; then echo 'install: DONE'; else echo 'install: running'; fi",
    'echo pet service: $(systemctl is-active pet 2>/dev/null)',
    "echo temperature: `$(vcgencmd measure_temp 2>/dev/null) '  power:' `$(vcgencmd get_throttled 2>/dev/null) '(0x0 = power OK)'"
) -join '; '
ssh @ssh $remote
Write-Host "`nPhone page: http://$Hostname.local:8080   (or http://${ip}:8080)" -ForegroundColor Cyan
