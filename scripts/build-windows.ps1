# Build the portable Windows package for a GitHub Release.
# 打包带 Python 的 Windows 版（解压就能用，不用装 Python）。
#
#   powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1 -Version 0.9.0
#
# Output: dist\Danmist-v<Version>-windows-x64.zip (renamed in 0.9.12; in-app update matches the -windows-x64.zip suffix, so old versions still find it)
# Needs: git, and any Python 3 with pip on this machine (only used to download wheels).
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [string]$PythonVersion = '3.13.13',
  [switch]$SkipTests  # only for test builds you hand to yourself; a real Release must not use it
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# 0. 先跑全部测试再打包（2026-11-28：0.9.15.4 两个脚本重名、页面一半没加载，网页检查能拦住，但发版时没跑）。
#    后台测试 + 网页检查（tests/run_ui.py：开演示服务，用浏览器打开每个页面，脚本一报错就算不过）。有一项不过就不打包。
if (-not $SkipTests) {
  $py = (Get-Command py -ErrorAction SilentlyContinue)
  $pyArgs = if ($py) { @('-3', '-B') } else { @('-B') }
  $pyExe = if ($py) { 'py' } else { 'python' }
  Push-Location $root
  try {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $pyExe @pyArgs -m unittest discover -s tests 2>&1 | Select-Object -Last 3 | ForEach-Object { "  $_" }
    $unit = $LASTEXITCODE
    & $pyExe @pyArgs (Join-Path 'tests' 'run_ui.py') 2>&1 | Where-Object { $_ -match 'FAIL|SKIP|全部通过' } | ForEach-Object { "  $_" }
    $ui = $LASTEXITCODE
    $ErrorActionPreference = $old
  } finally { Pop-Location }
  if ($unit -ne 0) { throw 'Backend tests failed - not packaging (后台测试没过，不打包)' }
  if ($ui -ne 0) { throw 'Page checks failed - not packaging (网页检查没过，不打包)' }
  'Tests passed (测试全过)'
}
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
# 3b. App window (2026-11-26): pywebview on Windows' own WebView2 + its .NET bridge. proxy_tools only ships as a source
#     package, so build its (pure Python) wheel here first.
$site = Join-Path $py 'Lib\site-packages'
& $hostPy[0] $hostPy[1..9] -m pip install --disable-pip-version-check --no-compile --only-binary=:all: --upgrade `
  --platform win_amd64 --python-version $pyMinor --implementation cp --target $site --no-deps `
  'pywebview==6.2.1' 'pythonnet==3.2.1' 'clr_loader==0.3.1' 'cffi>=1.17' 'pycparser' 'bottle' 'typing_extensions'
if ($LASTEXITCODE) { throw 'pip install (window) failed' }
$wheels = Join-Path $root 'dist\_cache\wheels'
& $hostPy[0] $hostPy[1..9] -m pip wheel --disable-pip-version-check --no-deps 'proxy_tools==0.1.0' -w $wheels
if ($LASTEXITCODE) { throw 'pip wheel proxy_tools failed' }
& $hostPy[0] $hostPy[1..9] -m pip install --disable-pip-version-check --no-compile --upgrade --target $site --no-deps (Get-ChildItem $wheels -Filter 'proxy_tools-*.whl' | Select-Object -First 1).FullName
if ($LASTEXITCODE) { throw 'pip install proxy_tools failed' }
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
