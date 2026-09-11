param(
    [string]$Source = "$PSScriptRoot\publish",
    [string]$InstallDirectory = "$env:LOCALAPPDATA\EnterpriseAgentSystem\DemoBooks",
    [string]$DesktopUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [switch]$DisableApi
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path "$Source\DemoBooks.exe")) { throw 'Publish DemoBooks first, or extract the Windows package next to this script.' }
New-Item -ItemType Directory -Force $InstallDirectory | Out-Null
# Accounting records live in data/, outside the replaceable application directory.
$applicationDirectory = Join-Path $InstallDirectory 'app'
New-Item -ItemType Directory -Force $applicationDirectory | Out-Null
Copy-Item "$Source\*" $applicationDirectory -Recurse -Force

# Restrict the native bridge to loopback and this Windows identity.
$existing = netsh http show urlacl url=http://127.0.0.1:8765/ 2>$null
if ($LASTEXITCODE -ne 0 -or -not ($existing -match 'http://127.0.0.1:8765/')) {
    netsh http add urlacl url=http://127.0.0.1:8765/ "user=$DesktopUser" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not reserve the local bridge URL. Run the installer as Administrator.' }
}
$executable = Join-Path $applicationDirectory 'DemoBooks.exe'
$launch = @{ Execute = $executable; WorkingDirectory = $applicationDirectory }
if ($DisableApi) { $launch.Argument = '--no-api' }
$action = New-ScheduledTaskAction @launch
$principal = New-ScheduledTaskPrincipal -UserId $DesktopUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# This task has NO schedule or trigger. It launches in the existing interactive session on demand.
Register-ScheduledTask -TaskName 'EAS-DemoBooks' -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'EAS-DemoBooks'

$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:USERPROFILE\Desktop\DemoBooks Desktop.lnk")
$shortcut.TargetPath = $executable
$shortcut.WorkingDirectory = $applicationDirectory
$shortcut.Description = 'Enterprise Agent System synthetic Windows accounting application'
$shortcut.Save()
Write-Output "Installed: $executable"
Write-Output "Launch task: EAS-DemoBooks (manual only; no recurring schedule)"
if ($DisableApi) { Write-Output 'Application API disabled; use the independent desktop controller.' }
else { Write-Output "Bridge: http://127.0.0.1:8765/ through an SSH tunnel" }
Write-Output "Token file: $InstallDirectory\data\bridge.token (keep private)"
Write-Output 'A logged-in, unlocked Windows desktop session is required.'
