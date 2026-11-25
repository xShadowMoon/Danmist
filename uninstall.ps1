# 卸载雾幕（安装版用，「设置 → 应用 → 雾幕 → 卸载」会跑这个）。2026-11-25
# 先问要不要连直播存档和设置一起删；不删的话 data\ 和 config.json 留在原来的文件夹，以后重装还能接着用。
Add-Type -AssemblyName System.Windows.Forms
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ok = [System.Windows.Forms.MessageBox]::Show('卸载雾幕？', '雾幕', 'YesNo', 'Question')
if ($ok -ne 'Yes') { exit 0 }
$all = [System.Windows.Forms.MessageBox]::Show("直播存档、观众备注和设置也一起删掉吗？`n`n选「否」会留在：$dir\data", '雾幕', 'YesNo', 'Question')

# 关掉还在跑的雾幕（只关这个文件夹里的程序）
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath('Programs')) '雾幕.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) '雾幕.lnk'))) {
  Remove-Item -LiteralPath $lnk -Force -ErrorAction SilentlyContinue
}
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Danmist' -Recurse -Force -ErrorAction SilentlyContinue

if ($all -eq 'Yes') {
  Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
} else {
  Get-ChildItem -LiteralPath $dir -Force | Where-Object { $_.Name -notin @('data', 'config.json') } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
[System.Windows.Forms.MessageBox]::Show('雾幕已经卸载了。', '雾幕', 'OK', 'Information') | Out-Null
