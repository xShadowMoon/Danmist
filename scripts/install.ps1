# 雾幕安装程序里跑的脚本（2026-11-25）。由 build-installer.ps1 和 app.zip 一起打进 Danmist-Setup.exe。
# 2026-11-26：做成常见软件那样的安装向导：左边看板娘横幅；第一页选装到哪、要不要创建快捷方式；第二页进度条；第三页装好了、要不要启动雾幕。
# 默认装到 %LOCALAPPDATA%\Programs\Danmist（不用管理员）。已经装过的话就是升级：还装在原来的地方，config.json 和 data\ 不动。
# 登记到「设置 → 应用」里可以卸载。
# 不弹窗口装（测试用）：-Quiet [-Dir 路径] [-NoDesktop] [-NoMenu] [-NoRun]
param([string]$Dir = '', [switch]$Quiet, [switch]$NoDesktop, [switch]$NoMenu, [switch]$NoRun)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
function Say($text, $icon = 'Information') { if ($Quiet) { Write-Output $text } else { [System.Windows.Forms.MessageBox]::Show($text, '雾幕', 'OK', $icon) | Out-Null } }

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

# ---------- 真正装的那一步（窗口和 -Quiet 都走这里）----------
function Resolve-Dir([string]$p) {
  $d = $p.Trim().TrimEnd('\')
  if (-not $old -and $d -and (Test-Path -LiteralPath $d) -and (Split-Path -Leaf $d) -ne 'Danmist' -and (Get-ChildItem -LiteralPath $d -Force | Select-Object -First 1)) {
    $d = Join-Path $d 'Danmist'  # 不往一个已经有别的东西的文件夹里直接放（卸载时整个删掉会误删）
  }
  if (-not $d -or -not [IO.Path]::IsPathRooted($d)) { throw '文件夹不对，要写完整的路径，比如 D:\Danmist' }
  try {
    New-Item -ItemType Directory -Force $d | Out-Null
    $probe = Join-Path $d ('.write-test-' + [guid]::NewGuid().ToString('N'))
    Set-Content -LiteralPath $probe -Value 'x' -Encoding ascii
    Remove-Item -LiteralPath $probe -Force
  } catch { throw "这个文件夹写不进去（可能要管理员权限）：`n$d`n`n换一个，比如 D:\Danmist" }
  $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) }
  if ($running) { throw '雾幕正在运行，先关掉雾幕的窗口，再点一次安装。' }
  return $d
}

