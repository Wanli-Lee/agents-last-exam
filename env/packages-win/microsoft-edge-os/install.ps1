# Microsoft Edge — ships with Windows Server 2022; verify-only on fresh images.
$ErrorActionPreference = 'Stop'
$candidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
foreach ($edge in $candidates) {
    if (Test-Path $edge) {
        Write-Host "OK microsoft-edge-os ($edge)"
        return
    }
}
throw 'Microsoft Edge not found — expected on Windows Server 2022 base image'