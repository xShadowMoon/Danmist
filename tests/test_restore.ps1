#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$copyRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $copyRoot) -ne '副本-codex') { throw '只在副本-codex 运行测试。' }
$scriptFile = Join-Path $copyRoot '恢复数据.ps1'
$fixture = Join-Path $PSScriptRoot ('.restore-test-' + [guid]::NewGuid().ToString('N'))
$daily = Join-Path $fixture '备份\数据'
$data = Join-Path $fixture 'data'
$archive = 'data-20261112.zip'
$restoreFixtureState = @{ Live = 0; Requests = 0; FailOnSecond = $false; FailSwap = $false }

# 只替换 B 站查询。假 Root 不会执行真实服务控制；任何其他网络访问都直接报错。
function Invoke-RestMethod([string]$Uri, $Headers, [int]$TimeoutSec) {
    if ($Uri -ne 'https://api.live.bilibili.com/room/v1/Room/room_init?id=373317') { throw "意外联网：$Uri" }
    $restoreFixtureState.Requests++
    $status = if ($restoreFixtureState.FailOnSecond -and $restoreFixtureState.Requests -eq 2) { 1 } else { $restoreFixtureState.Live }
    return @{ code = 0; data = @{ live_status = $status } }
}
function Invoke-WebRequest { throw '测试不允许访问正式服务。' }
function Get-CimInstance { throw '测试不允许枚举正式服务。' }
function Stop-Process { throw '测试不允许结束进程。' }
function Move-Item([string]$LiteralPath, [string]$Destination) {
    if ($restoreFixtureState.FailSwap -and (Split-Path -Leaf $LiteralPath) -like '.restore-stage-*') {
        throw '模拟暂存目录移动失败'
    }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}

