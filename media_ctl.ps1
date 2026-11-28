# 控制音乐客户端的播放 / 暂停（2026-11-28）：用 Windows 自带的「媒体控制」（任务栏音量那里能看到在放什么的那套），
# 只动名字对得上的那个程序（网易云 cloudmusic、QQ 音乐 QQMusic），别的程序（游戏、浏览器）不碰。
# 用法：powershell -NoProfile -File media_ctl.ps1 -App cloudmusic -Do status|play|pause
param([string]$App = 'cloudmusic', [string]$Do = 'status')
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
  function Wait-Op($op, [type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); [void]$task.Wait(5000); $task.Result }
  $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
  $mgr = Wait-Op ($mgrType::RequestAsync()) $mgrType
  $s = $mgr.GetSessions() | Where-Object { $_.SourceAppUserModelId -match [regex]::Escape($App) } | Select-Object -First 1
  if ($Do -eq 'list') { $mgr.GetSessions() | ForEach-Object { "$($_.SourceAppUserModelId) $($_.GetPlaybackInfo().PlaybackStatus)" }; exit 0 }
  if (-not $s) { 'none'; exit 0 }
  $st = "$($s.GetPlaybackInfo().PlaybackStatus)"
  if ($Do -eq 'play' -and $st -ne 'Playing') { [void](Wait-Op ($s.TryPlayAsync()) ([bool])) }
  if ($Do -eq 'pause' -and $st -eq 'Playing') { [void](Wait-Op ($s.TryPauseAsync()) ([bool])) }
  $st
} catch { 'error ' + $_.Exception.Message }
