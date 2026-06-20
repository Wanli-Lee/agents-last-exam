# Mesa3D software OpenGL (llvmpipe) — source: agenthle-private/windows_software_install/mesa3d/
# Requires 7-Zip at C:\Program Files\7-Zip\7z.exe (choco 7zip).
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if ($env:GALLIUM_DRIVER -eq 'llvmpipe') {
    Write-Host 'OK mesa3d-26.1.1 (GALLIUM_DRIVER=llvmpipe already set)'
    return
}

& (Join-Path (Split-Path $PSScriptRoot -Parent) 'chocolatey-bootstrap\install.ps1')
if (-not (Test-Path 'C:\Program Files\7-Zip\7z.exe')) {
    choco install -y --version=26.1.0 7zip --no-progress
}

$ver = '26.1.1'
$url = "https://github.com/pal1000/mesa-dist-win/releases/download/$ver/mesa3d-$ver-release-msvc.7z"
$dl = 'C:\AgentHLE\dl\mesa'
New-Item -ItemType Directory -Force -Path $dl | Out-Null
Invoke-WebRequest $url -OutFile "$dl\mesa.7z" -UseBasicParsing
& 'C:\Program Files\7-Zip\7z.exe' x -y "-o$dl" "$dl\mesa.7z"
cmd /c "cd /d $dl && systemwidedeploy.cmd 1"
setx /m GALLIUM_DRIVER llvmpipe | Out-Null

if ($env:GALLIUM_DRIVER -ne 'llvmpipe') {
    [Environment]::SetEnvironmentVariable('GALLIUM_DRIVER', 'llvmpipe', 'Machine')
}
Write-Host 'OK mesa3d-26.1.1 (GALLIUM_DRIVER=llvmpipe; restart cua-server to pick up in running services)'