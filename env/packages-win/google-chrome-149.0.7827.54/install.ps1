# Google Chrome 149.0.7827.54 — source: agenthle-private/windows_software_install/chrome/
$ErrorActionPreference = 'Stop'
& (Join-Path (Split-Path $PSScriptRoot -Parent) 'chocolatey-bootstrap\install.ps1')
$chrome = "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe"
if ((Test-Path $chrome) -and ((Get-Item $chrome).VersionInfo.ProductVersion -like '149.*')) {
    Write-Host 'OK google-chrome-149.0.7827.54 already present'
    return
}
choco uninstall googlechrome -y --no-progress 2>$null | Out-Null
choco install -y --ignore-checksums --version=149.0.7827.54 googlechrome --no-progress
if (-not (Test-Path $chrome)) { throw 'verify failed for google-chrome-149.0.7827.54' }
Write-Host "OK google-chrome-149.0.7827.54 ($((Get-Item $chrome).VersionInfo.ProductVersion))"