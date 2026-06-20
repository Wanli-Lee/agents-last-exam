# install.ps1 -- Eclipse Temurin JRE 21.0.10+7 at the Adoptium default path — required by Metabase launcher
# idempotent, version-pinned to dev-win10. Run as admin.
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$msi="$env:TEMP\temurin-jre-21.0.10.7.msi"
curl.exe -L -s -o $msi 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.10%2B7/OpenJDK21U-jre_x64_windows_hotspot_21.0.10_7.msi'
Start-Process msiexec.exe -ArgumentList '/i',"`"$msi`"",'/qn','/norestart' -Wait

# self-check
if(-not (Test-Path 'C:\Program Files\Eclipse Adoptium\jre-21.0.10.7-hotspot\bin\java.exe')){ throw 'verify failed for adoptium-jre-21.0.10.7' }
Write-Host 'OK adoptium-jre-21.0.10.7 @ C:\Program Files\Eclipse Adoptium\jre-21.0.10.7-hotspot'
