# install.ps1 -- LibreOffice 25.2.7.2 (Still/archive build) — matches dev-win10
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

choco uninstall libreoffice-fresh -y --no-progress 2>$null | Out-Null
$msi="$env:TEMP\LibreOffice_25.2.7.2_Win_x86-64.msi"
curl.exe -L -s -o $msi 'https://downloadarchive.documentfoundation.org/libreoffice/old/25.2.7.2/win/x86_64/LibreOffice_25.2.7.2_Win_x86-64.msi'
Start-Process msiexec.exe -ArgumentList '/i',"`"$msi`"",'/qn','/norestart' -Wait

# self-check
if(-not ((Get-Item 'C:\Program Files\LibreOffice\program\soffice.exe').VersionInfo.ProductVersion -like '25.2.7*')){ throw 'verify failed for libreoffice-25.2.7.2' }
Write-Host 'OK libreoffice-25.2.7.2 @ C:\Program Files\LibreOffice'
