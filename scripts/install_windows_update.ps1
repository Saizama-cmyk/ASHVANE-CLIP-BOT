param([Parameter(Mandatory=$true)][string]$StagedPackage)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$taskWorkspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskInstalled = Join-Path $taskWorkspace 'artifacts\windows-revamp\Ashvane'
$taskStaged = (Resolve-Path -LiteralPath $StagedPackage).Path
foreach ($taskPath in @($taskInstalled,$taskStaged)) {
    if (-not $taskPath.StartsWith($taskWorkspace + '\') -or $taskPath -eq $taskWorkspace) { throw 'Package path escapes workspace' }
}
if ($taskStaged -eq $taskInstalled) { throw 'Staged package must be separate' }
$taskExe = Join-Path $taskInstalled 'Ashvane.exe'
$taskExpected = (Get-FileHash -LiteralPath (Join-Path $taskStaged 'Ashvane.exe') -Algorithm SHA256).Hash
$taskOwned = @(Get-CimInstance Win32_Process -Filter "Name = 'Ashvane.exe'" | Where-Object { $_.ExecutablePath -eq $taskExe })
$taskHubs = @($taskOwned | Where-Object { $_.CommandLine -notmatch '--streamlink' })
if ($taskHubs.Count -gt 1) { throw 'Multiple hubs found; installation refused' }
foreach ($taskHub in $taskHubs) { & taskkill.exe /PID $taskHub.ProcessId /T /F 2>&1 | Out-Null }
Start-Sleep -Seconds 2
$taskRemaining = @(Get-CimInstance Win32_Process -Filter "Name = 'Ashvane.exe'" | Where-Object { $_.ExecutablePath -eq $taskExe })
foreach ($taskChild in $taskRemaining) {
    if ($taskChild.CommandLine -notmatch '--streamlink') { throw 'A hub appeared during maintenance' }
    & taskkill.exe /PID $taskChild.ProcessId /T /F 2>&1 | Out-Null
}
Start-Sleep -Seconds 1
if (Get-CimInstance Win32_Process -Filter "Name = 'Ashvane.exe'" | Where-Object { $_.ExecutablePath -eq $taskExe }) { throw 'Owned app processes have not drained' }
$taskBackup = Join-Path $taskWorkspace ('artifacts\install-backups\' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmssffff'))
New-Item -ItemType Directory -Path $taskBackup -Force | Out-Null
Copy-Item -LiteralPath $taskExe -Destination (Join-Path $taskBackup 'Ashvane.exe')
Copy-Item -LiteralPath (Join-Path $taskInstalled '_internal\base_library.zip') -Destination (Join-Path $taskBackup 'base_library.zip')
Copy-Item -LiteralPath (Join-Path $taskInstalled '_internal\clipbot\dashboard\static') -Destination (Join-Path $taskBackup 'static') -Recurse
# No folder renames/deletes: a dependency may retain the old directory as its cwd.
& robocopy.exe $taskStaged $taskInstalled /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP /NJH /NJS
if ($LASTEXITCODE -ge 8) { throw 'Package copy failed; saved app code remains in the backup' }
if ((Get-FileHash -LiteralPath $taskExe -Algorithm SHA256).Hash -ne $taskExpected) { throw 'Installed executable differs from tested package' }
$taskStatic = Join-Path $taskStaged '_internal\clipbot\dashboard\static'
foreach ($taskAsset in @(Get-ChildItem -LiteralPath $taskStatic -Recurse -File)) {
    $taskRelative = $taskAsset.FullName.Substring($taskStaged.Length + 1)
    $taskDestination = Join-Path $taskInstalled $taskRelative
    if ((Get-FileHash -LiteralPath $taskAsset.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $taskDestination -Algorithm SHA256).Hash) { throw "Installed asset differs: $taskRelative" }
}
$taskProcess = Start-Process -FilePath $taskExe -ArgumentList '--window' -WorkingDirectory $taskInstalled -WindowStyle Normal -PassThru
$taskReport = @{ pid=$taskProcess.Id; exe_sha256=$taskExpected; backup=$taskBackup; staged=$taskStaged; installed=$taskInstalled }
$taskReport | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskWorkspace 'artifacts\last-windows-install.json') -Encoding utf8
$taskReport | ConvertTo-Json
