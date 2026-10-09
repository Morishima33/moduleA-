#requires -Version 7.2
<#
用途：模块完成并通过检查后，只提交本次文件并上传 development。
输入：UTF-8 JSON 请求（module、message、paths、check_report）；检查报告位于仓库之外。
输出：中文说明及 JSON 结果；成功为退出码 0，未通过检查或推送失败为 1。
不安装定时任务，不自动合并 main，不改研究资料；检查失败和网络失败保留本地工作。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RequestFile,
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$LogDirectory
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'Never'
$root = [System.IO.Path]::GetFullPath($RepositoryRoot)
if (-not $LogDirectory) { $LogDirectory = Join-Path (Split-Path -Parent $root) 'runtime/github-upload' }
$logRoot = [System.IO.Path]::GetFullPath($LogDirectory)
$event = [ordered]@{
    schema_version = 1; time_utc = [DateTime]::UtcNow.ToString('o'); module = '';
    status = 'starting'; message_zh = ''; branch = 'development'; paths = @();
    commit = $null; remote_commit = $null; checks = @(); error_code = $null
}
$exitCode = 0
$lock = $null
$gitPath = (Get-Command git -ErrorAction Stop).Source

# 使用 ArgumentList 传参，不拼接 shell 命令；同时读取两个输出流，避免 Git 输出堵塞。
function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $gitPath
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $info.ArgumentList.Add('-C'); $info.ArgumentList.Add($root)
    foreach ($arg in $Arguments) { $info.ArgumentList.Add($arg) }
    $process = [System.Diagnostics.Process]::new(); $process.StartInfo = $info
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(120000)) {
            $process.Kill($true); $process.WaitForExit()
            Stop-Upload 'GIT_TIMEOUT' 'Git 操作超时；本地文件和已有提交已保留，请稍后重试。'
        }
        $output = $stdout.GetAwaiter().GetResult()
        # 错误输出不写入日志，避免认证工具输出意外泄露凭据。
        $null = $stderr.GetAwaiter().GetResult()
        $result = [pscustomobject]@{ Code = $process.ExitCode; Output = $output }
        if ($result.Code -ne 0 -and -not $AllowFailure) {
            Stop-Upload 'GIT_FAILED' ('Git ' + $Arguments[0] + ' 失败；请检查权限、网络或仓库状态。本地工作已保留。')
        }
        return $result
    } finally { $process.Dispose() }
}

# 统一提供可读失败信息，不输出密钥、认证输出或带凭据的远端地址。
function Stop-Upload {
    param([string]$Code, [string]$Text)
    $event.error_code = $Code
    throw [System.InvalidOperationException]::new($Text)
}

