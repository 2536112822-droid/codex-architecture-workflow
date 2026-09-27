# This script never edits Codex settings or starts a design application.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SketchUp', 'AutoCAD', 'McpConfig')]
    [string]$Target,
    [string]$Destination,
    [string]$AutoCADDir,
    [string]$PythonExecutable,
    [string]$NodeExecutable,
    [string]$DotNetExecutable
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent

function Resolve-Executable([string]$Path, [string]$Name) {
    if (-not $Path) { throw "Pass an explicit -$Name executable path; no PATH or system configuration is changed." }
    if (-not [System.IO.Path]::IsPathRooted($Path)) { throw "$Name must be an absolute path." }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw "$Name is not a file." }
    if ($resolved -match '\\WindowsApps\\') { throw "$Name appears to be a Windows Store alias; select the installed interpreter." }
    return $resolved
}

if ($Target -eq 'McpConfig') {
    $nodePath = Resolve-Executable $NodeExecutable 'NodeExecutable'
    $pythonPath = Resolve-Executable $PythonExecutable 'PythonExecutable'
    # JSON strings are valid TOML basic strings and safely escape Windows paths.
    $nodeToml = ConvertTo-Json -InputObject $nodePath -Compress
    $pythonToml = ConvertTo-Json -InputObject $pythonPath -Compress
    $suToml = ConvertTo-Json -InputObject (Join-Path $repoRoot 'plugins\su-model\runtime\mcp\server.js') -Compress
    $cadToml = ConvertTo-Json -InputObject (Join-Path $repoRoot 'plugins\cad-tz-model\runtime\mcp\server.py') -Compress
    @"
# Merge only after checking for existing registrations. Keep this checkout in place.
[mcp_servers.su]
command = $nodeToml
args = [$suToml]

[mcp_servers.cad]
command = $pythonToml
args = [$cadToml]
"@
    return
}

if (-not $Destination -or -not [System.IO.Path]::IsPathRooted($Destination)) {
    throw 'Pass -Destination with an explicit absolute existing Plugins/ApplicationPlugins directory.'
}
$destinationRoot = (Resolve-Path -LiteralPath $Destination -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $destinationRoot -PathType Container)) { throw 'Destination must be a directory.' }

if ($Target -eq 'SketchUp') {
    $sourceRoot = Join-Path $repoRoot 'plugins\su-model\runtime\sketchup'
    $launcherPath = Join-Path $destinationRoot 'su_model_launcher.rb'
    $runtimePath = Join-Path $destinationRoot 'su_model_runtime'
    foreach ($path in @($launcherPath, $runtimePath)) {
        if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite existing content: $path. Back up and choose a clean destination." }
    }
    foreach ($file in @('su_model_launcher.rb', 'su_server.rb', 'su_selftest.rb')) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $file) -PathType Leaf)) { throw "Missing source file: $file" }
    }
    if (-not $PSCmdlet.ShouldProcess($destinationRoot, 'Install the SketchUp launcher and isolated Ruby payload')) { return }
    New-Item -ItemType Directory -Path $runtimePath | Out-Null
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'su_server.rb') -Destination $runtimePath
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'su_selftest.rb') -Destination $runtimePath
    # Install the loader last, so an interrupted copy cannot autoload an incomplete payload.
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'su_model_launcher.rb') -Destination $launcherPath
    [ordered]@{ target = $Target; launcher = $launcherPath; runtime = $runtimePath; next = 'Restart SketchUp when its current work is saved, then verify su_ping and the active model.' } | ConvertTo-Json
    return
}

if (-not $AutoCADDir) { throw 'Pass -AutoCADDir with your installed AutoCAD 2025 directory containing acmgd.dll, acdbmgd.dll and accoremgd.dll.' }
$acadRoot = (Resolve-Path -LiteralPath $AutoCADDir -ErrorAction Stop).Path
foreach ($assembly in @('acmgd.dll', 'acdbmgd.dll', 'accoremgd.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $acadRoot $assembly) -PathType Leaf)) { throw "Missing AutoCAD reference: $assembly" }
}
$bundlePath = Join-Path $destinationRoot 'TzServer.bundle'
if (Test-Path -LiteralPath $bundlePath) { throw "Refusing to overwrite existing content: $bundlePath. Back it up and choose a clean destination." }
$dotnetPath = if ($DotNetExecutable) { Resolve-Executable $DotNetExecutable 'DotNetExecutable' } else { (Get-Command dotnet -ErrorAction Stop).Source }
$installedSdks = @(& $dotnetPath --list-sdks)
if (-not ($installedSdks -match '^(8|9|[1-9][0-9])\.')) { throw 'A .NET SDK 8 or newer is required. A .NET runtime alone cannot build this source release; supply -DotNetExecutable for a portable SDK.' }
if (-not $PSCmdlet.ShouldProcess($destinationRoot, 'Build against the installed AutoCAD SDK and install TzServer.bundle')) { return }
$sourceRoot = Join-Path $repoRoot 'plugins\cad-tz-model\runtime\autocad'
$buildRoot = Join-Path $repoRoot ('work\bridge-build-' + [guid]::NewGuid().ToString('N'))
$buildOutput = Join-Path $buildRoot 'output'
$intermediate = (Join-Path $buildRoot 'obj') + [System.IO.Path]::DirectorySeparatorChar
& $dotnetPath build (Join-Path $sourceRoot 'TzServer.csproj') -c Release -o $buildOutput "-p:AutoCADDir=$acadRoot" "-p:BaseIntermediateOutputPath=$intermediate"
if ($LASTEXITCODE -ne 0) { throw "AutoCAD bridge build failed. Diagnostic files remain in $buildRoot" }
$builtDll = Join-Path $buildOutput 'TzServer.dll'
if (-not (Test-Path -LiteralPath $builtDll -PathType Leaf)) { throw 'Build did not produce TzServer.dll.' }
$windowsPayload = Join-Path $bundlePath 'Contents\Windows'
New-Item -ItemType Directory -Path $windowsPayload | Out-Null
foreach ($file in @('TzServer.dll', 'TzServer.deps.json', 'TzServer.runtimeconfig.json')) {
    $builtFile = Join-Path $buildOutput $file
    if (Test-Path -LiteralPath $builtFile -PathType Leaf) { Copy-Item -LiteralPath $builtFile -Destination $windowsPayload }
}
# The manifest is copied last; proprietary Autodesk reference assemblies are not copied.
Copy-Item -LiteralPath (Join-Path $sourceRoot 'TzServer.bundle\PackageContents.xml') -Destination $bundlePath
[ordered]@{ target = $Target; bundle = $bundlePath; build_files = $buildRoot; next = 'Load the bundle in AutoCAD according to its trusted plugin settings; verify cad_discover and cad_state.' } | ConvertTo-Json
