# install.ps1 -- Ruffle 0.2.0 (Flash/SWF emulator) at C:\Program Files\ruffle\bin — matches dev-win10
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$zip="$env:TEMP\ruffle.zip"
curl.exe -L -s -o $zip 'https://github.com/ruffle-rs/ruffle/releases/download/v0.2.0/ruffle-0.2.0-windows-x86_64.zip'
New-Item -ItemType Directory -Force -Path 'C:\Program Files\ruffle\bin' | Out-Null
& 'C:\Program Files\7-Zip\7z.exe' x -y '-oC:\Program Files\ruffle\bin' $zip | Out-Null
# NOTE: dev-win10 reference SHA256 of ruffle.exe = 5A9D583271E703D7836DCE65FA20C1582BE5C831A2AAC5251DEA64DAFEADDE14

# self-check
if(-not ((Get-Item 'C:\Program Files\ruffle\bin\ruffle.exe').VersionInfo.ProductVersion -like '0.2.0*')){ throw 'verify failed for ruffle-0.2.0' }
Write-Host 'OK ruffle-0.2.0 @ C:\Program Files\ruffle'
