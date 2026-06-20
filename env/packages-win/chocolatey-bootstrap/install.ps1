# Bootstrap Chocolatey (prerequisite for choco-pinned apps). Idempotent.
$ErrorActionPreference = 'Stop'
if (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Host "OK chocolatey-bootstrap ($(& choco --version))"
    return
}
Set-ExecutionPolicy Bypass -Scope Process -Force
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) { throw 'Chocolatey bootstrap failed' }
Write-Host "OK chocolatey-bootstrap ($(& choco --version))"