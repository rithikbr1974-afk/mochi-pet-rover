<#
Sends the current pet code from this PC to Mochi over SSH and restarts it.
  powershell -ExecutionPolicy Bypass -File pet\setup\deploy.ps1 [-Target mochi.local]
#>
param([string]$Target = "mochi.local", [string]$User = "pet-admin")
$ErrorActionPreference = "Stop"
$src = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path $env:TEMP "pet-deploy"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
$utf8 = New-Object System.Text.UTF8Encoding($false)
$textExt = '.py', '.sh', '.service', '.yaml', '.yml', '.html', '.js', '.css', '.txt', '.md', '.json'
Get-ChildItem -Recurse -File $src | Where-Object { $_.FullName -notmatch '\\__pycache__\\|\\data\\|\\android\\' } | ForEach-Object {
    $out = Join-Path $tmp $_.FullName.Substring($src.Length + 1)
    New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
    if ($textExt -contains $_.Extension.ToLower()) {
        [IO.File]::WriteAllText($out, ([IO.File]::ReadAllText($_.FullName) -replace "`r`n", "`n"), $utf8)
    } else { Copy-Item $_.FullName $out }
}
$tar = Join-Path $env:TEMP "pet-deploy.tgz"
tar -czf $tar -C $tmp .
scp -o StrictHostKeyChecking=accept-new $tar "${User}@${Target}:/tmp/pet-deploy.tgz"
if ($LASTEXITCODE) { throw "copy failed" }
ssh "${User}@${Target}" "sudo rm -rf /opt/pet.new && sudo mkdir /opt/pet.new && sudo tar -xzf /tmp/pet-deploy.tgz -C /opt/pet.new && sudo chown -R root:root /opt/pet.new && sudo rm -rf /opt/pet && sudo mv /opt/pet.new /opt/pet && sudo cp /opt/pet/setup/pet.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart pet && systemctl is-active pet"
Remove-Item -Recurse -Force $tmp, $tar
