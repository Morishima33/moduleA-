param([int]$Port = 8765, [switch]$NoBrowser, [switch]$CheckOnly, [string]$PythonPath = '') # 可指定端口、浏览器开关和已有 Python。
$ErrorActionPreference = 'Stop' # 启动失败时停止，明确报告原因。
$projectRoot = Split-Path -Parent $PSScriptRoot # 从脚本位置确定根目录，不绑定盘符。
$candidates = @() # 按顺序检查可用解释器，不自动安装软件。
if ($PythonPath) { $candidates = @($PythonPath) } # 用户明确指定时只检查该解释器。
else { # 未指定时检查本机已有环境。
    if ($env:MODULEA_PYTHON) { $candidates += $env:MODULEA_PYTHON } # 允许环境变量指定已准备的运行环境。
    $candidates += (Join-Path $env:USERPROFILE 'scoop\apps\python\current\python.exe') # 检查本机常见的独立 Python 安装。
    $command = Get-Command python -ErrorAction SilentlyContinue # 检查系统 PATH 中的 Python。
    if ($command) { $candidates += $command.Source } # 仅将确实找到的命令加入列表。
} # 结束本机候选收集。
$runtime = $null # 尚未找到合格环境。
foreach ($candidate in $candidates) { # 逐个验证，避免误用系统旧 Python。
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { # 文件必须真实存在。
        & $candidate -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' # 检查最低支持版本。
        if ($LASTEXITCODE -eq 0) { $runtime = $candidate; break } # 只选择通过版本检查的环境。
    } # 不存在的候选不执行。
} # 完成环境检查。
if (-not $runtime) { throw '未找到 Python 3.11 或更新版本；请配置 MODULEA_PYTHON 或传入 PythonPath，不会自动安装。' } # 缺环境时明确停止。
$env:PYTHONDONTWRITEBYTECODE = '1' # 不在源码目录产生字节缓存。
$env:PYTHONIOENCODING = 'utf-8' # 让 Python 提示以 UTF-8 输出中文。
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false) # 统一控制台文字编码。
$arguments = @((Join-Path $projectRoot 'src\main.py'), '--port', $Port) # 统一通过 main.py 启动。
if ($NoBrowser) { $arguments += '--no-browser' } # 维护检查时可不弹出浏览器。
Write-Host ('使用 Python：' + $runtime) # 让实际运行环境可见。
if ($CheckOnly) { $arguments += @('--check', '--no-browser') } # 维护时只检查启动条件。
& $runtime @arguments # 启动工作台，用户可按 Ctrl+C 停止。

