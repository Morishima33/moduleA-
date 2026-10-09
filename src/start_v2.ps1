# 启动新版工作台（Windows）。查找 Python 的顺序与原 start.ps1 相同；不自动安装任何软件。
param([int]$Port = 8780, [switch]$NoBrowser, [switch]$CheckOnly, [string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$candidates = @()
if ($PythonPath) { $candidates = @($PythonPath) }
else {
    if ($env:MODULEA_PYTHON) { $candidates += $env:MODULEA_PYTHON }
    $candidates += (Join-Path $env:USERPROFILE 'scoop\apps\python\current\python.exe')
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
}
$runtime = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        & $candidate -B -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
        if ($LASTEXITCODE -eq 0) { $runtime = $candidate; break }
    }
}
if (-not $runtime) { throw '未找到 Python 3.11 或更新版本；请配置 MODULEA_PYTHON 或传入 PythonPath。' }
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$arguments = @('-m', 'modulea', 'serve', '--port', $Port)
if ($NoBrowser -or $CheckOnly) { $arguments += '--no-browser' }
if ($CheckOnly) { $arguments += '--check' }
Write-Host ('使用 Python：' + $runtime)
Set-Location $projectRoot
& $runtime @arguments
