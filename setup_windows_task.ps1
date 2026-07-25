<#
.SYNOPSIS
    配置 Windows 任务计划程序，定时运行 TikTok 选品分析 (SEA 区域)
#>

$TaskPath = "TikTokAuto"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BatFile = Join-Path $ScriptDir "run_sea.bat"

if (-not (Test-Path $BatFile)) {
    Write-Error "找不到 run_sea.bat: $BatFile"
    exit 1
}

# 删除旧任务
Get-ScheduledTask -TaskPath ("\" + $TaskPath + "\") -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue

# 创建 3 个定时任务
$Tasks = @(
    @{Name="SEA 08:00"; Hour=8;  Minute=0},
    @{Name="SEA 12:00"; Hour=12; Minute=0},
    @{Name="SEA 20:00"; Hour=20; Minute=0}
)

$Created = 0
foreach ($T in $Tasks) {
    $Trigger = New-ScheduledTaskTrigger -Daily -At "$($T.Hour):$($T.Minute)"
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`"" -WorkingDirectory $ScriptDir
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    Register-ScheduledTask -TaskPath ("\" + $TaskPath + "\") -TaskName $T.Name -Trigger $Trigger -Action $Action -Settings $Settings -User "SYSTEM" -RunLevel Limited -Force | Out-Null
    $Created++
    Write-Host "  [OK] 已创建: SEA $($T.Hour):00" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 已完成！共创建 $Created 个定时任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "管理命令:" -ForegroundColor Yellow
Write-Host "  Get-ScheduledTask -TaskPath \$TaskPath\ (查看)" -ForegroundColor Gray
Write-Host "  Start-ScheduledTask -TaskPath \$TaskPath\ -TaskName 'SEA 08:00' (手动运行)" -ForegroundColor Gray
