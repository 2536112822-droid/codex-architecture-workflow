[CmdletBinding()]
param(
    [string]$PythonExecutable,
    [string]$TianzhengLauncher = $env:CAD_TARCH_LAUNCHER,
    [switch]$NoPause
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$pluginRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$checkScript = Join-Path $pluginRoot 'runtime\mcp\launcher_check.py'
$pythonArgs = @()
if (-not $PythonExecutable) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notmatch '\\WindowsApps\\') {
        $PythonExecutable = $pythonCommand.Source
    } else {
        $pyCommand = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCommand) { $PythonExecutable = $pyCommand.Source; $pythonArgs = @('-3') }
    }
}
if (-not $PythonExecutable) { throw 'Pass -PythonExecutable with a real Python 3.10+ executable (not the Windows Store alias).' }
Write-Host 'CAD + Tianzheng structured drafting bridge'
$acad = Get-Process -Name acad -ErrorAction SilentlyContinue
if (-not $acad) {
    if ($TianzhengLauncher -and (Test-Path -LiteralPath $TianzhengLauncher -PathType Leaf)) {
        # The desktop application must be visible to select and verify its document.
        Start-Process -FilePath $TianzhengLauncher -WorkingDirectory (Split-Path $TianzhengLauncher -Parent) -WindowStyle Normal
    } else {
        Write-Host 'Open AutoCAD / Tianzheng, or pass -TianzhengLauncher with its installed executable.'
    }
}
$env:CAD_TZ_CONNECT_WAIT = '90'
& $PythonExecutable @pythonArgs $checkScript
$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) { Write-Host 'Bridge ready. Verify the active drawing before writing.' }
else { Write-Host 'Bridge not ready. Check installation, loading state, and the selected AutoCAD instance.' }
if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
exit $exitCode