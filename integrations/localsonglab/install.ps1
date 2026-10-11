param([Parameter(Mandatory=$true)][string]$SongLabRoot)
$ErrorActionPreference = 'Stop'
$labRoot = (Resolve-Path -LiteralPath $SongLabRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $labRoot 'app/server.py'))) {
    throw 'Choose the existing LocalSongLab root containing app/server.py.'
}
$null = Get-Command git -ErrorAction Stop
$patchNames = @('server.py.patch', 'launch.py.patch', 'test_server.py.patch')
$pending = @()
Push-Location -LiteralPath $labRoot
try {
    foreach ($patchName in $patchNames) {
        $patchPath = Join-Path $PSScriptRoot $patchName
        & git apply --check -- $patchPath 2>$null
        if ($LASTEXITCODE -eq 0) { $pending += $patchPath; continue }
        & git apply --reverse --check -- $patchPath 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Source conflicts with $patchName. No files have been changed." }
    }
    $sourceBackup = Join-Path $labRoot ('backups/resonance-source-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $null = New-Item -ItemType Directory -Path $sourceBackup
    foreach ($sourceName in @('server.py','launch.py','test_server.py')) {
        Copy-Item -LiteralPath (Join-Path $labRoot "app/$sourceName") -Destination $sourceBackup
    }
    foreach ($patchPath in $pending) {
        & git apply -- $patchPath
        if ($LASTEXITCODE -ne 0) { throw "Could not apply $patchPath; source backup: $sourceBackup" }
    }
    foreach ($sourceName in @('reaper_pipeline.py','test_reaper_pipeline.py','test_runtime_ownership.py')) {
        $target = Join-Path $labRoot "app/$sourceName"
        if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination $sourceBackup }
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $sourceName) -Destination $target
    }
    $configTarget = Join-Path $labRoot 'app/reaper_config.json'
    if (-not (Test-Path -LiteralPath $configTarget)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'reaper_config.json') -Destination $configTarget
    }
    Write-Output "Source installed. Backup: $sourceBackup. Restart the LocalSongLab bridge when idle."
} finally { Pop-Location }
