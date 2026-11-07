# 本机工作台入口：只复用经HTTP核实的同目录实例；隐藏启动、明确安全停止，不安装或强杀。
param(
    [int]$Port = 8780,
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [string]$PythonPath = '',
    [switch]$Stop,
    [switch]$Restart
)
$ErrorActionPreference = 'Stop'
# PowerShell 7可将预期的status退出3视为异常；WindowsPowerShell5没有这个选项。
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$pythonExecutable = $null
$stdoutPath = $null
$stderrPath = $null

# CLI在所有业务失败时仍返回标准JSON，不能只凭native退出码丢弃具体原因。
function Invoke-ServiceControl([string]$Action) {
    $cliArguments = @('-B', '-m', 'modulea', 'service', $Action, '--port', [string]$Port, '--json')
    if ($Action -eq 'stop') { $cliArguments += '--confirmed' }
    $lines = @(& $pythonExecutable @cliArguments)
    $nativeExitCode = $LASTEXITCODE
    try { $value = ($lines -join [Environment]::NewLine) | ConvertFrom-Json }
    catch { throw ('服务状态没有返回可读JSON，退出码：' + $nativeExitCode) }
    if (-not $value -or $value.schema_version -ne 'ModuleA.service_probe.1' -or
        -not ($value.state -is [string]) -or -not ($value.ready -is [bool])) {
        throw '服务状态格式不正确，未启动或停止任何进程。'
    }
    return [PSCustomObject]@{ Value = $value; ExitCode = $nativeExitCode }
}

# 状态原因直接沿同一CLI提供的中文事实，未知状态默认拒绝。
function Get-ServiceReason($Probe) {
    $reasons = @($Probe.reasons_zh | Where-Object { $_ -is [string] -and $_.Trim() })
    if ($reasons.Count) { return ($reasons -join '；') }
    return ('服务状态：' + $Probe.state)
}

# 服务身份必须属于脚本所在项目，并保留启动前固定的数据、运行目录与代码身份。
function Assert-ServiceExpectation($Probe, $Original = $null) {
    $expected = $Probe.expected
    foreach ($name in @('project_root', 'data_root', 'runtime_dir', 'static_dir', 'code_signature')) {
        if (-not ($expected.$name -is [string]) -or -not $expected.$name) {
            throw ('服务状态缺少本机身份字段：' + $name)
        }
        if ($Original -and $expected.$name -cne $Original.$name) {
            throw '启动期间目录、配置或代码已改变，请重新核对后启动。'
        }
    }
    if (-not [string]::Equals($expected.project_root, $projectRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw '状态返回的项目目录与此启动入口不同，未启动服务。'
    }
    if ($Probe.url -cne ('http://127.0.0.1:' + $Port)) { throw '服务地址与请求端口不同。' }
    if ($Probe.ready) {
        if ($Probe.state -ne 'running') { throw '服务尚未处于可运行状态。' }
        foreach ($name in @('project_root', 'data_root', 'runtime_dir', 'static_dir', 'code_signature')) {
            if ($Probe.actual.$name -cne $expected.$name) { throw ('运行实例身份不同：' + $name) }
        }
    }
    return $expected
}

# 仅用户交互入口在就绪后打开浏览器；服务进程始终携带--no-browser。
function Show-Workbench($Probe, [string]$Message) {
    Write-Host $Message
    Write-Host ('打开：' + $Probe.url)
    Write-Host ('数据目录：' + $Probe.expected.data_root)
    if (-not $NoBrowser) { Start-Process -FilePath $Probe.url }
}

# 日志目录不能经junction或符号链接写入runtime外，更不能落到研究目录。
function Assert-LogDirectories([string]$RuntimeDirectory) {
    foreach ($path in @($RuntimeDirectory, (Join-Path $RuntimeDirectory 'service'), (Join-Path $RuntimeDirectory 'service\logs'))) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw ('日志目录不能是文件或目录链接：' + $path)
            }
        }
    }
}

