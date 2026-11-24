<#
Builds Mochi.apk without Gradle: aapt2 -> javac -> d8 -> zipalign -> apksigner (debug key).
  powershell -ExecutionPolicy Bypass -File pet\android\build_apk.ps1
Output: pet\android\build\Mochi.apk  (copy it to the phone and install; allow "install unknown apps").
#>
param(
    [string]$Tools = "C:\android-tools",
    [string]$BuildTools = "35.0.0",
    [string]$Platform = "android-35"
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$bt = "$Tools\sdk\build-tools\$BuildTools"
$jar = "$Tools\sdk\platforms\$Platform\android.jar"
$jdk = Get-ChildItem "$Tools" -Directory -Filter "jdk-*" | Select-Object -First 1
if (-not $jdk) { throw "no JDK in $Tools" }
$env:JAVA_HOME = $jdk.FullName
$env:PATH = "$($jdk.FullName)\bin;$env:PATH"
foreach ($p in "$bt\aapt2.exe", "$bt\d8.bat", "$bt\zipalign.exe", "$bt\apksigner.bat", $jar) { if (-not (Test-Path $p)) { throw "missing $p" } }

$out = "$here\build"
if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force "$out\classes", "$out\dex" | Out-Null

function Run($exe, [string[]]$a) { & $exe @a; if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)" } }

Write-Host "1/5 resources"
Run "$bt\aapt2.exe" @("compile", "--dir", "$here\res", "-o", "$out\res.zip")
Run "$bt\aapt2.exe" @("link", "-o", "$out\base.apk", "-I", $jar, "--manifest", "$here\AndroidManifest.xml",
    "-A", "$here\assets", "--min-sdk-version", "24", "--target-sdk-version", "34", "$out\res.zip")

Write-Host "2/5 java"
$src = Get-ChildItem -Recurse "$here\src" -Filter *.java | ForEach-Object FullName
Run "javac" (@("-source", "8", "-target", "8", "-bootclasspath", $jar, "-classpath", $jar, "-Xlint:-options",
    "-encoding", "UTF-8", "-d", "$out\classes") + $src)

Write-Host "3/5 dex"
$classes = Get-ChildItem -Recurse "$out\classes" -Filter *.class | ForEach-Object FullName
Run "$bt\d8.bat" (@("--min-api", "24", "--lib", $jar, "--output", "$out\dex") + $classes)

Write-Host "4/5 package"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open("$out\base.apk", "Update")
[void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, "$out\dex\classes.dex", "classes.dex")
$zip.Dispose()
Run "$bt\zipalign.exe" @("-p", "-f", "4", "$out\base.apk", "$out\aligned.apk")

Write-Host "5/5 sign (debug key)"
$ks = Join-Path $env:USERPROFILE ".android\debug.keystore"
if (-not (Test-Path $ks)) { throw "no debug keystore at $ks (Android Studio/Unity creates it on the first build)" }
Run "$bt\apksigner.bat" @("sign", "--ks", $ks, "--ks-pass", "pass:android", "--key-pass", "pass:android",
    "--ks-key-alias", "androiddebugkey", "--out", "$out\Mochi.apk", "$out\aligned.apk")
Run "$bt\apksigner.bat" @("verify", "$out\Mochi.apk")
Write-Host "Built $out\Mochi.apk ($([math]::Round((Get-Item "$out\Mochi.apk").Length / 1KB)) KB)" -ForegroundColor Green
