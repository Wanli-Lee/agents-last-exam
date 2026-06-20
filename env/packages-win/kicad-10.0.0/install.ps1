# KiCad 10.0.0 per-user @ C:\Users\User\AppData\Local\Programs\KiCad\10.0
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$dst = 'C:\Users\User\AppData\Local\Programs\KiCad\10.0'
$kicad = Join-Path $dst 'bin\kicad.exe'
if ((Test-Path $kicad) -and ((Get-Item $kicad).VersionInfo.ProductVersion -like '10.0.0*')) {
    Write-Host 'OK kicad-10.0.0 already present'
    return
}

$installer = Join-Path $env:TEMP 'kicad-10.0.0-1-x86_64.exe'
if ($env:KICAD100_INSTALLER_URL) {
    curl.exe --fail --location --silent --show-error -o $installer $env:KICAD100_INSTALLER_URL
} else {
    $urls = @(
        'https://sourceforge.net/projects/kicad.mirror/files/10.0.0/kicad-10.0.0-1-x86_64.exe/download',
        'https://storage.googleapis.com/ale-data-public/env-packages-win/kicad-10.0.0-1-x86_64.exe'
    )
    $last = ''
    $ok = $false
    foreach ($url in $urls) {
        try {
            curl.exe --fail --location --silent --show-error -o $installer $url
            $ok = $true
            break
        } catch {
            $last = "$_"
        }
    }
    if (-not $ok) { throw "KiCad 10.0.0 download failed (set KICAD100_INSTALLER_URL): $last" }
}

choco uninstall kicad -y --no-progress 2>$null | Out-Null
if (Test-Path 'C:\Program Files\KiCad') { Remove-Item 'C:\Program Files\KiCad' -Recurse -Force }
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }

Start-Process $installer -ArgumentList '/S' -Wait

$pf = 'C:\Program Files\KiCad\10.0'
if (-not (Test-Path (Join-Path $pf 'bin\kicad.exe'))) {
    throw "KiCad installer did not produce $pf"
}
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item (Join-Path $pf '*') $dst -Recurse -Force

if (-not (Test-Path $kicad) -or ((Get-Item $kicad).VersionInfo.ProductVersion -notlike '10.0.0*')) {
    throw 'verify failed for kicad-10.0.0'
}
Write-Host "OK kicad-10.0.0 @ $dst"