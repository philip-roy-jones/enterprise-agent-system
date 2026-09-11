param(
    [string]$Source = "$PSScriptRoot\desktop-publish",
    [string]$TargetProcess = 'DemoBooks',
    [string]$DesktopUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
)
$ErrorActionPreference = 'Stop'
$installRoot = "$env:LOCALAPPDATA\EnterpriseAgentSystem\DesktopAgent"
if (-not (Test-Path "$Source\DesktopAgent.exe")) { throw 'Publish or extract DesktopAgent first.' }
Get-Process DesktopAgent -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Force "$installRoot\app" | Out-Null
Copy-Item "$Source\*" "$installRoot\app" -Recurse -Force
$existing = netsh http show urlacl url=http://127.0.0.1:8766/ 2>$null
if ($LASTEXITCODE -ne 0 -or -not ($existing -match 'http://127.0.0.1:8766/')) {
    netsh http add urlacl url=http://127.0.0.1:8766/ "user=$DesktopUser" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not reserve the desktop controller URL.' }
}
$action = New-ScheduledTaskAction -Execute "$installRoot\app\DesktopAgent.exe" -Argument $TargetProcess -WorkingDirectory "$installRoot\app"
$principal = New-ScheduledTaskPrincipal -UserId $DesktopUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'EAS-DesktopAgent' -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'EAS-DesktopAgent'
Write-Output "Desktop controller installed for process $TargetProcess (manual launch only)."
Write-Output "Private token file: $installRoot\data\bridge.token"
