# 雾幕安装程序里跑的脚本（2026-11-25）。由 build-installer.ps1 和 app.zip 一起打进 Danmist-Setup.exe。
# 装到 %LOCALAPPDATA%\Programs\Danmist（不用管理员），建开始菜单和桌面快捷方式，登记到「设置 → 应用」里可以卸载。
# 已经装过的话就是升级：config.json 和 data\ 不动。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
function Say($text, $icon = 'Information') { [System.Windows.Forms.MessageBox]::Show($text, '雾幕', 'OK', $icon) | Out-Null }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dir = Join-Path $env:LOCALAPPDATA 'Programs\Danmist'
$version = (Get-Content (Join-Path $here 'version.txt') -ErrorAction SilentlyContinue | Select-Object -First 1)

# 正在运行就先请它关掉（文件被占着换不了）
$running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) }
if ($running) { Say "雾幕正在运行，先关掉雾幕的窗口，再重新打开安装程序。" 'Warning'; exit 1 }

try {
  $tmp = Join-Path $env:TEMP ('danmist-setup-' + [guid]::NewGuid().ToString('N'))
  Expand-Archive -LiteralPath (Join-Path $here 'app.zip') -DestinationPath $tmp -Force
  $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
  New-Item -ItemType Directory -Force $dir | Out-Null
  # 拷过去；升级时不碰设置和存档
  Get-ChildItem $src.FullName -Force | Where-Object { $_.Name -notin @('config.json', 'data') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $dir -Recurse -Force
  }
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

  # 快捷方式：开始菜单 + 桌面，双击就是软件窗口
  $pyw = Join-Path $dir 'python\pythonw.exe'
  $icon = Join-Path $dir 'static\art\icon.ico'
  $sh = New-Object -ComObject WScript.Shell
  foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath('Programs')) '雾幕.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) '雾幕.lnk'))) {
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $pyw; $s.Arguments = '"' + (Join-Path $dir 'desktop.py') + '"'; $s.WorkingDirectory = $dir
    $s.IconLocation = $icon; $s.Description = '雾幕 Danmist'; $s.Save()
  }
  New-Item -ItemType Directory -Force (Join-Path $dir 'data') | Out-Null
  Set-Content (Join-Path $dir 'data\shortcut-made') -Value 'installer' -Encoding ascii

  # 登记到「设置 → 应用」：能看到版本、能卸载
  $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Danmist'
  New-Item -Path $key -Force | Out-Null
  $size = [int]((Get-ChildItem $dir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
  $props = @{
    DisplayName = '雾幕 Danmist'; DisplayVersion = "$version"; Publisher = 'xShadowMoon'; DisplayIcon = $icon; InstallLocation = $dir
    UninstallString = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $dir 'uninstall.ps1') + '"'
    URLInfoAbout = 'https://github.com/xShadowMoon/danmist'
  }
  foreach ($k in $props.Keys) { Set-ItemProperty -Path $key -Name $k -Value $props[$k] }
  foreach ($k in 'NoModify', 'NoRepair') { New-ItemProperty -Path $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
  New-ItemProperty -Path $key -Name EstimatedSize -Value $size -PropertyType DWord -Force | Out-Null
} catch {
  Say ("安装没成功：" + $_.Exception.Message) 'Error'
  exit 1
}

# 装好就打开（第一次会问直播间号）
Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $dir 'desktop.py') + '"') -WorkingDirectory $dir
