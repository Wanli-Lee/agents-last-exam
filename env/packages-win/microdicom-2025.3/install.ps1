# MicroDicom 2025.3.0.4183 @ C:\Program Files\MicroDicom
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$dst = 'C:\Program Files\MicroDicom'
$exe = Join-Path $dst 'mDicom.exe'
if ((Test-Path $exe) -and ((Get-Item $exe).VersionInfo.ProductVersion -like '2025.3*')) {
    Write-Host 'OK microdicom-2025.3 already present'
    return
}

$zip = Join-Path $env:TEMP 'microdicom-2025.3.0.4183.zip'
if ($env:MICRODICOM_ARCHIVE_URL) {
    curl.exe --fail --location --silent --show-error -o $zip $env:MICRODICOM_ARCHIVE_URL
} else {
    $url = 'https://storage.googleapis.com/ale-data-public/env-packages-win/microdicom-2025.3.0.4183.zip'
    try {
        curl.exe --fail --location --silent --show-error -o $zip $url
    } catch {
        throw @"
MicroDicom 2025.3.0.4183 download failed.
Publish microdicom-2025.3.0.4183.zip to gs://ale-data-public/env-packages-win/
or set MICRODICOM_ARCHIVE_URL. Error: $_
"@
    }
}

$extract = Join-Path $env:TEMP 'microdicom-2025.3-extract'
if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extract | Out-Null
Expand-Archive -Path $zip -DestinationPath $extract -Force

$root = $extract
$inner = Get-ChildItem $extract -Directory | Select-Object -First 1
if ($inner -and (Test-Path (Join-Path $inner.FullName 'mDicom.exe'))) { $root = $inner.FullName }
if (-not (Test-Path (Join-Path $root 'mDicom.exe'))) {
    throw 'archive does not contain mDicom.exe at top level'
}

if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Copy-Item $root $dst -Recurse -Force

if (-not (Test-Path $exe) -or ((Get-Item $exe).VersionInfo.ProductVersion -notlike '2025.3*')) {
    throw 'verify failed for microdicom-2025.3'
}
Write-Host "OK microdicom-2025.3 @ $dst"