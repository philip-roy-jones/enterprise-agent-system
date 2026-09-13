param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$PythonHome,
    [Parameter(Mandatory=$true)][string]$PlannerConfig,
    [Parameter(Mandatory=$true)][string]$ExecutorConfig,
    [string]$Root = "$env:ProgramData\EnterpriseAgentSystem\Worker",
    [string]$PlannerUser = 'eas-planner',
    [string]$LearnerUser = 'eas-learner',
    [string]$DesktopUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'account-rights.ps1')
foreach ($task in @('EAS-Worker', 'EAS-Planner', 'EAS-Executor', 'EAS-Learner')) {
    $existing = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if ($existing -and $existing.State -eq 'Running') { throw "Drain and stop $task before installation" }
}
if (-not (Test-Path "$PythonHome\python.exe")) { throw 'Provide a complete trusted Python installation directory' }
if (-not (Test-Path $PlannerConfig) -or -not (Test-Path $ExecutorConfig)) { throw 'Separate provisioned service configurations are required' }
$plannerAllowed = @('EAS_BACKEND_URL','EAS_WORKER_TOKEN','EAS_WORKER_ORGANIZATION_ID','EAS_WORKER_ROLE_IDS','EAS_WORKFLOW_MODULES','EAS_ROLE_MODULES','EAS_DATA_DIR','EAS_LEARNING_ENABLED','EAS_EXECUTOR_URL','EAS_MODEL_MODE','EAS_MODEL_PROVIDER','EAS_MODEL_ID','EAS_MAX_MODEL_CALLS','EAS_CONTEXT_MAX_CHARS','EAS_SECURITY_PROFILE','OPENROUTER_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','SSL_CERT_FILE')
foreach ($line in Get-Content $PlannerConfig) {
    if ($line -match '^\s*([A-Z][A-Z0-9_]+)\s*=' -and $Matches[1] -notin $plannerAllowed) { throw 'Planner configuration contains an unapproved variable; separate application and admission credentials first' }
}
$desktopSid = (New-Object Security.Principal.NTAccount($DesktopUser)).Translate([Security.Principal.SecurityIdentifier]).Value
$password = [Guid]::NewGuid().ToString('N') + '!aZ9'
if (Get-LocalUser $PlannerUser -ErrorAction SilentlyContinue) {
    Set-LocalUser $PlannerUser -Password (ConvertTo-SecureString $password -AsPlainText -Force)
} else {
    New-LocalUser $PlannerUser -Password (ConvertTo-SecureString $password -AsPlainText -Force) -Description 'Enterprise Agent System isolated planner' | Out-Null
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $PlannerUser
}
$plannerSid = (Get-LocalUser $PlannerUser).SID.Value
if (Get-LocalGroupMember -SID 'S-1-5-32-544' | Where-Object SID -eq $plannerSid) { throw 'Planner must not be an administrator' }
Set-EasAccountRight $plannerSid 'SeBatchLogonRight'
Set-EasAccountRight $plannerSid 'SeDenyInteractiveLogonRight'
Set-EasAccountRight $plannerSid 'SeDenyRemoteInteractiveLogonRight'
$learnerPassword = [Guid]::NewGuid().ToString('N') + '!aZ9'
if (Get-LocalUser $LearnerUser -ErrorAction SilentlyContinue) {
    Set-LocalUser $LearnerUser -Password (ConvertTo-SecureString $learnerPassword -AsPlainText -Force)
} else {
    New-LocalUser $LearnerUser -Password (ConvertTo-SecureString $learnerPassword -AsPlainText -Force) -Description 'Enterprise Agent System isolated learner' | Out-Null
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $LearnerUser
}
$learnerSid = (Get-LocalUser $LearnerUser).SID.Value
if ($learnerSid -eq $plannerSid -or (Get-LocalGroupMember -SID 'S-1-5-32-544' | Where-Object SID -eq $learnerSid)) { throw 'Learner requires a distinct non-admin account' }
Set-EasAccountRight $learnerSid 'SeBatchLogonRight'
Set-EasAccountRight $learnerSid 'SeDenyInteractiveLogonRight'
Set-EasAccountRight $learnerSid 'SeDenyRemoteInteractiveLogonRight'
New-Item -ItemType Directory -Force $Root | Out-Null
icacls.exe $Root /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' "*$($desktopSid):RX" "*$($plannerSid):RX" "*$($learnerSid):RX" | Out-Null
if ($LASTEXITCODE) { throw 'Root ACL configuration failed' }
foreach ($folder in @('code','code\shared','code\edge-harness','python','planner','planner\runtime','executor','executor\runtime','learner','learner\runtime','ipc','ipc\requests','ipc\responses')) { New-Item -ItemType Directory -Force (Join-Path $Root $folder) | Out-Null }
# Copy the interpreter out of the interactive user's profile. Planner can read
# this immutable installation but cannot change code executed by the executor.
Copy-Item "$PythonHome\*" "$Root\python" -Recurse -Force
Copy-Item "$Source\src\shared\*" "$Root\code\shared" -Recurse -Force
Copy-Item "$Source\src\edge-harness\*" "$Root\code\edge-harness" -Recurse -Force
Copy-Item "$Source\requirements.lock" "$Root\code\requirements.lock" -Force
Copy-Item "$PSScriptRoot\run-component.py" "$Root\code\run-component.py" -Force
$python = "$Root\python\python.exe"
& $python -m venv "$Root\venv"
if ($LASTEXITCODE) { throw 'Environment creation failed' }
& "$Root\venv\Scripts\python.exe" -m pip install -c "$Root\code\requirements.lock" "$Root\code\shared" "$Root\code\edge-harness"
if ($LASTEXITCODE) { throw 'Package installation failed' }
foreach ($folder in @('code','python','venv')) {
    icacls.exe (Join-Path $Root $folder) /grant:r "*$($plannerSid):(OI)(CI)RX" "*$($learnerSid):(OI)(CI)RX" "*$($desktopSid):(OI)(CI)RX" /T | Out-Null
    if ($LASTEXITCODE) { throw 'Immutable runtime ACL configuration failed' }
}
icacls.exe "$Root\planner" /grant:r "*$($plannerSid):(OI)(CI)RX" /T | Out-Null
icacls.exe "$Root\learner" /grant:r "*$($learnerSid):(OI)(CI)RX" /T | Out-Null
icacls.exe "$Root\executor" /grant:r "*$($desktopSid):(OI)(CI)RX" /T | Out-Null
icacls.exe "$Root\planner\runtime" /grant:r "*$($plannerSid):(OI)(CI)M" /T | Out-Null
icacls.exe "$Root\learner\runtime" /grant:r "*$($learnerSid):(OI)(CI)M" /T | Out-Null
icacls.exe "$Root\executor\runtime" /grant:r "*$($desktopSid):(OI)(CI)M" /T | Out-Null
# The learner may read requests and create response files. It cannot replace
# IPC directories or make executor writes traverse a learner-controlled path.
icacls.exe "$Root\ipc" /grant:r "*$($learnerSid):RX" "*$($desktopSid):RX" | Out-Null
icacls.exe "$Root\ipc\requests" /grant:r "*$($learnerSid):(OI)(CI)RX" "*$($desktopSid):(OI)(CI)M" | Out-Null
icacls.exe "$Root\ipc\responses" /grant:r "*$($learnerSid):(RX,W)" "*$($learnerSid):(OI)(IO)M" "*$($desktopSid):(OI)(CI)M" | Out-Null
Copy-Item $PlannerConfig "$Root\planner\.env" -Force
Copy-Item $ExecutorConfig "$Root\executor\.env" -Force
# Executor state and secrets inherit no planner permission. Configuration paths
# are fixed at install time; source .env and interactive application credentials
# never enter the planner environment.
$plannerState = "$Root\planner\runtime"
$executorState = "$Root\executor\runtime"
Add-Content "$Root\planner\.env" "`nEAS_DATA_DIR='$plannerState'`nEAS_LEARNING_ENABLED=false" -Encoding UTF8
Add-Content "$Root\executor\.env" "`nEAS_DATA_DIR='$executorState'" -Encoding UTF8
Add-Content "$Root\executor\.env" "EAS_LEARNER_QUEUE='$Root\ipc'" -Encoding UTF8
$learnerConfig = @("EAS_DATA_DIR='$Root\learner\runtime'", "EAS_LEARNER_QUEUE='$Root\ipc'")
$learnerConfig += Get-Content $ExecutorConfig | Where-Object { $_ -match '^(OPENROUTER_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|SSL_CERT_FILE)=' }
$learnerConfig | Set-Content "$Root\learner\.env" -Encoding UTF8
# Read-only ACLs alone are insufficient when a service account owns the files:
# an owner can rewrite its DACL. SYSTEM owns the deployment and configuration.
icacls.exe $Root /setowner '*S-1-5-18' /T | Out-Null
if ($LASTEXITCODE) { throw 'Protected deployment ownership could not be established' }
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(1))
foreach ($component in @('planner','executor','learner')) {
    $name = 'EAS-' + (Get-Culture).TextInfo.ToTitleCase($component)
    $action = New-ScheduledTaskAction -Execute "$Root\venv\Scripts\pythonw.exe" -Argument "`"$Root\code\run-component.py`" $component --env `"$Root\$component\.env`"" -WorkingDirectory "$Root\$component"
    if ($component -eq 'planner') {
        Register-ScheduledTask -TaskName $name -Action $action -Settings $settings -User "$env:COMPUTERNAME\$PlannerUser" -Password $password -RunLevel Limited -Force | Out-Null
    } elseif ($component -eq 'learner') {
        Register-ScheduledTask -TaskName $name -Action $action -Settings $settings -User "$env:COMPUTERNAME\$LearnerUser" -Password $learnerPassword -RunLevel Limited -Force | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId $DesktopUser -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $name -Action $action -Settings $settings -Principal $principal -Force | Out-Null
    }
}
$password = $null
$learnerPassword = $null
Write-Output 'Isolated worker installed. Start EAS-Executor, then EAS-Planner after validating identities and transport.'