try {
    if ($Stop -and $Restart) { throw 'Stop和Restart不能同时使用。' }
    if ($CheckOnly -and ($Stop -or $Restart)) { throw 'CheckOnly仅作临时启动检查，不能同时停止或重启。' }
    if ($Port -lt 0 -or $Port -gt 65535 -or ($Port -eq 0 -and -not $CheckOnly)) {
        throw '常驻端口须为1至65535；仅CheckOnly允许端口0。'
    }
    # Python查找顺序保持旧入口；只作版本核对，不安装软件或读取研究。
    $candidates = @()
    if ($PythonPath) { $candidates = @($PythonPath) }
    else {
        if ($env:MODULEA_PYTHON) { $candidates += $env:MODULEA_PYTHON }
        $candidates += (Join-Path $env:USERPROFILE 'scoop\apps\python\current\python.exe')
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $candidates += $command.Source }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
            if ($LASTEXITCODE -eq 0) { $pythonExecutable = (Get-Item -LiteralPath $candidate).FullName; break }
        }
    }
    if (-not $pythonExecutable) { throw '未找到Python 3.11或更新版本；请配置MODULEA_PYTHON或传入PythonPath。' }
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = Join-Path $projectRoot 'src'
    Set-Location -LiteralPath $projectRoot
    Write-Host ('使用Python：' + $pythonExecutable)
    if ($CheckOnly) {
        & $pythonExecutable -B -m modulea serve --port $Port --no-browser --check
        $checkExitCode = $LASTEXITCODE
        if ($checkExitCode -ne 0) { throw ('临时启动检查失败，退出码：' + $checkExitCode) }
        Write-Host '临时启动检查通过；本次没有启动常驻工作台。'
        exit 0
    }
    if ($Stop -or $Restart) {
        $stopped = Invoke-ServiceControl 'stop'
        if ($stopped.ExitCode -ne 0 -or $stopped.Value.state -ne 'stopped') {
            throw ('安全停止未完成：' + (Get-ServiceReason $stopped.Value))
        }
        Write-Host (Get-ServiceReason $stopped.Value)
        if ($Stop) { exit 0 }
    }
    $response = Invoke-ServiceControl 'status'
    $probe = $response.Value
    if ($probe.state -eq 'running' -and $probe.ready -and $response.ExitCode -eq 0) {
        $null = Assert-ServiceExpectation $probe
        Show-Workbench $probe '已复用本项目、同数据与同代码的现有工作台。'
        exit 0
    }
    if ($probe.state -ne 'not_running' -or $probe.preflight_ready -ne $true) {
        throw ('未启动工作台：' + (Get-ServiceReason $probe))
    }
    $expected = Assert-ServiceExpectation $probe
    # 日志只落本机配置的runtime；唯一时间戳和随机名保证不覆盖既有记录。
    $logFolder = Join-Path $expected.runtime_dir 'service\logs'
    Assert-LogDirectories $expected.runtime_dir
    $null = New-Item -ItemType Directory -Path $logFolder -Force
    Assert-LogDirectories $expected.runtime_dir
    $logName = 'workbench_{0}_{1}_{2}' -f $Port, (Get-Date -Format 'yyyyMMdd_HHmmss_fff'), ([Guid]::NewGuid().ToString('N'))
    $stdoutPath = Join-Path $logFolder ($logName + '.stdout.log')
    $stderrPath = Join-Path $logFolder ($logName + '.stderr.log')
    if ((Test-Path -LiteralPath $stdoutPath) -or (Test-Path -LiteralPath $stderrPath)) { throw '新日志名称已存在，未覆盖原记录。' }
    $process = Start-Process -FilePath $pythonExecutable -ArgumentList @('-B', '-m', 'modulea', 'serve', '--port', [string]$Port, '--no-browser') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
    Write-Host ('标准输出日志：' + $stdoutPath)
    Write-Host ('错误日志：' + $stderrPath)
    # 进程创建不等于服务可用；只轮询轻量HTTP身份，绝不换端口或按PID清理。
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $response = Invoke-ServiceControl 'status'
        $probe = $response.Value
        if ($probe.state -eq 'running' -and $probe.ready -and $response.ExitCode -eq 0) {
            $null = Assert-ServiceExpectation $probe $expected
            Show-Workbench $probe '工作台已在后台就绪；关闭本启动窗口不会退出服务。'
            exit 0
        }
        $process.Refresh()
        if ($process.HasExited) { throw ('工作台启动进程已退出，退出码：' + $process.ExitCode + '；' + (Get-ServiceReason $probe)) }
        if ($probe.state -notin @('not_running', 'unreachable')) { throw ('工作台未能就绪：' + (Get-ServiceReason $probe)) }
    }
    throw ('45秒内未确认工作台就绪；' + (Get-ServiceReason $probe))
}
catch {
    [Console]::Error.WriteLine('工作台操作失败：' + $_.Exception.Message)
    if ($stdoutPath) { [Console]::Error.WriteLine('标准输出日志：' + $stdoutPath) }
    if ($stderrPath) { [Console]::Error.WriteLine('错误日志：' + $stderrPath) }
    exit 1
}
