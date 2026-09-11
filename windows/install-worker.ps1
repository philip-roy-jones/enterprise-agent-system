param(
    [string]$Source = (Split-Path $PSScriptRoot -Parent),
    [string]$Python = 'python',
    [string]$DesktopUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
)
$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path $Source).Path
if (-not (Test-Path "$Source\.env")) { throw 'Configure the Windows worker .env before installing. See docs/developer-setup.md.' }
$existing = Get-ScheduledTask -TaskName 'EAS-Worker' -ErrorAction SilentlyContinue
if ($existing -and $existing.State -eq 'Running') { throw 'Stop the idle EAS-Worker task before updating its environment.' }
$launcherPattern = [regex]::Escape("$Source\windows\run-worker.py")
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match $launcherPattern }) {
    throw 'A worker process still exists. Stop the idle worker with windows/stop-worker.ps1 first.'
}
& $Python -m venv "$Source\.venv"
if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
$workerPython = "$Source\.venv\Scripts\python.exe"
& $workerPython -m pip install -r "$Source\requirements.lock"
if ($LASTEXITCODE -ne 0) { throw 'Worker dependency installation failed.' }
& $workerPython -m pip install --no-deps -e $Source
if ($LASTEXITCODE -ne 0) { throw 'Worker package installation failed.' }
New-Item -ItemType Directory -Force "$Source\runtime" | Out-Null
$launcher = "$Source\windows\run-worker.py"
$action = New-ScheduledTaskAction -Execute "$Source\.venv\Scripts\pythonw.exe" -Argument "`"$launcher`"" -WorkingDirectory $Source
$principal = New-ScheduledTaskPrincipal -UserId $DesktopUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'EAS-Worker' -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Write-Output 'Windows worker installed. Once the backend is available, run: Start-ScheduledTask EAS-Worker'
Write-Output "Worker log: $Source\runtime\worker.log"
