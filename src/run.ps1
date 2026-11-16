#Requires -Version 5.1
<#
.SYNOPSIS
    Perfect Campus Power Monitor - Windows launcher (ASCII only).

.DESCRIPTION
    Wraps electricity_monitor.py and wanxiao_login.py with UTF-8 environment
    variables so Chinese output never crashes on a cp936 console.

.EXAMPLE
    .\run.ps1 doctor
    .\run.ps1 projects
    .\run.ps1 rooms --building 11 --room 616
    .\run.ps1 now
    .\run.ps1 test
    .\run.ps1 report --dry
    .\run.ps1 install
    .\run.ps1 login
    .\run.ps1 sms-code 123456
    .\run.ps1 wx-status

.NOTES
    `status` goes to the monitor ledger status. Use `wx-status` for the
    wanxiao login state.
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONLEGACYWINDOWSSTDIO = "0"
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }
try { chcp 65001 | Out-Null } catch { }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Monitor = Join-Path $Here "electricity_monitor.py"
$Login = Join-Path $Here "wanxiao_login.py"

$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] python.exe not found in PATH." -ForegroundColor Red
    Write-Host "        Install Python 3.8+ and enable 'Add python.exe to PATH'."
    exit 1
}
$Python = $PythonCmd.Source

$Arguments = @($Rest)
if ($Arguments.Count -eq 0) { $Arguments = @("status") }

$LoginCommands = @("login", "sms", "sms-send", "sms-code", "token", "wx-status")
$Script = $Monitor
if ($LoginCommands -contains $Arguments[0]) {
    $Script = $Login
    if ($Arguments[0] -eq "wx-status") { $Arguments[0] = "status" }
}

& $Python $Script @Arguments
exit $LASTEXITCODE
