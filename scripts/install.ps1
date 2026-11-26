# 雾幕安装程序里跑的脚本（2026-11-25）。由 build-installer.ps1 和 app.zip 一起打进 Danmist-Setup.exe。
# 2026-11-26：先出一个窗口，选装到哪个文件夹（默认 %LOCALAPPDATA%\Programs\Danmist，不用管理员）、要不要建桌面 / 开始菜单快捷方式、装完要不要打开。
# 已经装过的话就是升级：还装在原来的地方，config.json 和 data\ 不动。登记到「设置 → 应用」里可以卸载。
# 不弹窗口装（测试用）：-Quiet [-Dir 路径] [-NoDesktop] [-NoMenu] [-NoRun]
param([string]$Dir = '', [switch]$Quiet, [switch]$NoDesktop, [switch]$NoMenu, [switch]$NoRun)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
function Say($text, $icon = 'Information') { [System.Windows.Forms.MessageBox]::Show($text, '雾幕', 'OK', $icon) | Out-Null }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = (Get-Content (Join-Path $here 'version.txt') -ErrorAction SilentlyContinue | Select-Object -First 1)
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Danmist'
$deskLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '雾幕.lnk'
$menuLnk = Join-Path ([Environment]::GetFolderPath('Programs')) '雾幕.lnk'
if ($env:DANMIST_TEST_ROOT) {  # 测试用：登记和快捷方式都放到这个文件夹里，不碰电脑上真装的那份
  $key = 'HKCU:\Software\DanmistInstallTest'
  $deskLnk = Join-Path $env:DANMIST_TEST_ROOT 'desktop-雾幕.lnk'; $menuLnk = Join-Path $env:DANMIST_TEST_ROOT 'menu-雾幕.lnk'
}

# 以前装过：就升级原来那份
$old = ''
try { $old = (Get-ItemProperty -Path $key -ErrorAction Stop).InstallLocation } catch {}
if ($old -and -not (Test-Path -LiteralPath (Join-Path $old 'desktop.py'))) { $old = '' }
$default = if ($old) { $old } else { Join-Path $env:LOCALAPPDATA 'Programs\Danmist' }

# ---------- 选项窗口 ----------
$f = New-Object System.Windows.Forms.Form
$f.Text = if ($old) { "升级雾幕 Danmist 到 v$version" } else { "安装雾幕 Danmist v$version" }
$f.StartPosition = 'CenterScreen'; $f.FormBorderStyle = 'FixedDialog'; $f.MaximizeBox = $false; $f.MinimizeBox = $false
$f.ClientSize = New-Object System.Drawing.Size(520, 300)
$f.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9.5)
$ico = Join-Path $here 'icon.ico'
if (Test-Path $ico) { $f.Icon = New-Object System.Drawing.Icon($ico) }
function Add($c, $x, $y, $w, $h) { $c.Location = New-Object System.Drawing.Point($x, $y); $c.Size = New-Object System.Drawing.Size($w, $h); $f.Controls.Add($c); $c }

$l1 = Add (New-Object System.Windows.Forms.Label) 20 18 480 22
$l1.Text = '装到哪个文件夹'
$path = Add (New-Object System.Windows.Forms.TextBox) 20 44 390 26
$path.Text = $default
$browse = Add (New-Object System.Windows.Forms.Button) 418 42 82 28
$browse.Text = '选文件夹…'
$tip = Add (New-Object System.Windows.Forms.Label) 20 76 480 44
$tip.ForeColor = [System.Drawing.Color]::DimGray
if ($old) {
  $path.ReadOnly = $true; $browse.Enabled = $false
  $tip.Text = "已经装在这里了，这次是升级：直播存档、设置都不动。想换地方的话先在「设置 → 应用」里卸载（选保留存档），再重新装。"
} else {
  $tip.Text = "不用管理员权限。别选 C:\Program Files（那里要管理员才能写）。选了别的文件夹会在里面建一个 Danmist 文件夹。直播存档、设置也存在这里面的 data 文件夹。"
}
$cDesk = Add (New-Object System.Windows.Forms.CheckBox) 20 130 480 26
$cDesk.Text = '在桌面上建「雾幕」快捷方式'
$cDesk.Checked = (-not $old) -or (Test-Path -LiteralPath $deskLnk)
$cMenu = Add (New-Object System.Windows.Forms.CheckBox) 20 158 480 26
$cMenu.Text = '在开始菜单里建「雾幕」'
$cMenu.Checked = (-not $old) -or (Test-Path -LiteralPath $menuLnk)
$cRun = Add (New-Object System.Windows.Forms.CheckBox) 20 186 480 26
$cRun.Text = '装好以后马上打开雾幕'
$cRun.Checked = $true
$ok = Add (New-Object System.Windows.Forms.Button) 300 248 100 32
$ok.Text = if ($old) { '升级' } else { '安装' }
$cancel = Add (New-Object System.Windows.Forms.Button) 408 248 92 32
$cancel.Text = '取消'
$f.AcceptButton = $ok; $f.CancelButton = $cancel
$ok.DialogResult = 'OK'; $cancel.DialogResult = 'Cancel'
$browse.Add_Click({
  $d = New-Object System.Windows.Forms.FolderBrowserDialog
  $d.Description = '雾幕装到哪个文件夹里（会在里面建一个 Danmist 文件夹）'
  $d.SelectedPath = Split-Path -Parent $path.Text
  if ($d.ShowDialog() -eq 'OK') {
    $p = $d.SelectedPath
    if ((Split-Path -Leaf $p) -ne 'Danmist') { $p = Join-Path $p 'Danmist' }
    $path.Text = $p
  }
})
if ($Quiet) {
  if ($Dir -and -not $old) { $path.Text = $Dir }
  $cDesk.Checked = -not $NoDesktop; $cMenu.Checked = -not $NoMenu; $cRun.Checked = -not $NoRun
} elseif ($f.ShowDialog() -ne 'OK') { exit 0 }

