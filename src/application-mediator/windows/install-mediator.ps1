param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$Configuration,
    [string]$Root = "$env:ProgramData\EnterpriseAgentSystem\ApplicationMediator",
    [string]$DesktopUser = ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
)
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask EAS-ApplicationMediator -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') { throw 'Drain the worker and stop EAS-ApplicationMediator before installation' }
if (-not (Test-Path "$Source\src\application-mediator\pyproject.toml")) { throw 'Source must be the repository root' }
$sid = (New-Object Security.Principal.NTAccount($DesktopUser)).Translate([Security.Principal.SecurityIdentifier]).Value
New-Item -ItemType Directory -Force $Root | Out-Null
# Only the trusted desktop operator and machine administrators may read local
# controller credentials. Planner/learner accounts get no mediator files.
icacls.exe $Root /inheritance:r /grant:r "*${sid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE) { throw 'Could not protect mediator directory' }
& $Python -m venv "$Root\venv"
if ($LASTEXITCODE) { throw 'Could not create mediator environment' }
& "$Root\venv\Scripts\python.exe" -m pip install -c "$Source\requirements.lock" "$Source\src\shared" "$Source\src\application-mediator"
if ($LASTEXITCODE) { throw 'Could not install mediator packages' }
Copy-Item $Configuration "$Root\mediator.env" -Force
Copy-Item "$Source\src\application-mediator\windows\run-mediator.py" "$Root\run-mediator.py" -Force
$tokenFile = "$env:LOCALAPPDATA\EnterpriseAgentSystem\DesktopAgent\data\bridge.token"
if (-not (Test-Path $tokenFile)) { throw 'Install the native desktop controller first under the designated desktop user' }
$lines = @(Get-Content "$Root\mediator.env" | Where-Object { $_ -notmatch '^EAS_NATIVE_TOKEN=' })
$lines += 'EAS_NATIVE_TOKEN=' + (Get-Content $tokenFile -Raw).Trim()
[IO.File]::WriteAllLines("$Root\mediator.env", $lines, (New-Object Text.UTF8Encoding($false)))
$action = New-ScheduledTaskAction -Execute "$Root\venv\Scripts\pythonw.exe" -Argument ('"' + "$Root\run-mediator.py" + '"') -WorkingDirectory $Root
$principal = New-ScheduledTaskPrincipal -UserId $DesktopUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $DesktopUser
Register-ScheduledTask EAS-ApplicationMediator -Action $action -Principal $principal -Settings $settings -Trigger $trigger -Force | Out-Null
Write-Output 'Application Mediator installed. Assign office policy and executor mediator settings, then start EAS-ApplicationMediator.'
