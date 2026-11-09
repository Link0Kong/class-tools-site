# install_task.ps1 - register a Windows Scheduled Task for jwxt timetable sync.
#
# Action runs pythonw.exe (GUI subsystem, no console window flash) with sync.py,
# working directory = this folder, logs go to .\logs\sync-YYYYMMDD.log (written by sync.py).
# Uses schtasks.exe (no admin elevation required), NOT Register-ScheduledTask.
#
# Examples:
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -At 07:00 -OnLogon
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Term 2026-2027-1 -TermStart 2026-08-31
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Show
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Remove
#   powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Run
#
# NOTE: run "python sync.py --save-creds" once before the task can log in.
#       The task never stores the password: sync.py reads the DPAPI file creds.dpapi.
#
# Login chain (since 2026-11-03): school unified auth (authserver) -> portal -> new jwxt.
# The saved DPAPI password is the *unified auth* password, not the old jwxt password.
# Step 2 of the SSO needs Edge/Chrome (started headless by sync.py); no user interaction.
# Same account must not log in concurrently (sessions kick each other) - do not run a
# manual sync at the same time as this task.

[CmdletBinding()]
param(
    [string]$TaskName = "JwxtTimetableSync",
    [string]$At = "07:00",
    [string]$Term = "",
    [string]$TermStart = "",
    [string]$Out = "..\tools\tt.json",
    [string]$Pythonw = "",
    [switch]$OnLogon,
    [int]$LogonDelayMinutes = 3,
    [switch]$PublishLink,
    [switch]$NoDeploy,
    [switch]$Remove,
    [switch]$Run,
    [switch]$Show
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Write-Info([string]$msg) { Write-Host "[jwxt] $msg" }
function Fail([string]$msg) { Write-Host "[jwxt] ERROR: $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Query / run / remove only
# ---------------------------------------------------------------------------
if ($Show) {
    & schtasks.exe /Query /TN $TaskName /V /FO LIST
    if ($LASTEXITCODE -ne 0) { Fail "task not found: $TaskName" }
    exit 0
}

if ($Remove) {
    & schtasks.exe /Delete /TN $TaskName /F
    if ($LASTEXITCODE -ne 0) { Fail "failed to delete task: $TaskName" }
    Write-Info "task deleted: $TaskName"
    exit 0
}

if ($Run) {
    & schtasks.exe /Run /TN $TaskName
    if ($LASTEXITCODE -ne 0) { Fail "failed to start task: $TaskName" }
    Write-Info "task started: $TaskName (check .\logs\sync-*.log)"
    exit 0
}

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
if ($At -notmatch '^\d{1,2}:\d{2}$') { Fail "invalid -At '$At', expected HH:mm (e.g. 07:00)" }
$At = ([datetime]::Parse($At, [Globalization.CultureInfo]::InvariantCulture)).ToString("HH:mm")

$SyncPy = Join-Path $Here "sync.py"
if (-not (Test-Path $SyncPy)) { Fail "sync.py not found next to this script: $SyncPy" }

if (-not (Test-Path (Join-Path $Here "creds.dpapi"))) {
    Write-Info "WARNING: creds.dpapi not found. Run: python sync.py --save-creds"
}

# ---------------------------------------------------------------------------
# Locate pythonw.exe (required: no console window)
# ---------------------------------------------------------------------------
function Find-Pythonw([string]$Hint) {
    if ($Hint) {
        if (Test-Path $Hint) { return (Resolve-Path $Hint).Path }
        Fail "pythonw.exe not found: $Hint"
    }
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py -and $py.Source) {
        $cand = Join-Path (Split-Path $py.Source) "pythonw.exe"
        if (Test-Path $cand) { return $cand }
    }
    $roots = @()
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA "Programs\Python") }
    if ($env:ProgramFiles) { $roots += (Join-Path $env:ProgramFiles "Python") }
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $found = Get-ChildItem -Path $root -Filter pythonw.exe -Recurse -ErrorAction SilentlyContinue |
                 Sort-Object FullName -Descending | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    Fail "pythonw.exe not found. Pass -Pythonw 'C:\path\to\pythonw.exe'"
}
$PythonwExe = Find-Pythonw $Pythonw
Write-Info "pythonw: $PythonwExe"

# ---------------------------------------------------------------------------
# Build action arguments (absolute paths; task working dir is also set)
# ---------------------------------------------------------------------------
function To-FullPath([string]$p) {
    if ([System.IO.Path]::IsPathRooted($p)) { return [System.IO.Path]::GetFullPath($p) }
    return [System.IO.Path]::GetFullPath((Join-Path $Here $p))
}
$OutAbs = To-FullPath $Out

$parts = @()
$parts += ('"' + $SyncPy + '"')
$parts += '--out'
$parts += ('"' + $OutAbs + '"')
if ($Term) { $parts += '--term'; $parts += $Term }
if ($TermStart) { $parts += '--term-start'; $parts += $TermStart }
if ($PublishLink) { $parts += '--publish-link' }
if (-not $NoDeploy) { $parts += '--deploy' }
$ArgString = ($parts -join ' ')

# ---------------------------------------------------------------------------
# Build Task Scheduler XML (UTF-16 written below)
# ---------------------------------------------------------------------------
$userId = "$env:USERDOMAIN\$env:USERNAME"
$startDate = (Get-Date).ToString("yyyy-MM-dd")
$startBoundary = ($startDate + "T" + $At + ":00")

$escXml = { param($s) [System.Security.SecurityElement]::Escape([string]$s) }

$logonTrigger = ""
if ($OnLogon) {
    $logonTrigger = @"
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$($userId)</UserId>
      <Delay>PT$($LogonDelayMinutes)M</Delay>
    </LogonTrigger>
"@
}

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>$($userId)</Author>
    <Description>Sync class timetable from jwxt (jsxsd) into tools/tt.json</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
$logonTrigger
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$($userId)</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$(& $escXml $PythonwExe)</Command>
      <Arguments>$(& $escXml $ArgString)</Arguments>
      <WorkingDirectory>$(& $escXml $Here)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$xmlPath = Join-Path ([System.IO.Path]::GetTempPath()) ("jwxt-task-" + [guid]::NewGuid().ToString("N") + ".xml")
try {
    [System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
    Write-Info "registering task: $TaskName"
    & schtasks.exe /Create /TN $TaskName /XML $xmlPath /F
    if ($LASTEXITCODE -ne 0) {
        Write-Info "XML import failed (exit $LASTEXITCODE), trying fallback schtasks /SC DAILY ..."
        & schtasks.exe /Create /TN $TaskName /SC DAILY /ST $At /TR ('"' + $PythonwExe + '" ' + $ArgString) /F
        if ($LASTEXITCODE -ne 0) { Fail "schtasks /Create failed (exit $LASTEXITCODE)" }
        Write-Info "WARNING: fallback mode used -> only the daily trigger exists and working dir is not pinned."
    }
}
finally {
    Remove-Item -LiteralPath $xmlPath -Force -ErrorAction SilentlyContinue
}

Write-Info "done. task: $TaskName"
$triggerText = "daily at $At"
if ($OnLogon) { $triggerText += " + at logon (delay ${LogonDelayMinutes}m)" }
Write-Info "trigger: $triggerText"
Write-Info "action : `"$PythonwExe`" $ArgString"
Write-Info "workdir: $Here"
Write-Info "log    : $Here\logs\sync-YYYYMMDD.log"
Write-Info "verify : .\install_task.ps1 -Show   |   .\install_task.ps1 -Run"
Write-Info "remove : .\install_task.ps1 -Remove"
