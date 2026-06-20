# install.ps1 -- Wireshark 4.4.14 x64 — matches dev-win10 (offline pcap analysis; Npcap optional)
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

choco uninstall wireshark -y --no-progress 2>$null | Out-Null
$exe="$env:TEMP\Wireshark-4.4.14-x64.exe"
curl.exe -L -s -o $exe 'https://1.na.dl.wireshark.org/win64/all-versions/Wireshark-4.4.14-x64.exe'
Start-Process $exe -ArgumentList '/S' -Wait

# self-check
if(-not ((Get-Item 'C:\Program Files\Wireshark\Wireshark.exe').VersionInfo.ProductVersion -like '4.4.14*')){ throw 'verify failed for wireshark-4.4.14' }
Write-Host 'OK wireshark-4.4.14 @ C:\Program Files\Wireshark'
