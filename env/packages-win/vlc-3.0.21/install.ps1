# install.ps1 -- VLC media player 3.0.21 (win32 build) at the x86 path — matches dev-win10
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

# dev-win10 ships the 32-bit VLC at the x86 path; remove any x64/choco copy first
choco uninstall vlc vlc.install -y --no-progress 2>$null | Out-Null
if(Test-Path 'C:\Program Files\VideoLAN\VLC'){ Remove-Item 'C:\Program Files\VideoLAN' -Recurse -Force }
$exe="$env:TEMP\vlc-3.0.21-win32.exe"
curl.exe -L -s -o $exe 'https://get.videolan.org/vlc/3.0.21/win32/vlc-3.0.21-win32.exe'
Start-Process $exe -ArgumentList '/S' -Wait

# self-check
if(-not ((Get-Item 'C:\Program Files (x86)\VideoLAN\VLC\vlc.exe').VersionInfo.ProductVersion -replace ',','.' -like '3.0.21*')){ throw 'verify failed for vlc-3.0.21' }
Write-Host 'OK vlc-3.0.21 @ C:\Program Files (x86)\VideoLAN\VLC'
