<#
.SYNOPSIS
    配置 Windows 任务计划程序，定时运行 TikTok 选品分析 (SEA 区域)

.DESCRIPTION
    创建三个定时任务，分别在 08:00 / 12:00 / 20:00 执行 SEA 选品分析。
    使用前需要:
    1. 已配置 .env 文件
    2. 已安装依赖 (pip install -r requirements.txt)

    查看已创建的任务: Get-ScheduledTask -TaskPath "\TikTokAuto\"
    手动运行:        Start-ScheduledTask -TaskPath "\TikTokAuto\" -TaskName "SEA 08:00"
    删除所有任务:    Unregister-ScheduledTask -TaskPath "\TikTokAuto\" -Confirm:$false
#>

$TaskPath = "\TikTokAuto\"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BatFile = Join-Path $ScriptDir "run_sea.bat"

# 确保脚本路径存在
if (-not (Test-Path $BatFile)) {
    Write-Error "找不到 run_sea.bat: $BatFile"
    exit 1
}

# 任务配置
$Tasks = @(
    @{Name="SEA 08:00"; Hour=8;  Minute=0; Description="TikTok 选品分析 - 早上 8:00"},
    @{Name="SEA 12:00"; Hour=12; Minute=0; Description="TikTok 选品分析 - 中午 12:00"},
    @{Name="SEA 20:00"; Hour=20; Minute=0; Description="TikTok 选品分析 - 晚上 20:00"}
)

# 创建任务路径（如果不存在）
$null = New-Item -Path "Task:\$TaskPath" -ItemType "TaskPath" -Force -ErrorAction SilentlyContinue

$Created = 0
foreach ($Task in $Tasks) {
    $TaskName = $Task.Name

    # 如果任务已存在，先删除
    $Existing = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($Existing) {
        Write-Host "任务已存在，正在更新: $TaskName" -ForegroundColor Yellow
        $null = Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
    }

    # 创建触发器
    $Trigger = New-ScheduledTaskTrigger -Daily -At "$($Task.Hour):$($Task.Minute)"

    # 创建执行动作
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`"" -WorkingDirectory $ScriptDir

    # 创建任务
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

    $null = Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Trigger $Trigger -Action $Action -Settings $Settings -Description $Task.Description -User "SYSTEM" -RunLevel Limited -Force

    Write-Host "  [OK] 已创建: $($Task.Description)" -ForegroundColor Green
    $Created++
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 已完成！共创建 $Created 个定时任务" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "手动管理命令:" -ForegroundColor Yellow
Write-Host "  查看任务:   Get-ScheduledTask -TaskPath `"\TikTokAuto\`"" -ForegroundColor Gray
Write-Host "  手动运行:   Start-ScheduledTask -TaskPath `"\TikTokAuto\`" -TaskName `"SEA 08:00`"" -ForegroundColor Gray
Write-Host "  删除所有:   Unregister-ScheduledTask -TaskPath `"\TikTokAuto\`" -Confirm:`$false" -ForegroundColor Gray
