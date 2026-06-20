# install.ps1 -- DaVinci Resolve 21.0 (free edition) — current version on the target.
# idempotent, pins the CURRENT version (NOT a downgrade). Requires admin. ~3-4 GB.
#
# Download is automatable via Blackmagic's register API — the only trick is sending a
# browser User-Agent (without it the API returns HTTP 400).
$ErrorActionPreference='Stop'
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12

$resolve='C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe'
if((Test-Path $resolve) -and ((Get-Item $resolve).VersionInfo.ProductVersion -like '21.0*')){
  Write-Host 'OK davinci-resolve-21.0 already present'; return
}

# 1) signed official download URL for DaVinci Resolve 21.0 (Windows)
$downloadId='e2096c01ac344e33926f9da9b5097c4f'
$ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0 Safari/537.36'
$reg='{"firstname":"Eval","lastname":"Lab","email":"agenthle.sv@gmail.com","phone":"4155550100","country":"us","street":"1 Market St","city":"San Francisco","state":"California","product":"DaVinci Resolve"}'
$url = Invoke-RestMethod -Method Post -Uri "https://www.blackmagicdesign.com/api/register/us/download/$downloadId" `
  -ContentType 'application/json;charset=UTF-8' `
  -Headers @{'User-Agent'=$ua;'Origin'='https://www.blackmagicdesign.com';'Referer'='https://www.blackmagicdesign.com/support/download/'} `
  -Body $reg
$zip="$env:TEMP\DaVinci_Resolve_21.0_Windows.zip"
curl.exe -L -s -o $zip $url
if((Get-Item $zip).Length -lt 1GB){ throw "download too small: $url" }

# 2) extract installer .exe -> embedded MSI
& 'C:\Program Files\7-Zip\7z.exe' x -y "-o$env:TEMP\dv210" $zip | Out-Null
$exe = Get-ChildItem "$env:TEMP\dv210" -Filter *.exe -Recurse | Select-Object -First 1
& 'C:\Program Files\7-Zip\7z.exe' x -y "-o$env:TEMP\dv210msi" $exe.FullName | Out-Null
$msi = Get-ChildItem "$env:TEMP\dv210msi" -Filter *.msi -Recurse | Select-Object -First 1

# 3) silent install
Start-Process msiexec.exe -ArgumentList '/i',('"'+$msi.FullName+'"'),'/qn','/norestart' -Wait

# 4) self-check
if(-not ((Get-Item $resolve).VersionInfo.ProductVersion -like '21.0*')){ throw 'verify failed for davinci-resolve-21.0' }
Write-Host 'OK davinci-resolve-21.0 @ C:\Program Files\Blackmagic Design\DaVinci Resolve'