function Assert-True($Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
}
function Assert-Throws([scriptblock]$Operation, [string]$Pattern) {
    try { & $Operation | Out-Null } catch {
        if ($_.Exception.Message -match $Pattern) { return }
        throw
    }
    throw "应抛出 $Pattern。"
}
function New-TestZip([string]$Name, [object[]]$Entries) {
    $zip = [IO.Compression.ZipFile]::Open((Join-Path $daily $Name), [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($row in $Entries) {
            $entry = $zip.CreateEntry($row.path)
            if ($row.attributes) { $entry.ExternalAttributes = $row.attributes }
            if ($row.bytes) {
                $stream = $entry.Open()
                try { $stream.Write($row.bytes, 0, $row.bytes.Length) } finally { $stream.Dispose() }
            } else {
                $writer = New-Object IO.StreamWriter($entry.Open())
                try { $writer.Write([string]$row.text) } finally { $writer.Dispose() }
            }
        }
    } finally { $zip.Dispose() }
}
function Get-FixtureFiles {
    return @(
        Get-ChildItem -LiteralPath $fixture -Recurse -File -Force | Sort-Object FullName |
        ForEach-Object { $_.FullName + ':' + (Get-FileHash -LiteralPath $_.FullName).Hash }
    ) -join [Environment]::NewLine
}

try {
    [void][IO.Directory]::CreateDirectory($daily)
    [void][IO.Directory]::CreateDirectory($data)
    Set-Content -LiteralPath (Join-Path $data '373317.json') -Value 'original'
    Set-Content -LiteralPath (Join-Path $data 'extra.json') -Value 'before only'
    $gzipText = '{"uid":1,"name":"test","text":"gzip restored","t":100,"face":"","guard":0}' + [char]10
    $gzipBuffer = New-Object IO.MemoryStream
    $gzipWriter = New-Object IO.Compression.GZipStream($gzipBuffer, [IO.Compression.CompressionMode]::Compress, $true)
    $gzipInput = [Text.Encoding]::UTF8.GetBytes($gzipText)
    $gzipWriter.Write($gzipInput, 0, $gzipInput.Length)
    $gzipWriter.Dispose()
    $gzipBytes = $gzipBuffer.ToArray()
    $gzipBuffer.Dispose()
    New-TestZip $archive @(
        @{ path = '373317.json'; text = 'restored' },
        @{ path = 'history/373317/20260101-1234.dm.jsonl.gz'; bytes = $gzipBytes },
        @{ path = 'history/373317/测试.json'; text = 'history record' }
    )

    $before = Get-FixtureFiles
    $listing = & $scriptFile -Root $fixture
    Assert-True ($listing -match 'data-20261112\.zip') '没有列出假备份。'
    $preview = @(& $scriptFile -Root $fixture -Backup $archive -DryRun)
    Assert-True ($preview -contains '覆盖 373317.json') '预览未列出覆盖文件。'
    Assert-True ($preview -contains '新增 history/373317/测试.json') '预览未列出新增文件。'
    Assert-True ($preview -contains '移出当前数据目录 extra.json') '预览未列出移出文件。'
    Assert-True ($restoreFixtureState.Requests -eq 0 -and $before -ceq (Get-FixtureFiles)) '预览更改文件或联网。'

    $restoreFixtureState.Live = 1
    Assert-Throws { & $scriptFile -Root $fixture -Backup $archive } '正在直播'
    Assert-True ($before -ceq (Get-FixtureFiles)) '直播状态拦截时更改了文件。'
    $restoreFixtureState.Live = $null
    Assert-Throws { & $scriptFile -Root $fixture -Backup $archive } '无法确认'
    Assert-True ($before -ceq (Get-FixtureFiles)) '未知状态拦截时更改了文件。'
    $restoreFixtureState.Live = 0
    $restoreFixtureState.Requests = 0

    New-TestZip 'data-20261113.zip' @(@{ path = '..\escaped.txt'; text = 'bad path' })
    New-TestZip 'data-20261114.zip' @(@{ path = 'bad:stream'; text = 'bad path' })
    New-TestZip 'data-20261115.zip' @(@{ path = 'NUL.txt'; text = 'bad path' })
    New-TestZip 'data-20261116.zip' @(@{ path = 'x'; text = 'file' }, @{ path = 'X/sub'; text = 'collision' })
    New-TestZip 'data-20261117.zip' @(@{ path = 'x.json'; text = 'file' }, @{ path = 'X.json'; text = 'duplicate' })
    New-TestZip 'data-20261118.zip' @(@{ path = 'link'; text = 'target'; attributes = -1610612736 })
    foreach ($day in 13, 14, 15, 16, 17, 18) {
        Assert-Throws { & $scriptFile -Root $fixture -Backup "data-202611$day.zip" -DryRun } '不安全|同名|重复|链接'
    }
    Assert-Throws { & $scriptFile -Root $fixture -Backup "..\$archive" -DryRun } '文件名'
    Assert-True ($restoreFixtureState.Requests -eq 0) '恶意 ZIP 在校验前查询了网络。'

    $result = & $scriptFile -Root $fixture -Backup $archive
    Assert-True ($result -match '已恢复') '没有报告恢复成功。'
    Assert-True ($restoreFixtureState.Requests -eq 2) '恢复前未做两次下播检查。'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $data '373317.json')) -ceq 'restored') '恢复内容不符。'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $data 'history\373317\测试.json')) -ceq 'history record') '没有恢复嵌套文件。'
    $gzipPath = Join-Path $data 'history\373317\20260101-1234.dm.jsonl.gz'
    Assert-True ([Convert]::ToBase64String([IO.File]::ReadAllBytes($gzipPath)) -ceq [Convert]::ToBase64String($gzipBytes)) '恢复后 gzip 字节不同。'
    & py -3 -X utf8 -B -c "import server,sys; server.DIR=sys.argv[1]; rows=server.History(373317).dm('20260101-1234'); assert len(rows)==1 and rows[0]['text']=='gzip restored'" $fixture
    Assert-True ($LASTEXITCODE -eq 0) '服务不能读取恢复后的 gzip 弹幕。'
    Assert-True (!(Test-Path -LiteralPath (Join-Path $data 'extra.json'))) '残留备份中没有的旧文件。'
    $saved = @(Get-ChildItem -LiteralPath (Join-Path $fixture '备份') -Directory | Where-Object Name -Like '恢复前-*')
    Assert-True ($saved.Count -eq 1) '未保留一份恢复前数据。'
    Assert-True ((Get-Content -LiteralPath (Join-Path $saved[0].FullName 'data\373317.json')) -ceq 'original') '恢复前副本内容不符。'
    Assert-True (Test-Path -LiteralPath (Join-Path $saved[0].FullName 'data\extra.json')) '恢复前副本缺少旧文件。'

    # 解压后开播也必须拒绝，不得换掉现有 data。
    $restoreFixtureState.Requests = 0
    $restoreFixtureState.FailOnSecond = $true
    Set-Content -LiteralPath (Join-Path $data 'after.json') -Value 'keep'
    Assert-Throws { & $scriptFile -Root $fixture -Backup $archive } '正在直播'
    Assert-True (Test-Path -LiteralPath (Join-Path $data 'after.json')) '第二次下播检查没有保护当前数据。'
    Assert-True (@(Get-ChildItem -LiteralPath $fixture -Force -Filter '.restore-stage-*').Count -eq 0) '解压暂存目录未清理。'
    $restoreFixtureState.FailOnSecond = $false
    $restoreFixtureState.FailSwap = $true
    Assert-Throws { & $scriptFile -Root $fixture -Backup $archive } '已保留原数据.*模拟暂存目录移动失败'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $data '373317.json')) -ceq 'restored') '换目录失败后没有回退原数据。'
    Assert-True (Test-Path -LiteralPath (Join-Path $data 'after.json')) '回退丢失本次恢复前的数据。'
    '恢复测试通过：列出、预览无写入、下播检查、危险 ZIP、完整恢复、保留旧数据、换目录失败回退。'
} finally {
    if (Test-Path -LiteralPath $fixture) {
        $target = (Resolve-Path -LiteralPath $fixture).ProviderPath
        if ((Split-Path -Parent $target) -ne $PSScriptRoot -or (Split-Path -Leaf $target) -notmatch '^\.restore-test-[0-9a-f]{32}$') {
            throw '拒绝清理测试目录。'
        }
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
