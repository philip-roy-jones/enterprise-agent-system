param([string]$Source = (Resolve-Path "$PSScriptRoot\..\..\.."))
$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path $Source).Path
# Stop only after current jobs finish; check the staff console first.
$launcher = ([regex]::Escape("$Source\src\edge-harness\windows\run-worker.py") + "|" + [regex]::Escape("$Source\src\enterprise\harness\windows\run-worker.py") + "|" + [regex]::Escape("$Source\windows\run-worker.py"))
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -match $launcher
})
Stop-ScheduledTask -TaskName 'EAS-Worker' -ErrorAction SilentlyContinue
foreach ($workerProcess in $processes) {
    if (Get-Process -Id $workerProcess.ProcessId -ErrorAction SilentlyContinue) {
        # Another parent in the list may already have terminated this child.
        & $env:ComSpec /d /c "taskkill /PID $($workerProcess.ProcessId) /T /F >nul 2>&1"
    }
}
if (Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe', 'pythonw.exe') -and $_.CommandLine -match $launcher
}) { throw 'The worker process did not stop.' }
Write-Output 'Windows worker stopped.'
