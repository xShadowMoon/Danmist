# 打安装包（2026-11-25）：把 build-windows.ps1 打好的 zip 装进一个 Danmist-Setup-v<版本>.exe。
# 用的是 Windows 自带的 IExpress，不用另外装东西。先跑 build-windows.ps1，再跑这个：
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -Version 0.9.6
#
# Output: dist\Danmist-Setup-v<Version>.exe (+ .sha256)
param([Parameter(Mandatory = $true)][string]$Version)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist'
$zip = Join-Path $dist "bili-danmaku-board-v$Version-windows-x64.zip"
if (-not (Test-Path $zip)) { throw "先跑 build-windows.ps1 -Version $Version" }
$stage = Join-Path $dist '_installer'
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force $stage | Out-Null
Copy-Item $zip (Join-Path $stage 'app.zip')
Copy-Item (Join-Path $PSScriptRoot 'install.ps1') (Join-Path $stage 'install.ps1')
Set-Content (Join-Path $stage 'version.txt') -Value $Version -Encoding ascii
$exe = Join-Path $dist "Danmist-Setup-v$Version.exe"
if (Test-Path $exe) { Remove-Item -Force $exe }
$sed = Join-Path $stage 'setup.sed'
@"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$exe
FriendlyName=Danmist Setup
AppLaunched=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File install.ps1
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="app.zip"
FILE1="install.ps1"
FILE2="version.txt"
[SourceFiles]
SourceFiles0=$stage\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@ | Set-Content $sed -Encoding ascii
$p = Start-Process -FilePath "$env:WINDIR\System32\iexpress.exe" -ArgumentList '/N', '/Q', $sed -Wait -PassThru -WindowStyle Hidden
if (-not (Test-Path $exe)) { throw "IExpress 没生成安装包（退出码 $($p.ExitCode)）" }
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
"$hash  Danmist-Setup-v$Version.exe" | Set-Content "$exe.sha256" -Encoding ascii
Remove-Item -Recurse -Force $stage
"{0}  ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB)
"SHA256 $hash"
