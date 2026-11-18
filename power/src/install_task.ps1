#Requires -Version 5.1
<#
.SYNOPSIS
    Install / remove scheduled tasks for the Perfect Campus power monitor.

.DESCRIPTION
    Registers two Windows scheduled tasks with schtasks.exe (schtasks /create
    works without elevation on the tested machine; PowerShell
    Register-ScheduledTask may be denied):

      PerfectCampusPower_Hourly : every hour
          pythonw.exe electricity_monitor.py sample --log logs\monitor.log
      PerfectCampusPower_Weekly : Monday 00:05
          pythonw.exe electricity_monitor.py report --log logs\report.log

    pythonw.exe has no console window, so nothing flashes every hour.
    Each run appends timestamped output to the logs\ folder.
    Credential files (config.json / wanxiao_state.json) are permission-tightened
    if they exist.

.PARAMETER PythonExe
    Full path to python.exe. Default: first python.exe found in PATH.

.PARAMETER NoPythonw
    Use python.exe instead of pythonw.exe (a console window may flash).

.PARAMETER Remove
    Delete both scheduled tasks and exit.

.PARAMETER Status
    Print current task state and exit.

.PARAMETER DryRun
    Print the exact schtasks commands, do not create any task.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Status

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File install_task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$PythonExe = "",
    [switch]$NoPythonw,
    [switch]$Remove,
    [switch]$Status,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Monitor = Join-Path $Here "electricity_monitor.py"
$ConfigFile = Join-Path $Here "config.json"
$StateFile = Join-Path $Here "wanxiao_state.json"
$Database = Join-Path $Here "electricity.db"
$LogDir = Join-Path $Here "logs"
$HourlyLog = Join-Path $LogDir "monitor.log"
$WeeklyLog = Join-Path $LogDir "report.log"
$TaskHourly = "PerfectCampusPower_Hourly"
$TaskWeekly = "PerfectCampusPower_Weekly"

function Write-Step([string]$Text) { Write-Host ("[ .. ] " + $Text) }
function Write-Ok([string]$Text) { Write-Host ("[ OK ] " + $Text) -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host ("[WARN] " + $Text) -ForegroundColor Yellow }
function Write-Err([string]$Text) { Write-Host ("[FAIL] " + $Text) -ForegroundColor Red }

function Invoke-Schtasks([string[]]$SchtasksArgs) {
    # schtasks writes "not found" to stderr; with $ErrorActionPreference = "Stop"
    # PowerShell 5.1 would turn that into a terminating NativeCommandError.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & schtasks.exe @SchtasksArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return @{
        ExitCode = $code
        Output   = (($output | ForEach-Object { "$_" }) -join "`n")
    }
}

function Format-Command([string[]]$SchtasksArgs) {
    $parts = foreach ($arg in $SchtasksArgs) {
        if ($arg -match '[\s"]') {
            '"' + ($arg -replace '"', '\"') + '"'
        } else {
            $arg
        }
    }
    return "schtasks.exe " + ($parts -join " ")
}

function Show-TaskShort([string]$Name) {
    $result = Invoke-Schtasks @("/Query", "/TN", $Name, "/FO", "LIST")
    if ($result.ExitCode -ne 0) {
        Write-Warn ("not installed: " + $Name)
        return $false
    }
    Write-Host ("--- " + $Name + " ---")
    foreach ($line in ($result.Output -split "`r?`n")) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -gt 0 -and $trimmed -notmatch "^HostName") {
            Write-Host ("  " + $trimmed)
        }
    }
    return $true
}

function Test-TaskCommand([string]$Name, [string[]]$MustContain) {
    $result = Invoke-Schtasks @("/Query", "/TN", $Name, "/XML")
    if ($result.ExitCode -ne 0) { return $false }
    foreach ($needle in $MustContain) {
        if (-not $result.Output.Contains($needle)) { return $false }
    }
    return $true
}

function Remove-OneTask([string]$Name) {
    $result = Invoke-Schtasks @("/Delete", "/TN", $Name, "/F")
    if ($result.ExitCode -eq 0) {
        Write-Ok ("removed: " + $Name)
    } else {
        Write-Warn ("not removed (probably not installed): " + $Name)
    }
}

function Protect-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    & icacls.exe $Path /inheritance:r /grant:r ("{0}:F" -f $env:USERNAME) /Q | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok ("permissions tightened: " + $Path)
    } else {
        Write-Warn ("icacls failed (not fatal): " + $Path)
    }
}

Write-Host "Perfect Campus Power Monitor - scheduled task installer"
Write-Host ("working dir: " + $Here)

if ($Status) {
    Write-Host ""
    $found = 0
    if (Show-TaskShort $TaskHourly) { $found++ }
    if (Show-TaskShort $TaskWeekly) { $found++ }
    if ($found -eq 0) {
        Write-Host ""
        Write-Host "No tasks installed. Run install_task.ps1 to install."
    }
    exit 0
}

if ($Remove) {
    Write-Host ""
    Remove-OneTask $TaskHourly
    Remove-OneTask $TaskWeekly
    exit 0
}

if (-not (Test-Path -LiteralPath $Monitor)) {
    Write-Err ("monitor script not found: " + $Monitor)
    exit 1
}