$dir = $path.Text.Trim().TrimEnd('\')
if (-not $old -and $dir -and (Test-Path -LiteralPath $dir) -and (Split-Path -Leaf $dir) -ne 'Danmist' -and (Get-ChildItem -LiteralPath $dir -Force | Select-Object -First 1)) {
  $dir = Join-Path $dir 'Danmist'  # 不往一个已经有别的东西的文件夹里直接放（卸载时整个删掉会误删）
}
if (-not $dir -or -not [IO.Path]::IsPathRooted($dir)) { Say '文件夹不对，要写完整的路径，比如 D:\Danmist' 'Warning'; exit 1 }

# 能不能写
try {
  New-Item -ItemType Directory -Force $dir | Out-Null
  $probe = Join-Path $dir ('.write-test-' + [guid]::NewGuid().ToString('N'))
  Set-Content -LiteralPath $probe -Value 'x' -Encoding ascii
  Remove-Item -LiteralPath $probe -Force
} catch { Say "这个文件夹写不进去（可能要管理员权限）：`n$dir`n`n换一个，比如 D:\Danmist" 'Warning'; exit 1 }

# 正在运行就先请它关掉（文件被占着换不了）
$running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) }
if ($running) { Say "雾幕正在运行，先关掉雾幕的窗口，再重新打开安装程序。" 'Warning'; exit 1 }

try {
  $tmp = Join-Path $env:TEMP ('danmist-setup-' + [guid]::NewGuid().ToString('N'))
  Expand-Archive -LiteralPath (Join-Path $here 'app.zip') -DestinationPath $tmp -Force
  $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
  # 拷过去；升级时不碰设置和存档
  Get-ChildItem $src.FullName -Force | Where-Object { $_.Name -notin @('config.json', 'data') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $dir -Recurse -Force
  }
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

  # 快捷方式：双击就是软件窗口。没勾的话，以前建过的（指向这份雾幕的）也删掉
  $pyw = Join-Path $dir 'python\pythonw.exe'
  $icon = Join-Path $dir 'static\art\icon.ico'
  # 换过看板娘的话，升级以后快捷方式还用换的那个图标（2026-11-26）
  $mine = Get-ChildItem (Join-Path $dir 'data\mascot') -Filter 'mascot-*.ico' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
  $lnkIcon = if ($mine) { $mine.FullName } else { $icon }
  $sh = New-Object -ComObject WScript.Shell
  foreach ($pair in @(@($menuLnk, $cMenu.Checked), @($deskLnk, $cDesk.Checked))) {
    $lnk = $pair[0]
    if ($pair[1]) {
      $s = $sh.CreateShortcut($lnk)
      $s.TargetPath = $pyw; $s.Arguments = '"' + (Join-Path $dir 'desktop.py') + '"'; $s.WorkingDirectory = $dir
      $s.IconLocation = $lnkIcon; $s.Description = '雾幕 Danmist'; $s.Save()
    } elseif (Test-Path -LiteralPath $lnk) {
      if ($sh.CreateShortcut($lnk).WorkingDirectory.TrimEnd('\') -ieq $dir) { Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue }
    }
  }
  New-Item -ItemType Directory -Force (Join-Path $dir 'data') | Out-Null
  Set-Content (Join-Path $dir 'data\shortcut-made') -Value 'installer' -Encoding ascii  # 软件第一次打开时不再自己建桌面快捷方式

  # 登记到「设置 → 应用」：能看到版本、能卸载
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

if ($cRun.Checked) {
  # 装好就打开（第一次在软件里选平台、填直播间号）
  Start-Process -FilePath $pyw -ArgumentList ('"' + (Join-Path $dir 'desktop.py') + '"') -WorkingDirectory $dir
} else {
  $where = if ($cDesk.Checked) { '双击桌面上的「雾幕」打开。' } elseif ($cMenu.Checked) { '在开始菜单里找「雾幕」打开。' } else { "打开方法：双击 $dir\python\pythonw.exe 旁边的 start.bat。" }
  Say ("装好了，在：$dir`n" + $where)
}
