# install_agent.ps1 - register/unregister the Windows scheduled task for the PPT
# converter agent (web\ppt\agent.py on this Windows machine).
#
# Action: <Python312>\pythonw.exe "<web>\ppt\agent.py" --once
#   * pythonw.exe = GUI subsystem -> the 1-minute schedule never flashes a console window
#   * one round per trigger; agent.py has its own single-instance lock (logs\agent.lock)
#   * every 1 minute, StartWhenAvailable, IgnoreNew, Hidden, InteractiveToken
#     (PowerPoint COM automation needs the interactive desktop => InteractiveToken,
#      NOT "run whether user is logged on or not")
#   * ALSO a LogonTrigger (30s delay) so a login/boot catches queued work immediately
#   * pause: create web\ppt\ppt-agent.pause ; resume: delete it
#   * logs: web\ppt\logs\agent-YYYYMMDD.log
#
# schtasks.exe is used (no admin elevation required on this machine); the repetition +
# logon settings are applied via an XML import. Do NOT use /sc onlogon (denied without
# elevation) and do NOT run powershell/cmd as the task action (console window flashes);
# pythonw.exe is used instead.
#
# Examples:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1            # register, do NOT run now
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -NoRun     # same (explicit)
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Show      # query task incl. LogonType
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Run       # trigger one round now
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -Remove    # unregister
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\install_agent.ps1 -EveryMinutes 2

[CmdletBinding()]
param(
    [string]$TaskName = "PptConvertAgent",
    [int]$EveryMinutes = 1,
    [string]$Pythonw = "",
    [switch]$Remove,
    [switch]$Show,
    [switch]$Run,
    [switch]$NoRun,
    [switch]$Disabled
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Agent = Join-Path $Here "agent.py"
$LogDir = Join-Path $Here "logs"
$DefaultPythonw = "C:\Users\Ko_Li\AppData\Local\Programs\Python\Python312\pythonw.exe"

function Write-Info([string]$msg) { Write-Host "[ppt-agent] $msg" }

if ($Show) {
    & schtasks.exe /Query /TN $TaskName /V /FO LIST
    if ($LASTEXITCODE -ne 0) { Write-Host "[ppt-agent] ERROR: task not found: $TaskName" -ForegroundColor Red; exit 1 }
    exit 0
}

if ($Remove) {
    & schtasks.exe /Delete /TN $TaskName /F
    if ($LASTEXITCODE -ne 0) { Write-Host "[ppt-agent] ERROR: failed to delete task: $TaskName" -ForegroundColor Red; exit 1 }
    Write-Info "task deleted: $TaskName"
    exit 0
}

if ($Run) {
    & schtasks.exe /Run /TN $TaskName
    if ($LASTEXITCODE -ne 0) { Write-Host "[ppt-agent] ERROR: failed to start task: $TaskName" -ForegroundColor Red; exit 1 }
    Write-Info "task started: $TaskName (log: $LogDir\agent-<date>.log)"
    exit 0
}

# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
if (-not (Test-Path $Agent)) {
    Write-Host "[ppt-agent] ERROR: agent.py not found next to this script: $Agent" -ForegroundColor Red
    exit 1
}
if ($EveryMinutes -lt 1 -or $EveryMinutes -gt 60) {
    Write-Host "[ppt-agent] ERROR: -EveryMinutes must be 1..60" -ForegroundColor Red
    exit 1
}
if ($Pythonw) {
    if (-not (Test-Path $Pythonw)) { Write-Host "[ppt-agent] ERROR: pythonw.exe not found: $Pythonw" -ForegroundColor Red; exit 1 }
} else {
    if (Test-Path $DefaultPythonw) {
        $Pythonw = $DefaultPythonw
    } else {
        $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $Pythonw = $cmd.Source }
        else { Write-Host "[ppt-agent] ERROR: pythonw.exe not found; pass -Pythonw 'C:\path\to\pythonw.exe'" -ForegroundColor Red; exit 1 }
    }
}
$Pythonw = (Resolve-Path $Pythonw).Path
$Agent = (Resolve-Path $Agent).Path
Write-Info "pythonw: $Pythonw"
Write-Info "script : $Agent"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

# ---------------------------------------------------------------------------
# Build task XML (repetition + logon + settings; XML import works without elevation)
# ---------------------------------------------------------------------------
$now = Get-Date
$start = $now.AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss")
$interval = "PT${EveryMinutes}M"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$esc = { param($s) $s.Replace("&", "&amp;").Replace("<", "&lt;").Replace(">", "&gt;") }

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>$($now.ToString("yyyy-MM-ddTHH:mm:ss"))</Date>
    <Author>$(& $esc $user)</Author>
    <Description>PPT converter agent (PowerPoint COM + ffmpeg + OSS + CloudBase queue). Runs agent.py --once every $EveryMinutes minute(s) and at logon (30s delay). InteractiveToken is required for PowerPoint COM automation. Log: $(& $esc $LogDir)\agent-YYYYMMDD.log. Pause: create $(& $esc $Here)\ppt-agent.pause. Contract: web\ppt\CONTRACT.md</Description>
    <URI>\$TaskName</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>$sid</UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
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
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <!-- 单任务上限 45min：转换预算 30min（CONTRACT §11.2.2，含原样播放视频）+ 收尾/排队余量；
         多个实例策略 IgnoreNew + 脚本单实例锁 -->
    <ExecutionTimeLimit>PT45M</ExecutionTimeLimit>
    <Priority>7</Priority>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
  </Settings>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>$start</StartBoundary>
      <Repetition>
        <Interval>$interval</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <!-- 登录/开机后 30s 补跑一轮（catch-up；不用 /sc onlogon，走 XML 免提权导入） -->
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$(& $esc $user)</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>$(& $esc $Pythonw)</Command>
      <Arguments>"$(& $esc $Agent)" --once</Arguments>
      <WorkingDirectory>$(& $esc $Here)</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

$tmp = Join-Path $env:TEMP ("ppt_agent_task_" + [guid]::NewGuid().ToString("N") + ".xml")
# Task Scheduler XML import expects UTF-16 (LE with BOM) when declared as UTF-16
[System.IO.File]::WriteAllText($tmp, $xml, [System.Text.UnicodeEncoding]::new($false, $true))

try {
    & schtasks.exe /Create /TN $TaskName /XML $tmp /F
    if ($LASTEXITCODE -ne 0) { Write-Host "[ppt-agent] ERROR: schtasks /Create failed (exit $LASTEXITCODE)" -ForegroundColor Red; exit 1 }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $tmp
}

Write-Info "task created: $TaskName (every $EveryMinutes min + logon 30s, pythonw, InteractiveToken, hidden)"
& schtasks.exe /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "TaskName|Status|Next Run Time|Schedule Type|Repeat|Logon Mode|Run As User"

if (-not $NoRun) {
    # 注意：默认注册后也**不**主动触发（Lead 统一 E2E 后才 /Run）；-Run 才立即跑一轮。
    Write-Info "task registered (not started). Use -Run to trigger one round now, -Show to inspect, -Remove to uninstall."
}
if ($Disabled) {
    & schtasks.exe /Change /TN $TaskName /DISABLE | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "[ppt-agent] ERROR: failed to disable task: $TaskName" -ForegroundColor Red; exit 1 }
    Write-Info "task DISABLED (enable later: schtasks /Change /TN $TaskName /ENABLE)"
}
Write-Info "pause : create $Here\ppt-agent.pause ; resume: delete it"
Write-Info "logs  : $LogDir\agent-YYYYMMDD.log"
Write-Info "manual: $Pythonw `"$Agent`" --once"
exit 0
