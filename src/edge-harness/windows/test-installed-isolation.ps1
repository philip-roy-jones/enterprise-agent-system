param([string]$Root="$env:ProgramData\EnterpriseAgentSystem\Worker", [string]$TaskName='EAS-Planner', [string]$Component='planner')
$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName $TaskName
if ($task.State -eq 'Running') { throw 'Run this probe while the component is stopped and its assignments are drained' }
$folder=Join-Path $Root "$Component\runtime"
New-Item -ItemType Directory -Force $folder | Out-Null
$original=$task.Actions
$account=$task.Principal.UserId
$localName=$account.Split('\')[-1]
if ($localName -notin @('eas-planner','eas-learner')) { throw 'This probe may rotate only the installer-owned service accounts' }
$password=[Guid]::NewGuid().ToString('N')+'!aZ9'
Set-LocalUser $localName -Password (ConvertTo-SecureString $password -AsPlainText -Force)
$file=Join-Path $folder 'isolation-probe.ps1'
$result=Join-Path $folder 'isolation-result.json'
$target=Get-Process DemoBooks | Select-Object -First 1
if (-not $target -or -not (Test-Path "$Root\executor\.env") -or -not (Test-Path "$Root\code\run-component.py")) { throw 'Positive controls missing: require running application and installed executor configuration/code' }
$records=Join-Path $env:LOCALAPPDATA 'EnterpriseAgentSystem\DemoBooks\data\accounting-records.json'
$controller=Join-Path $env:LOCALAPPDATA 'EnterpriseAgentSystem\DesktopAgent\data\bridge.token'
if (-not (Test-Path $records) -or -not (Test-Path $controller)) { throw 'Application data and controller credential positive controls are missing' }
@{ executor_config="$Root\executor\.env"; source="$Root\code\run-component.py"; executor_root="$Root\executor"; target_pid=$target.Id; records=$records; controller=$controller } | ConvertTo-Json | Set-Content (Join-Path $folder 'probe-input.json') -Encoding UTF8
@'
$ErrorActionPreference='Stop'
try {
$config=Get-Content (Join-Path $PSScriptRoot 'probe-input.json') -Raw | ConvertFrom-Json
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class EASInstalledProbe {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint access, bool inherit, int process);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern IntPtr CreateFile(string name, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
}
"@
function Readable([string]$p) { try { $s=[IO.File]::OpenRead($p); $s.Dispose(); return $true } catch { return $false } }
function Writable([string]$p) { try { $s=[IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite); $s.Dispose(); return $true } catch { return $false } }
$handle=[EASInstalledProbe]::OpenProcess(0x10,$false,$config.target_pid)
$memory=$handle -ne [IntPtr]::Zero
if ($memory) { [EASInstalledProbe]::CloseHandle($handle) | Out-Null }
$aclHandle=[EASInstalledProbe]::CreateFile($config.source,0x40000,7,[IntPtr]::Zero,3,0,[IntPtr]::Zero)
$aclWritable=$aclHandle -ne [IntPtr](-1)
if ($aclWritable) { [EASInstalledProbe]::CloseHandle($aclHandle) | Out-Null }
$list=$false
try { [IO.Directory]::GetFileSystemEntries($config.executor_root) | Out-Null; $list=$true } catch { }
Add-Type -AssemblyName UIAutomationClient
$condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$config.target_pid)
$visible=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition).Count
$status=0
try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8766/observe' -Method Post -ContentType application/json -Body '{}' -TimeoutSec 3 | Out-Null; $status=200 }
catch { if ($_.Exception.Response) { $status=[int]$_.Exception.Response.StatusCode } }
[ordered]@{ identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name; session_id=(Get-Process -Id $PID).SessionId;
 executor_config_readable=(Readable $config.executor_config); execution_code_writable=(Writable $config.source);
 application_records_readable=(Readable $config.records); controller_token_readable=(Readable $config.controller); execution_code_acl_writable=$aclWritable;
 executor_directory_listable=$list; application_memory_readable=$memory;
 foreground_available=([EASInstalledProbe]::GetForegroundWindow() -ne [IntPtr]::Zero); application_automation_elements=$visible;
 unauthenticated_controller_status=$status; model_mode='none'; staff_mode='no business actions' } |
 ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'isolation-result.json') -Encoding UTF8
} catch { @{probe_error=$_.Exception.Message} | ConvertTo-Json | Set-Content (Join-Path $PSScriptRoot 'isolation-result.json') -Encoding UTF8 }
'@ | Set-Content $file -Encoding UTF8
try {
    Remove-Item $result -ErrorAction SilentlyContinue
    $action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$file`""
    Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $task.Settings -User $account -Password $password -RunLevel Limited -Force | Out-Null
    Start-ScheduledTask $TaskName
    $deadline=(Get-Date).AddSeconds(45)
    while (-not (Test-Path $result) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if (-not (Test-Path $result)) { throw 'Installed account probe produced no result' }
    Get-Content $result -Raw
} finally {
    Stop-ScheduledTask $TaskName -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $original -Settings $task.Settings -User $account -Password $password -RunLevel Limited -Force | Out-Null
    Remove-Item $file,(Join-Path $folder 'probe-input.json') -ErrorAction SilentlyContinue
}
