# ChatMemoir admin scheduled task setup.
# Invoked by setup-admin-task.bat (already elevated via UAC).
# Registers ChatMemoirAdmin task so GUI can be launched with admin privileges
# from WSL via: schtasks.exe /run /tn ChatMemoirAdmin
# Logs everything to admin-task-setup.log (readable from WSL for debugging).

$ErrorActionPreference = 'Continue'
$taskName = 'ChatMemoirAdmin'
$workDir = $PSScriptRoot
$logPath = Join-Path $workDir 'admin-task-setup.log'

function Log($msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "$ts  $msg"
    Add-Content -Path $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

# Reset log on each run
Set-Content -Path $logPath -Value "=== ChatMemoir admin task setup $(Get-Date) ===" -Encoding UTF8

# Sanity: confirm we're elevated (bat should have already done this)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Log 'ERROR: Not running as admin. The .bat should have elevated. Aborting.'
    Read-Host 'Press Enter to exit'
    exit 1
}

Log "Elevated:    YES"
Log "User:        $($identity.Name)"
Log "WorkDir:     $workDir"
Log "OS:          $([System.Environment]::OSVersion.VersionString)"
Log "PowerShell:  $($PSVersionTable.PSVersion)"

# Resolve pythonw.exe to absolute path (scheduled tasks need full paths)
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    Log 'ERROR: pythonw.exe not found in PATH. Install Python or add to PATH first.'
    Read-Host 'Press Enter to exit'
    exit 1
}
Log "pythonw.exe: $pythonw"

# Verify gui.py exists in work dir
$guiPy = Join-Path $workDir 'gui.py'
if (-not (Test-Path $guiPy)) {
    Log "ERROR: gui.py not found at $guiPy - wrong project dir?"
    Read-Host 'Press Enter to exit'
    exit 1
}
Log "gui.py:      found"

# Register the scheduled task
try {
    $action    = New-ScheduledTaskAction    -Execute $pythonw -Argument 'gui.py' -WorkingDirectory $workDir
    $principal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    Log "Task '$taskName' registered."
} catch {
    Log "ERROR: Register-ScheduledTask failed: $($_.Exception.Message)"
    Read-Host 'Press Enter to exit'
    exit 1
}

# Verify by querying it back
try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Log '--- task verification ---'
    Log "  State:       $($task.State)"
    Log "  RunLevel:    $($task.Principal.RunLevel)"
    Log "  UserId:      $($task.Principal.UserId)"
    Log "  Execute:     $($task.Actions[0].Execute)"
    Log "  Arguments:   $($task.Actions[0].Arguments)"
    Log "  WorkingDir:  $($task.Actions[0].WorkingDirectory)"
    Log '--- end verification ---'
} catch {
    Log "ERROR: post-register verification query failed: $($_.Exception.Message)"
}

Log ''
Log 'Setup complete. From WSL, Claude can now launch the GUI admin via:'
Log "  schtasks.exe /run /tn $taskName"
Log ''
Read-Host 'Press Enter to close this window'