# $step：进度回调 { param($pct, $text) }
function Install-App([string]$dir, [bool]$desk, [bool]$menu, $step) {
  & $step 3 '正在解压…'
  $tmp = Join-Path $env:TEMP ('danmist-setup-' + [guid]::NewGuid().ToString('N'))
  Expand-Archive -LiteralPath (Join-Path $here 'app.zip') -DestinationPath $tmp -Force
  $src = (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName
  # 一个一个文件拷，进度条跟着走；升级时不碰设置和存档
  $files = @(Get-ChildItem -LiteralPath $src -Recurse -File -Force | Where-Object {
    $rel = $_.FullName.Substring($src.Length + 1)
    -not ($rel -eq 'config.json' -or $rel -like 'data\*')
  })
  $n = [Math]::Max(1, $files.Count)
  for ($i = 0; $i -lt $files.Count; $i++) {
    $fi = $files[$i]
    $dst = Join-Path $dir $fi.FullName.Substring($src.Length + 1)
    $dd = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dd)) { New-Item -ItemType Directory -Force $dd | Out-Null }
    [IO.File]::Copy($fi.FullName, $dst, $true)
    if ($i % 25 -eq 0) { & $step (5 + [int](85 * $i / $n)) ('正在复制文件… ' + $fi.Name) }
  }
  Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

  & $step 92 '正在创建快捷方式…'
  $pyw = Join-Path $dir 'python\pythonw.exe'
  $icon = Join-Path $dir 'static\art\icon.ico'
  # 换过看板娘的话，升级以后快捷方式还用换的那个图标（2026-11-26）
  $mine = Get-ChildItem (Join-Path $dir 'data\mascot') -Filter 'mascot-*.ico' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
  $lnkIcon = if ($mine) { $mine.FullName } else { $icon }
  $sh = New-Object -ComObject WScript.Shell
  foreach ($pair in @(@($menuLnk, $menu), @($deskLnk, $desk))) {
    $lnk = $pair[0]
    if ($pair[1]) {
      $s = $sh.CreateShortcut($lnk)
      $s.TargetPath = $pyw; $s.Arguments = '"' + (Join-Path $dir 'desktop.py') + '"'; $s.WorkingDirectory = $dir
      $s.IconLocation = $lnkIcon; $s.Description = '雾幕 Danmist'; $s.Save()
    } elseif (Test-Path -LiteralPath $lnk) {  # 没勾：以前建过的（指向这份雾幕的）删掉
      if ($sh.CreateShortcut($lnk).WorkingDirectory.TrimEnd('\') -ieq $dir) { Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue }
    }
  }
  New-Item -ItemType Directory -Force (Join-Path $dir 'data') | Out-Null
  Set-Content (Join-Path $dir 'data\shortcut-made') -Value 'installer' -Encoding ascii  # 软件第一次打开时不再自己建桌面快捷方式

  & $step 97 '正在登记到「设置 → 应用」…'
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
  & $step 100 '装好了'
}
function Start-App([string]$dir) {
  Start-Process -FilePath (Join-Path $dir 'python\pythonw.exe') -ArgumentList ('"' + (Join-Path $dir 'desktop.py') + '"') -WorkingDirectory $dir
}

if ($Quiet) {
  try {
    $d = Resolve-Dir $(if ($Dir -and -not $old) { $Dir } else { $default })
    Install-App $d (-not $NoDesktop) (-not $NoMenu) { param($p, $t) }
    if (-not $NoRun) { Start-App $d }
    Write-Output "装好了：$d"
  } catch { Write-Output ('安装没成功：' + $_.Exception.Message); exit 1 }
  exit 0
}

# ---------- 安装向导窗口 ----------
$C = @{ ink = [Drawing.Color]::FromArgb(31, 41, 55); gray = [Drawing.Color]::FromArgb(100, 112, 128); line = [Drawing.Color]::FromArgb(226, 231, 238)
        accent = [Drawing.Color]::FromArgb(74, 140, 196); bar = [Drawing.Color]::FromArgb(246, 248, 251); white = [Drawing.Color]::White }
$font = { param($size, $bold) New-Object Drawing.Font('Microsoft YaHei UI', $size, $(if ($bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular })) }
$f = New-Object Windows.Forms.Form
$f.Text = if ($old) { '雾幕 Danmist 升级' } else { '雾幕 Danmist 安装' }
$f.StartPosition = 'CenterScreen'; $f.FormBorderStyle = 'FixedSingle'; $f.MaximizeBox = $false
$f.ClientSize = New-Object Drawing.Size(680, 440); $f.BackColor = $C.white; $f.Font = & $font 9.5 $false
$ico = Join-Path $here 'icon.ico'
if (Test-Path $ico) { $f.Icon = New-Object Drawing.Icon($ico) }
function Put($parent, $c, $x, $y, $w, $h) { $c.Location = New-Object Drawing.Point($x, $y); $c.Size = New-Object Drawing.Size($w, $h); $parent.Controls.Add($c); $c }

# 左边的横幅：渐变底 + 看板娘 + 名字
$side = Put $f (New-Object Windows.Forms.Panel) 0 0 210 384
$side.Add_Paint({ param($s, $e)
  $r = New-Object Drawing.Rectangle(0, 0, $s.Width, $s.Height)
  $b = New-Object Drawing.Drawing2D.LinearGradientBrush($r, [Drawing.Color]::FromArgb(28, 40, 66), [Drawing.Color]::FromArgb(70, 96, 150), 70)
  $e.Graphics.FillRectangle($b, $r); $b.Dispose()
})
$logoFile = Join-Path $here 'logo.png'
if (Test-Path $logoFile) {
  $pic = Put $side (New-Object Windows.Forms.PictureBox) 45 70 120 120
  $pic.SizeMode = 'Zoom'; $pic.BackColor = [Drawing.Color]::Transparent; $pic.Image = [Drawing.Image]::FromFile($logoFile)
}
$brand = Put $side (New-Object Windows.Forms.Label) 0 206 210 40
$brand.Text = '雾幕'; $brand.Font = & $font 20 $true; $brand.ForeColor = $C.white; $brand.BackColor = [Drawing.Color]::Transparent; $brand.TextAlign = 'MiddleCenter'
$sub = Put $side (New-Object Windows.Forms.Label) 0 246 210 22
$sub.Text = "Danmist  v$version"; $sub.ForeColor = [Drawing.Color]::FromArgb(200, 214, 235); $sub.BackColor = [Drawing.Color]::Transparent; $sub.TextAlign = 'MiddleCenter'
$tag = Put $side (New-Object Windows.Forms.Label) 0 330 210 40
$tag.Text = "B 站直播弹幕工具`n免费 · 开源"; $tag.ForeColor = [Drawing.Color]::FromArgb(170, 188, 214); $tag.BackColor = [Drawing.Color]::Transparent; $tag.TextAlign = 'MiddleCenter'; $tag.Font = & $font 8.5 $false

# 下面一条按钮栏
$sep = Put $f (New-Object Windows.Forms.Panel) 0 384 680 1
$sep.BackColor = $C.line
$foot = Put $f (New-Object Windows.Forms.Panel) 0 385 680 55
$foot.BackColor = $C.bar
function Btn($text, $x, $primary) {
  $b = Put $foot (New-Object Windows.Forms.Button) $x 12 104 32
  $b.Text = $text; $b.FlatStyle = 'Flat'; $b.Cursor = 'Hand'
  if ($primary) { $b.BackColor = $C.accent; $b.ForeColor = $C.white; $b.FlatAppearance.BorderSize = 0; $b.Font = & $font 9.5 $true }
  else { $b.BackColor = $C.white; $b.ForeColor = $C.ink; $b.FlatAppearance.BorderColor = $C.line }
  $b
}
$btnGo = Btn $(if ($old) { '升级' } else { '安装' }) 448 $true
$btnCancel = Btn '取消' 562 $false

# 三页：选项 / 正在安装 / 装好了
function Page { $p = Put $f (New-Object Windows.Forms.Panel) 210 0 470 384; $p.BackColor = $C.white; $p }
function Title($p, $t, $s) {
  $a = Put $p (New-Object Windows.Forms.Label) 32 30 420 34; $a.Text = $t; $a.Font = & $font 16 $true; $a.ForeColor = $C.ink
  $b = Put $p (New-Object Windows.Forms.Label) 32 68 420 40; $b.Text = $s; $b.ForeColor = $C.gray
}
$pOpt = Page
Title $pOpt $(if ($old) { '升级雾幕' } else { '安装雾幕' }) $(if ($old) { "把雾幕升级到 v$version。直播存档、设置都会保留。" } else { '选好安装位置和要创建的快捷方式，然后点「安装」。' })
$lp = Put $pOpt (New-Object Windows.Forms.Label) 32 118 400 22; $lp.Text = '安装位置'; $lp.Font = & $font 9.5 $true; $lp.ForeColor = $C.ink
$path = Put $pOpt (New-Object Windows.Forms.TextBox) 32 144 312 28; $path.Text = $default
$browse = Put $pOpt (New-Object Windows.Forms.Button) 352 142 88 29; $browse.Text = '浏览…'; $browse.FlatStyle = 'Flat'; $browse.FlatAppearance.BorderColor = $C.line
$hint = Put $pOpt (New-Object Windows.Forms.Label) 32 176 410 40; $hint.ForeColor = $C.gray; $hint.Font = & $font 8.5 $false
if ($old) { $path.ReadOnly = $true; $browse.Enabled = $false; $hint.Text = '已经装在这里。想换位置，先在 Windows「设置 → 应用」里卸载（选保留存档），再重新安装。' }
else { $hint.Text = '不需要管理员权限。直播存档和设置也存在这个文件夹里的 data 文件夹。' }
$lo = Put $pOpt (New-Object Windows.Forms.Label) 32 228 400 22; $lo.Text = '附加选项'; $lo.Font = & $font 9.5 $true; $lo.ForeColor = $C.ink
$cDesk = Put $pOpt (New-Object Windows.Forms.CheckBox) 32 254 400 26; $cDesk.Text = '创建桌面快捷方式'; $cDesk.Checked = (-not $old) -or (Test-Path -LiteralPath $deskLnk)
$cMenu = Put $pOpt (New-Object Windows.Forms.CheckBox) 32 282 400 26; $cMenu.Text = '创建开始菜单快捷方式'; $cMenu.Checked = (-not $old) -or (Test-Path -LiteralPath $menuLnk)

$pProg = Page; $pProg.Visible = $false
Title $pProg $(if ($old) { '正在升级' } else { '正在安装' }) '请稍候，一般十几秒就好。'
$bar = Put $pProg (New-Object Windows.Forms.ProgressBar) 32 150 408 18; $bar.Style = 'Continuous'
$stat = Put $pProg (New-Object Windows.Forms.Label) 32 176 408 22; $stat.ForeColor = $C.gray; $stat.AutoEllipsis = $true

$pDone = Page; $pDone.Visible = $false
Title $pDone $(if ($old) { '升级完成' } else { '安装完成' }) ''
$doneText = Put $pDone (New-Object Windows.Forms.Label) 32 76 410 60; $doneText.ForeColor = $C.gray
$cRun = Put $pDone (New-Object Windows.Forms.CheckBox) 32 150 400 26; $cRun.Text = '启动雾幕'; $cRun.Checked = $true

$browse.Add_Click({
  $d = New-Object Windows.Forms.FolderBrowserDialog
  $d.Description = '雾幕装到哪个文件夹里（会在里面建一个 Danmist 文件夹）'
  $d.SelectedPath = Split-Path -Parent $path.Text
  if ($d.ShowDialog() -eq 'OK') {
    $p = $d.SelectedPath
    if ((Split-Path -Leaf $p) -ne 'Danmist') { $p = Join-Path $p 'Danmist' }
    $path.Text = $p
  }
})
$script:stage = 'opt'; $script:dir = ''
$btnCancel.Add_Click({ if ($script:stage -ne 'busy') { $f.Close() } })
$f.Add_FormClosing({ param($s, $e) if ($script:stage -eq 'busy') { $e.Cancel = $true } })
$btnGo.Add_Click({
  if ($script:stage -eq 'done') {
    if ($cRun.Checked) { Start-App $script:dir }
    $f.Close(); return
  }
  try { $script:dir = Resolve-Dir $path.Text } catch { [Windows.Forms.MessageBox]::Show($_.Exception.Message, '雾幕', 'OK', 'Warning') | Out-Null; return }
  $script:stage = 'busy'
  $pOpt.Visible = $false; $pProg.Visible = $true; $btnGo.Enabled = $false; $btnCancel.Enabled = $false
  [Windows.Forms.Application]::DoEvents()
  try {
    Install-App $script:dir $cDesk.Checked $cMenu.Checked { param($p, $t) $bar.Value = [Math]::Min(100, $p); $stat.Text = $t; [Windows.Forms.Application]::DoEvents() }
  } catch {
    $script:stage = 'opt'
    [Windows.Forms.MessageBox]::Show('安装没成功：' + $_.Exception.Message, '雾幕', 'OK', 'Error') | Out-Null
    $pProg.Visible = $false; $pOpt.Visible = $true; $btnGo.Enabled = $true; $btnCancel.Enabled = $true
    return
  }
  $script:stage = 'done'
  $where = if ($cDesk.Checked) { '以后双击桌面上的「雾幕」就能打开。' } elseif ($cMenu.Checked) { '以后在开始菜单里找「雾幕」打开。' } else { "装在 $($script:dir)。" }
  $doneText.Text = "雾幕已经装好了。$where"
  $pProg.Visible = $false; $pDone.Visible = $true
  $btnGo.Text = '完成'; $btnGo.Enabled = $true; $btnCancel.Visible = $false
})
$f.AcceptButton = $btnGo
[void]$f.ShowDialog()