# 只接受仓库内的明确相对路径；拒绝通配符、路径穿越和上传目录以外的内容。
function Get-SafePath {
    param([string]$Path)
    $rel = $Path.Replace('\', '/').TrimEnd('/')
    if (-not $rel -or $rel -match '[\x00-\x1f:*?\[\]]' -or $rel.StartsWith('/') -or $rel.StartsWith('-') -or
        @($rel.Split('/') | Where-Object { $_ -in @('', '.', '..') }).Count -gt 0) {
        Stop-Upload 'INVALID_PATH' '文件清单必须使用仓库内的明确相对路径，不接受绝对路径、通配符或上级目录。'
    }
    $full = [System.IO.Path]::GetFullPath((Join-Path $root $rel))
    if (-not $full.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Upload 'INVALID_PATH' '文件路径超出了正式代码仓库。'
    }
    $allowedFiles = @('.gitignore', '.gitattributes', 'AGENTS.md', 'README.md', 'start.cmd', 'start_v2.cmd', 'start_v2.command')
    $top = $rel.Split('/')[0]
    if ($rel -notin $allowedFiles -and $top -notin @('src', 'web', 'tests', 'docs', 'templates', 'config', 'tools', '.github')) {
        Stop-Upload 'EXCLUDED_PATH' ('上传范围不包含：' + $rel)
    }
    if ($rel -match '(?i)(^|/)(\.git|studies|references|governance|environments?|demo_data|runtime|\.runtime|browser_profile|node_modules|__pycache__|_qa|dist|audit_[^/]*)(/|$)' -or
        $rel -match '(?i)(^|/)(\.env(\..*)?|local\.toml|automation_runtime\.toml|credentials[^/]*|id_rsa|id_ed25519)$' -or
        $rel -match '(?i)\.(pyc|pyo|tsbuildinfo|sqlite(-[^/]*)?|db|log|pem|key|png|jpe?g)$' -or
        $rel -match '(?i)^docs/方法学汇报资料(/|$)') {
        Stop-Upload 'EXCLUDED_PATH' ('文件属于资料、个人配置或过程产物，不上传：' + $rel)
    }
    # 每一级都检查，防止目录链接把实际读取范围引到仓库之外。
    $cursor = $full
    while ($cursor.Length -gt $root.Length) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Stop-Upload 'LINK_PATH' '文件清单中不接受符号链接或目录链接。'
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
    return $rel
}

# NUL 分隔的文件列表兼容中文、空格和 Git 的特殊文件名显示方式。
function Get-GitPaths {
    param([string[]]$Arguments)
    $value = (Invoke-Git $Arguments).Output
    return @($value.Split([char]0, [StringSplitOptions]::RemoveEmptyEntries))
}

# 检查报告必须明确通过，且覆盖本次文件的原始字节，防止检查后代码又被修改。
function Assert-CheckedFile {
    param([string]$Rel, [hashtable]$Checked, [long]$MaxBytes)
    if (-not $Checked.ContainsKey($Rel)) { Stop-Upload 'UNCHECKED_FILE' ('检查报告没有覆盖：' + $Rel) }
    $entry = $Checked[$Rel]; $full = Join-Path $root $Rel
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        if (-not $entry.Contains('deleted') -or $entry.deleted -ne $true) {
            Stop-Upload 'CHECKED_FILE_CHANGED' ('文件已删除，但检查报告没有登记删除：' + $Rel)
        }
        return
    }
    if ($entry.Contains('deleted') -and $entry.deleted -eq $true) { Stop-Upload 'CHECKED_FILE_CHANGED' '检查后被删除的文件又重新出现。' }
    if ((Get-Item -LiteralPath $full).Length -gt $MaxBytes) { Stop-Upload 'OVERSIZE_FILE' ('文件超过单文件上传限制：' + $Rel) }
    if (-not $entry.Contains('sha256') -or (Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $entry.sha256) {
        Stop-Upload 'CHECKED_FILE_CHANGED' ('文件与通过检查时的内容不一致：' + $Rel)
    }
}

try {
    $actual = (Invoke-Git @('rev-parse', '--show-toplevel')).Output.Trim()
    if ([System.IO.Path]::GetFullPath($actual) -ne $root) { Stop-Upload 'WRONG_ROOT' '指定目录不是正式 Git 仓库根目录。' }
    $gitDir = (Invoke-Git @('rev-parse', '--absolute-git-dir')).Output.Trim()
    try { $lock = [System.IO.File]::Open((Join-Path $gitDir 'modulea-upload.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { Stop-Upload 'UPLOAD_BUSY' '已有上传任务在执行，请等待其完成后重试。' }
    $policy = Get-Content -LiteralPath (Join-Path $root 'tools/github_upload_policy.json') -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($policy.schema_version -ne 1 -or $policy.remote_name -ne 'origin' -or $policy.branch -ne 'development') {
        Stop-Upload 'INVALID_POLICY' '上传策略格式不正确。'
    }
    $remote = (Invoke-Git @('remote', 'get-url', '--push', 'origin')).Output.Trim()
    if ($remote -ne $policy.remote_url) { Stop-Upload 'WRONG_REMOTE' '推送远端与上传策略不一致；未上传任何文件。' }
    $branch = (Invoke-Git @('branch', '--show-current')).Output.Trim()
    if ($branch -ne 'development') { Stop-Upload 'WRONG_BRANCH' '自动上传只允许在 development 分支执行。' }
    $request = Get-Content -LiteralPath $RequestFile -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    foreach ($field in @('module', 'message', 'paths', 'check_report')) {
        if (-not $request.ContainsKey($field)) { Stop-Upload 'INVALID_REQUEST' ('上传请求缺少字段：' + $field) }
    }
    if (-not ($request.module -is [string]) -or -not $request.module.Trim() -or
        -not ($request.message -is [string]) -or -not $request.message.Trim() -or -not ($request.paths -is [System.Collections.IList])) {
        Stop-Upload 'INVALID_REQUEST' '模块、中文修改说明和文件清单格式不正确。'
    }
    $event.module = $request.module
    $paths = @($request.paths | ForEach-Object { Get-SafePath ([string]$_) } | Select-Object -Unique)
    if ($paths.Count -eq 0) { Stop-Upload 'EMPTY_PATHS' '必须提供本次模块的文件清单。' }
    $event.paths = $paths
    $reportPath = [System.IO.Path]::GetFullPath([string]$request.check_report)
    if ($reportPath.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Stop-Upload 'REPORT_IN_REPO' '检查报告应保存在仓库外的核查目录，避免作为代码上传。'
    }
    $report = Get-Content -LiteralPath $reportPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    if ($report.schema_version -ne 1 -or $report.module -ne $request.module -or $report.passed -ne $true -or
        @($report.checks).Count -eq 0 -or @($report.checks | Where-Object { $_.passed -ne $true -or $_.exit_code -ne 0 }).Count -gt 0) {
        Stop-Upload 'CHECKS_FAILED' '相应检查尚未通过；保留本地工作，不提交或上传。'
    }
    $event.checks = @($report.checks | ForEach-Object { [ordered]@{ name = $_.name; passed = $_.passed; exit_code = $_.exit_code } })
    $checked = @{}
    foreach ($entry in $report.files) {
        $rel = Get-SafePath ([string]$entry.path)
        if ($checked.ContainsKey($rel)) { Stop-Upload 'INVALID_REPORT' '检查报告中存在重复文件。' }
        $checked[$rel] = $entry
    }
    if (@(Get-GitPaths @('diff', '--cached', '--name-only', '-z')).Count -gt 0) {
        Stop-Upload 'DIRTY_INDEX' '暂存区已有内容，请先处理；脚本不会混入其他工作或清空暂存区。'
    }
    # 检查当前跟踪范围，旧仓库历史不得通过简单改远端带入。
    foreach ($rel in @(Get-GitPaths @('ls-files', '-z'))) { $null = Get-SafePath $rel }
    $remoteLines = (Invoke-Git @('ls-remote', '--heads', 'origin', 'refs/heads/development')).Output.Trim()
    if (-not $remoteLines) { Stop-Upload 'MISSING_BRANCH' '远端 development 尚未建立，请先完成独立仓库初始化。' }
    $remoteHead = ($remoteLines -split '\s+')[0]
    $known = Invoke-Git @('cat-file', '-e', ($remoteHead + '^{commit}')) -AllowFailure
    if ($known.Code -ne 0 -or (Invoke-Git @('merge-base', '--is-ancestor', $remoteHead, 'HEAD') -AllowFailure).Code -ne 0) {
        Stop-Upload 'REMOTE_CHANGED' '远端出现新的提交或分歧；已停止上传，请先核对，不会强制覆盖。'
    }
    # 之前推送失败的本地提交可以重试，但其历史中的文件也必须符合上传范围。
    $pending = (Invoke-Git @('rev-list', ($remoteHead + '..HEAD'))).Output.Trim()
    if ($pending) {
        foreach ($commit in ($pending -split '\r?\n')) {
            foreach ($rel in @(Get-GitPaths @('diff-tree', '--no-commit-id', '--name-only', '-r', '-z', $commit))) { $null = Get-SafePath $rel }
        }
    }
    # 先查出明确路径内的变化并核对报告，再暂存；忽略的资料文件不会被强行加入。
    $literalPaths = @($paths | ForEach-Object { ':(literal)' + $_ })
    $changed = @(
        Get-GitPaths (@('diff', '--name-only', '-z', '--') + $literalPaths)
        Get-GitPaths (@('ls-files', '--others', '--exclude-standard', '-z', '--') + $literalPaths)
    ) | Select-Object -Unique
    foreach ($rel in @($changed)) {
        $null = Get-SafePath $rel
        Assert-CheckedFile $rel $checked ([long]$policy.max_file_bytes)
    }
    if (@($changed).Count -gt 0) {
        $null = Invoke-Git (@('add', '--all', '--') + $literalPaths)
        foreach ($rel in @(Get-GitPaths @('diff', '--cached', '--name-only', '-z'))) {
            $null = Get-SafePath $rel
            Assert-CheckedFile $rel $checked ([long]$policy.max_file_bytes)
        }
        if (@(Get-GitPaths @('diff', '--cached', '--name-only', '-z')).Count -gt 0) {
            $null = Invoke-Git @('commit', '-m', ($request.module + '：' + $request.message))
        }
    }
    $head = (Invoke-Git @('rev-parse', 'HEAD')).Output.Trim()
    $event.commit = $head
    if ($head -eq $remoteHead) {
        $event.status = 'no_changes'; $event.remote_commit = $remoteHead
        $event.message_zh = '本次没有需要上传的变化；未产生空提交。'
    } else {
        $pushed = Invoke-Git @('push', '--porcelain', '--set-upstream', 'origin', 'HEAD:refs/heads/development') -AllowFailure
        if ($pushed.Code -ne 0) { Stop-Upload 'PUSH_FAILED' '上传失败；本地提交已经保留。请检查网络、权限或远端变化后重试，不会强制推送。' }
        $verified = (Invoke-Git @('ls-remote', '--heads', 'origin', 'refs/heads/development')).Output.Trim()
        $verifiedHead = ($verified -split '\s+')[0]
        if ($verifiedHead -ne $head) { Stop-Upload 'VERIFY_FAILED' '推送后远端提交号不一致；请核对远端，未执行强制覆盖。' }
        $event.status = 'uploaded'; $event.remote_commit = $verifiedHead
        $event.message_zh = '本次模块已提交并上传 development；这不代替用户验收或大纲确认。'
    }
} catch {
    $exitCode = 1
    $event.status = 'failed'
    if (-not $event.error_code) { $event.error_code = 'INVALID_STATE'; $event.message_zh = '上传配置、请求或仓库状态不完整；本地工作已保留，请核查。' }
    else { $event.message_zh = $_.Exception.Message }
} finally {
    if ($lock) { $lock.Dispose() }
    try {
        if ($logRoot.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or $logRoot -eq $root) {
            throw 'log directory must stay outside code'
        }
        [void][System.IO.Directory]::CreateDirectory($logRoot)
        $logFile = Join-Path $logRoot (([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfff')) + '-' + [Guid]::NewGuid().ToString('N') + '.json')
        [System.IO.File]::WriteAllText($logFile, ($event | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
    } catch { Write-Warning '上传结果日志未能保存，请查看本次输出。' }
}
$event | ConvertTo-Json -Depth 8
exit $exitCode
