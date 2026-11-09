# PowerShell helper to manage Windows Scheduled Task for Reddit Video Poster
param(
    [ValidateSet("Install", "Uninstall", "Status", "RunNow")]
    [string]$Action = "Install",
    [int]$IntervalHours = 2
)

$TaskName = "RedditTelegramChannelSaver"
$RepoDir = Split-Path -Parent $PSScriptRoot
$VbsPath = Join-Path $RepoDir "run_silent.vbs"
$BatPath = Join-Path $RepoDir "run_auto.bat"

if ($Action -eq "Install") {
    Write-Host "Configuring Windows Scheduled Task: $TaskName..." -ForegroundColor Cyan

    # Trigger: Starts now, repeats every N hours indefinitely
    $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)
    
    # Action: Run wscript.exe with silent VBS script (no window pops up)
    $TaskAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`"" -WorkingDirectory $RepoDir

    # Settings: Run on battery, wake if needed, hidden
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden

    # Register task for current user
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $TaskName -Action $TaskAction -Trigger $Trigger -Settings $Settings -Description "Automated Reddit video downloader and Telegram channel post scheduler (runs every $IntervalHours hours)." | Out-Null
        Write-Host "Successfully registered '$TaskName' to run every $IntervalHours hours!" -ForegroundColor Green
        Write-Host "Activity will be logged to: $RepoDir\temp\reddit_automation.log" -ForegroundColor Yellow
    } catch {
        Write-Error "Failed to register task: $_"
    }
}
elseif ($Action -eq "Uninstall") {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "Successfully removed scheduled task '$TaskName'." -ForegroundColor Green
    } catch {
        Write-Warning "Task '$TaskName' does not exist or could not be removed."
    }
}
elseif ($Action -eq "Status") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "Task Name:        $TaskName" -ForegroundColor Cyan
        Write-Host "State:            $($task.State)"
        Write-Host "Last Run Time:    $($info.LastRunTime)"
        Write-Host "Last Result Code: $($info.LastTaskResult)"
        Write-Host "Next Run Time:    $($info.NextRunTime)"
    } else {
        Write-Host "Task '$TaskName' is NOT installed." -ForegroundColor Yellow
    }
}
elseif ($Action -eq "RunNow") {
    Write-Host "Starting task '$TaskName' now..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "Triggered! Check $RepoDir\temp\reddit_automation.log for output." -ForegroundColor Green
}
