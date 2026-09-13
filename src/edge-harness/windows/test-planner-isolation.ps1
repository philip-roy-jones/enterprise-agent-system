param(
    [Parameter(Mandatory=$true)][string]$ControllerToken,
    [Parameter(Mandatory=$true)][string]$ProtectedSource,
    [string]$TargetProcess = 'DemoBooks',
    [string]$ControllerUrl = 'http://127.0.0.1:8766',
    [string]$Output = "$env:ProgramData\EnterpriseAgentSystem\isolation-result.json"
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'account-rights.ps1')
$probeName = 'eas-probe-' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$taskName = 'EAS-Isolation-' + $probeName
$root = Join-Path $env:ProgramData "EnterpriseAgentSystem\$probeName"
$created = $false
try {
    $password = [Guid]::NewGuid().ToString('N') + '!aZ9'
    New-LocalUser -Name $probeName -Password (ConvertTo-SecureString $password -AsPlainText -Force) -Description 'Temporary EAS isolation validation' | Out-Null
    $created = $true
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $probeName
    New-Item -ItemType Directory -Force $root | Out-Null
    $sid = (Get-LocalUser $probeName).SID.Value
    Set-EasAccountRight $sid 'SeBatchLogonRight'
    icacls.exe $root /inheritance:r /grant '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' "*$($sid):(OI)(CI)M" | Out-Null
    $target = Get-Process -Name $TargetProcess | Select-Object -First 1
    if (-not $target) { throw 'Target application must be running to validate isolation' }
    @{ controller_token=$ControllerToken; protected_source=$ProtectedSource; target_pid=$target.Id; controller_url=$ControllerUrl } |
        ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $root 'input.json')
    $script = @'
$ErrorActionPreference = 'Stop'
try {
$config = Get-Content (Join-Path $PSScriptRoot 'input.json') -Raw | ConvertFrom-Json
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class EASProbe {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int process);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
"@
function CanRead([string]$path) {
    try { $s = [IO.File]::OpenRead($path); $s.Dispose(); return $true } catch { return $false }
}
function CanWrite([string]$path) {
    try { $s = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite); $s.Dispose(); return $true } catch { return $false }
}
$handle = [EASProbe]::OpenProcess(0x10, $false, $config.target_pid)
$memory = $handle -ne [IntPtr]::Zero
if ($memory) { [EASProbe]::CloseHandle($handle) | Out-Null }
$bridge = $false
try { Invoke-WebRequest -UseBasicParsing -Uri ($config.controller_url + '/observe') -Method Post -ContentType application/json -Body '{}' -TimeoutSec 3 | Out-Null; $bridge = $true } catch { }
$result = [ordered]@{
    identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    session_id = (Get-Process -Id $PID).SessionId
    controller_token_readable = (CanRead $config.controller_token)
    protected_source_writable = (CanWrite $config.protected_source)
    target_memory_readable = $memory
    interactive_foreground_available = [EASProbe]::GetForegroundWindow() -ne [IntPtr]::Zero
    unauthenticated_controller_available = $bridge
    model_mode = 'none'
    staff_mode = 'no business actions'
}
$result | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot 'result.json')
} catch {
    @{ probe_error=$_.Exception.Message } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot 'result.json')
}
'@
    $file = Join-Path $root 'probe.ps1'
    $script | Set-Content -Encoding UTF8 $file
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$file`""
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::FromMinutes(2))
    Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -User "$env:COMPUTERNAME\$probeName" -Password $password -RunLevel Limited | Out-Null
    Start-ScheduledTask $taskName
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-Path (Join-Path $root 'result.json')) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (-not (Test-Path (Join-Path $root 'result.json'))) { throw 'Probe task did not produce a result' }
    New-Item -ItemType Directory -Force (Split-Path $Output) | Out-Null
    Copy-Item (Join-Path $root 'result.json') $Output -Force
    Get-Content $Output -Raw
} finally {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    if ($created) {
        Set-EasAccountRight $sid 'SeBatchLogonRight' $true
        Remove-LocalUser -Name $probeName -ErrorAction SilentlyContinue
    }
    if (Test-Path $root) { Remove-Item $root -Recurse -Force }
}
