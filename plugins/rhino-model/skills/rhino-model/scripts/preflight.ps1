[CmdletBinding()]
param(
    [string]$RhinoExe = (Join-Path $env:ProgramFiles 'Rhino 8\System\Rhino.exe'),
    [string]$YakExe,
    [string]$ShortcutPath,
    [string]$PluginVersion = '0.3.2',
    [string]$PluginManifest,
    [string]$ServerExe = $env:RHINO_MCP_SERVER,
    [string]$ContractsDir = $env:RHINO_MCP_CONTRACTS,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'

if (-not $YakExe) { $YakExe = Join-Path (Split-Path $RhinoExe -Parent) 'Yak.exe' }
if (-not $PluginManifest) {
    $PluginManifest = Join-Path $env:APPDATA "McNeel\Rhinoceros\packages\8.0\rhinomcp\$PluginVersion\manifest.yml"
}
if (-not $ConfigPath) {
    $configRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
    $ConfigPath = Join-Path $configRoot 'config.toml'
}
$expectedDangerous = @(
    'run_command',
    'execute_rhinoscript_python_code',
    'execute_rhinocommon_csharp_code'
)

$issues = [System.Collections.Generic.List[string]]::new()
$liveIssues = [System.Collections.Generic.List[string]]::new()
$rhinoExists = Test-Path -LiteralPath $rhinoExe -PathType Leaf
$yakExists = Test-Path -LiteralPath $yakExe -PathType Leaf
$serverExists = $serverExe -and (Test-Path -LiteralPath $serverExe -PathType Leaf)
$contractsCount = if ($contractsDir -and (Test-Path -LiteralPath $contractsDir -PathType Container)) {
    @(Get-ChildItem -LiteralPath $contractsDir -Recurse -File).Count
} else {
    0
}

$rhinoVersion = $null
$signature = $null
if ($rhinoExists) {
    $rhinoItem = Get-Item -LiteralPath $rhinoExe
    $rhinoVersion = $rhinoItem.VersionInfo.ProductVersion
    $signature = (Get-AuthenticodeSignature -LiteralPath $rhinoExe).Status.ToString()
} else {
    $issues.Add("Rhino executable is missing: $rhinoExe")
}
if ($signature -ne 'Valid') {
    $issues.Add("Rhino signature is not valid: $signature")
}

$shortcutTarget = $null
if ($shortcutPath -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcutTarget = $shell.CreateShortcut($shortcutPath).TargetPath
    if ($shortcutTarget -ine $rhinoExe) {
        $issues.Add("Rhino shortcut target is unexpected: $shortcutTarget")
    }
} elseif ($shortcutPath) {
    $issues.Add("Rhino shortcut is missing: $shortcutPath")
}

$yakPackages = $null
if ($yakExists) {
    $yakPackages = ((& $yakExe list 2>&1) -join "`n").Trim()
    if ($yakPackages -notmatch ('rhinomcp\s+\(' + [regex]::Escape($PluginVersion) + '\)')) {
        $issues.Add("Yak does not report rhinomcp ($PluginVersion).")
    }
} else {
    $issues.Add("Yak executable is missing: $yakExe")
}

if (-not $serverExists) {
    $issues.Add("External RhinoMCP server is missing; pass -ServerExe or set RHINO_MCP_SERVER: $serverExe")
}
if ($contractsCount -lt 1) {
    $issues.Add("External RhinoMCP contract schemas are missing; pass -ContractsDir or set RHINO_MCP_CONTRACTS: $contractsDir")
}
if (-not (Test-Path -LiteralPath $pluginManifest -PathType Leaf)) {
    $issues.Add("RhinoMCP Rhino plugin manifest is missing: $pluginManifest")
}
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    $issues.Add("Codex config is missing: $configPath")
}

$approvalWrites = $false
if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    $configText = Get-Content -LiteralPath $configPath -Raw
    $rhinoSection = [regex]::Match(
        $configText,
        '(?ms)^\[mcp_servers\.rhino\]\s*(.*?)(?=^\[|\z)'
    )
    if ($rhinoSection.Success) {
        $approvalWrites = $rhinoSection.Groups[1].Value -match '(?m)^\s*default_tools_approval_mode\s*=\s*["'']writes["'']\s*$'
    }
}

$rhinoConfig = $null
try {
    $rawConfig = (& codex mcp get rhino --json 2>$null) -join "`n"
    if ($LASTEXITCODE -eq 0 -and $rawConfig) {
        $rhinoConfig = $rawConfig | ConvertFrom-Json
    } else {
        $issues.Add('Codex does not report an enabled rhino MCP.')
    }
} catch {
    $issues.Add("Could not inspect Codex rhino MCP: $($_.Exception.Message)")
}

