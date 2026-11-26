# Build the portable Windows package for a GitHub Release.
# 打包带 Python 的 Windows 版（解压就能用，不用装 Python）。
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1 -Version 0.9.0
#
# Output: dist\Danmist-v<Version>-windows-x64.zip (renamed in 0.9.12; in-app update matches the -windows-x64.zip suffix, so old versions still find it)
# Needs: git, and any Python 3 with pip on this machine (only used to download wheels).
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [string]$PythonVersion = '3.13.13'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = "Danmist-v$Version-windows-x64"
$dist = Join-Path $root 'dist'
$out = Join-Path $dist $name
$cache = Join-Path $dist '_cache'
New-Item -ItemType Directory -Force $dist, $cache | Out-Null
if (Test-Path $out) { Remove-Item -Recurse -Force $out }

# 1. Tracked files only (git archive), so local data/, config.json, admin.key etc. can never get in.
$tar = Join-Path $cache 'src.zip'
git -C $root archive --format=zip -o $tar HEAD
if ($LASTEXITCODE) { throw 'git archive failed' }
Expand-Archive $tar $out
Remove-Item -Recurse -Force (Join-Path $out 'tests'), (Join-Path $out 'scripts'), (Join-Path $out 'docs') -ErrorAction SilentlyContinue

# 2. Embeddable Python from python.org
$embed = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $embed)) {
  Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $embed -UseBasicParsing
}
$py = Join-Path $out 'python'
Expand-Archive $embed $py
$tag = ($PythonVersion -split '\.')[0..1] -join ''
# ._pth: stdlib zip, site-packages, and the app folder (..) so server.py's own modules import.
Set-Content (Join-Path $py "python$tag._pth") -Encoding ascii -Value @("python$tag.zip", '.', 'Lib\site-packages', '..', 'import site')

# 3. Dependencies as Windows wheels
$hostPy = if (Get-Command py -ErrorAction SilentlyContinue) { @('py', '-3') } else { @('python') }
$pyMinor = ($PythonVersion -split '\.')[0..1] -join '.'
& $hostPy[0] $hostPy[1..9] -m pip install --disable-pip-version-check --no-compile --only-binary=:all: `
  --platform win_amd64 --python-version $pyMinor --implementation cp `
  --target (Join-Path $py 'Lib\site-packages') -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE) { throw 'pip install failed' }
Get-ChildItem (Join-Path $py 'Lib\site-packages') -Directory -Filter 'bin' | Remove-Item -Recurse -Force

# 4. Zip
$zip = Join-Path $dist "$name.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
# Python's zipfile writes forward-slash paths; PowerShell 5's Compress-Archive writes backslashes.
& $hostPy[0] $hostPy[1..9] -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], sys.argv[3])" (Join-Path $dist $name) $dist $name
if ($LASTEXITCODE) { throw 'zip failed' }
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $name.zip" | Set-Content (Join-Path $dist "$name.zip.sha256") -Encoding ascii
"{0}  ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB)
"SHA256 $hash"