# ---------------------------------------------------------------- python ---
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Err "python.exe not found in PATH. Install Python 3.8+ or pass -PythonExe <path>."
        exit 1
    }
    $PythonExe = $pythonCmd.Source
}
try {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
} catch {
    Write-Err ("python.exe not found: " + $PythonExe)
    exit 1
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Err ("python.exe not found: " + $PythonExe)
    exit 1
}
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $versionText = (& $PythonExe -c "import sys; print(sys.version.split()[0]); raise SystemExit(0 if sys.version_info >= (3,8) else 1)" 2>&1 | Out-String).Trim()
    $versionExit = $LASTEXITCODE
    $probe = & $PythonExe $Monitor --version 2>&1
    $probeExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorAction
}
if ($versionExit -ne 0) {
    Write-Err ("Python 3.8+ required, found: " + $versionText)
    exit 1
}
Write-Ok ("python: " + $PythonExe + "  (version " + $versionText + ")")

if ($probeExit -ne 0) {
    Write-Err ("monitor script self-check failed: " + (($probe | ForEach-Object { "$_" }) -join " "))
    exit 1
}
Write-Ok ("monitor: " + $Monitor)

$PythonW = Join-Path (Split-Path -Parent $PythonExe) "pythonw.exe"
if ($NoPythonw) {
    $Runner = $PythonExe
    Write-Warn "using python.exe (-NoPythonw): a console window may flash every hour"
} elseif (Test-Path -LiteralPath $PythonW) {
    $Runner = $PythonW
    Write-Ok ("runner: " + $PythonW + "  (no console window)")
} else {
    $Runner = $PythonExe
    Write-Warn ("pythonw.exe not found next to python.exe; using python.exe (console may flash)")
    Write-Warn ("pass -NoPythonw to silence this warning, or install full Python distribution")
}

if (-not (Test-Path -LiteralPath $ConfigFile)) {
    Write-Warn ("config.json not found: " + $ConfigFile)
    Write-Warn "the hourly task will log an error until you copy config.example.json and fill it"
}

if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ------------------------------------------------------------- commands ---
$HourlyCommand = '"' + $Runner + '" "' + $Monitor + '" sample --log "' + $HourlyLog + '"'
$WeeklyCommand = '"' + $Runner + '" "' + $Monitor + '" report --log "' + $WeeklyLog + '"'

$HourlyArgs = @("/Create", "/TN", $TaskHourly, "/SC", "HOURLY", "/MO", "1", "/TR", $HourlyCommand, "/F")
$WeeklyArgs = @("/Create", "/TN", $TaskWeekly, "/SC", "WEEKLY", "/D", "MON", "/ST", "00:05", "/TR", $WeeklyCommand, "/F")

Write-Host ""
Write-Host "Commands:"
Write-Host ("  " + (Format-Command $HourlyArgs))
Write-Host ("  " + (Format-Command $WeeklyArgs))

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun: nothing was created. Re-run without -DryRun to install."
    exit 0
}

Write-Host ""
Write-Step "creating hourly task"
$result = Invoke-Schtasks $HourlyArgs
if ($result.ExitCode -ne 0) {
    Write-Err ("schtasks /Create failed (hourly): " + $result.Output)
    exit 1
}
Write-Ok ("created: " + $TaskHourly)

Write-Step "creating weekly task"
$result = Invoke-Schtasks $WeeklyArgs
if ($result.ExitCode -ne 0) {
    Write-Err ("schtasks /Create failed (weekly): " + $result.Output)
    exit 1
}
Write-Ok ("created: " + $TaskWeekly)

Write-Step "verifying task actions"
$hourlyOk = Test-TaskCommand $TaskHourly @($Runner, $Monitor, "sample", $HourlyLog)
$weeklyOk = Test-TaskCommand $TaskWeekly @($Runner, $Monitor, "report", $WeeklyLog)
if ($hourlyOk) { Write-Ok "hourly action verified (pythonw + sample + log)" } else { Write-Warn "hourly action could not be fully verified; check with -Status" }
if ($weeklyOk) { Write-Ok "weekly action verified (pythonw + report + log)" } else { Write-Warn "weekly action could not be fully verified; check with -Status" }

Write-Step "tightening permissions of local credential files"
Protect-File $ConfigFile
Protect-File $StateFile
Protect-File $Database

Write-Host ""
Write-Host "Done. Installed tasks:"
Write-Host ("  " + $TaskHourly + "  ->  every hour, logs: " + $HourlyLog)
Write-Host ("  " + $TaskWeekly + "  ->  Monday 00:05, logs: " + $WeeklyLog)
Write-Host ""
Write-Host "Useful commands:"
Write-Host ('  schtasks /Query /TN "' + $TaskHourly + '" /V /FO LIST')
Write-Host ('  schtasks /Query /TN "' + $TaskWeekly + '" /V /FO LIST')
Write-Host ('  schtasks /Run /TN "' + $TaskHourly + '"')
Write-Host ('  schtasks /End /TN "' + $TaskHourly + '"')
Write-Host ('  schtasks /Delete /TN "' + $TaskHourly + '" /F')
Write-Host ('  schtasks /Delete /TN "' + $TaskWeekly + '" /F')
Write-Host ('  powershell -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Here "install_task.ps1") + '" -Status')
Write-Host ('  powershell -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Here "install_task.ps1") + '" -Remove')
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1) fill config.json  (run.bat doctor tells you what is missing)"
Write-Host "  2) run.bat now       (read remaining kWh once)"
Write-Host "  3) run.bat test      (push one confirmation message)"
Write-Host ""
Write-Host "Note: keep sampling at most once per hour. Faster polling trips the WAF."
exit 0
