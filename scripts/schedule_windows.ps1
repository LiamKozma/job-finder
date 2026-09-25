# Registers a Windows Task Scheduler job that runs the job finder every morning.
# Usage (PowerShell, from the repo folder):
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1            # 8:00 AM daily
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1 -Times 08:00,13:00
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1 -Remove
param(
  [string[]]$Times = @("08:00"),
  [switch]$Remove
)
$TaskName = "JobFinderDaily"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task $TaskName."
  exit 0
}

$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue) }
if (-not $py) {
  Write-Host "Python not found. Install it first:  winget install Python.Python.3.12" -ForegroundColor Red
  exit 1
}
$ver = & $py.Source -c "import sys; print(sys.version_info >= (3, 11))"
if ($ver -ne "True") {
  Write-Host "Python 3.11 or newer is required. Install:  winget install Python.Python.3.12" -ForegroundColor Red
  exit 1
}

$env_cmd = "set JOBFINDER_NOPAUSE=1 && `"$Repo\run.bat`" --new-first"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $env_cmd" -WorkingDirectory $Repo
$triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
# StartWhenAvailable: if the laptop was asleep/off at 8am, run as soon as it wakes up.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
  -Description "Find fresh, real, well-matched job postings" -Force | Out-Null
Write-Host "Scheduled '$TaskName' daily at $($Times -join ', '). The report opens in your browser when it runs." -ForegroundColor Green
Write-Host "Run it now:  Start-ScheduledTask -TaskName $TaskName"
