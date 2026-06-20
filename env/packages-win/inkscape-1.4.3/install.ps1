# install.ps1 -- Inkscape 1.4.3 (vector editor) — matches dev-win10
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

choco install inkscape --version=1.4.3 --allow-downgrade -y --no-progress --force

# self-check
if(-not ((Get-Item 'C:\Program Files\Inkscape\bin\inkscape.exe').VersionInfo.ProductVersion -eq '1.4.3')){ throw 'verify failed for inkscape-1.4.3' }
Write-Host 'OK inkscape-1.4.3 @ C:\Program Files\Inkscape'