$configSafe = $false
if ($null -ne $rhinoConfig) {
    $disabled = @($rhinoConfig.disabled_tools)
    $missingDisabled = @($expectedDangerous | Where-Object { $_ -notin $disabled })
    $envConfig = $rhinoConfig.transport.env
    $configSafe = (
        $rhinoConfig.enabled -eq $true -and
        $rhinoConfig.transport.command -ieq $serverExe -and
        @($rhinoConfig.transport.args).Count -eq 0 -and
        $envConfig.RHINO_MCP_HOST -eq '127.0.0.1' -and
        $envConfig.RHINO_MCP_PORT -eq '1999' -and
        $envConfig.RHINO_MCP_ALLOW_REMOTE -eq '0' -and
        $envConfig.RHINO_MCP_VALIDATE -eq 'strict' -and
        $envConfig.RHINO_MCP_ENABLE_RUN_COMMAND -eq '0' -and
        $envConfig.RHINO_MCP_ENABLE_RHINOSCRIPT -eq '0' -and
        $envConfig.RHINO_MCP_ENABLE_CSHARP -eq '0' -and
        $envConfig.RHINO_MCP_DEBUG -eq '0' -and
        $approvalWrites -and
        $missingDisabled.Count -eq 0
    )
    if (-not $configSafe) {
        $issues.Add('Codex rhino MCP configuration does not match the verified safety baseline.')
    }
}

$rhinoProcesses = @(Get-CimInstance Win32_Process -Filter "Name='Rhino.exe'" -ErrorAction SilentlyContinue)
$validRhinoProcesses = @($rhinoProcesses | Where-Object { $_.ExecutablePath -ieq $rhinoExe })
$listeners = @(Get-NetTCPConnection -LocalPort 1999 -State Listen -ErrorAction SilentlyContinue)
$unsafeListeners = @($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') })
$loopbackListeners = @($listeners | Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') })
$matchedListeners = @(
    $loopbackListeners | Where-Object {
        $_.OwningProcess -in @($validRhinoProcesses | ForEach-Object { $_.ProcessId })
    }
)
if ($unsafeListeners.Count -gt 0) {
    $liveIssues.Add('Port 1999 has a non-loopback listener; do not use RhinoMCP.')
}
if ($rhinoProcesses.Count -gt 1) {
    $liveIssues.Add('Multiple Rhino processes are running; select and verify one target before writing.')
}
if ($rhinoProcesses.Count -gt 0 -and $validRhinoProcesses.Count -ne $rhinoProcesses.Count) {
    $liveIssues.Add('A Rhino.exe process is not running from the verified executable path.')
}
if ($listeners.Count -gt 0 -and $matchedListeners.Count -ne 1) {
    $liveIssues.Add('Port 1999 is not owned by the unique verified Rhino process.')
}

$staticReady = (
    $rhinoExists -and
    $signature -eq 'Valid' -and
    $yakExists -and
    $serverExists -and
    $contractsCount -gt 0 -and
    $configSafe -and
    $issues.Count -eq 0
)
$liveReady = (
    $staticReady -and
    $rhinoProcesses.Count -eq 1 -and
    $validRhinoProcesses.Count -eq 1 -and
    $loopbackListeners.Count -eq 1 -and
    $matchedListeners.Count -eq 1 -and
    $unsafeListeners.Count -eq 0 -and
    $liveIssues.Count -eq 0
)

[ordered]@{
    schema_version = '1.0'
    checked_at = (Get-Date).ToString('o')
    static_ready = $staticReady
    live_ready = $liveReady
    rhino = [ordered]@{
        executable = $rhinoExe
        version = $rhinoVersion
        signature = $signature
        process_count = $rhinoProcesses.Count
        processes = @($rhinoProcesses | ForEach-Object {
            [ordered]@{
                pid = $_.ProcessId
                executable_path = $_.ExecutablePath
            }
        })
        shortcut = $shortcutPath
        shortcut_target = $shortcutTarget
    }
    mcp = [ordered]@{
        server = $serverExe
        yak_packages = $yakPackages
        contracts_count = $contractsCount
        config_safe = $configSafe
        approval_mode_writes = $approvalWrites
        loopback_listener_count = $loopbackListeners.Count
        unsafe_listener_count = $unsafeListeners.Count
        matched_rhino_listener_count = $matchedListeners.Count
        listener_owners = @($listeners | ForEach-Object {
            [ordered]@{
                address = $_.LocalAddress
                pid = $_.OwningProcess
            }
        })
    }
    static_issues = @($issues)
    live_issues = @($liveIssues)
    issues = @($issues) + @($liveIssues)
} | ConvertTo-Json -Depth 6
