# Visual Studio Code 1.112.0 per-user @ C:\Users\User\AppData\Local\Programs\Microsoft VS Code
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$code = 'C:\Users\User\AppData\Local\Programs\Microsoft VS Code\Code.exe'
$dst = Split-Path $code -Parent

choco uninstall vscode vscode.install -y --no-progress 2>$null | Out-Null
if (Test-Path "$env:ProgramFiles\Microsoft VS Code") {
    Remove-Item "$env:ProgramFiles\Microsoft VS Code" -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $dst | Out-Null
$exe = Join-Path $env:TEMP 'VSCodeUserSetup-x64-1.112.0.exe'
curl.exe --fail --location --silent --show-error -o $exe 'https://update.code.visualstudio.com/1.112.0/win32-x64-user/stable'
$prevLocal = $env:LOCALAPPDATA
$env:LOCALAPPDATA = 'C:\Users\User\AppData\Local'
try {
    Start-Process $exe -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/MERGETASKS=!runcode' -Wait
} finally {
    $env:LOCALAPPDATA = $prevLocal
}

if (-not (Test-Path $code)) { throw 'verify failed for vscode-1.112.0' }
Write-Host "OK vscode-1.112.0 @ $dst"