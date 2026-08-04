# 자산 인사이트 — 윈도우 작업 스케줄러 등록
#
#   powershell -ExecutionPolicy Bypass -File 예약등록.ps1
#   powershell -ExecutionPolicy Bypass -File 예약등록.ps1 -Remove   (해제)
#
# 등록되는 예약 (평일만):
#   08:00  국장 개장 1시간 전  → 국장 + 매크로
#   21:30  미장 개장 1시간 전  → 미장 + 매크로 + 코인 (서머타임 기준)
#   22:30  미장 개장 1시간 전  → 겨울용. 여름엔 --auto가 알아서 건너뜁니다.
#
# 세 예약 모두 run.py --auto를 부르고, --auto가 지금 열릴 장만 고릅니다.
# 3시간 안에 이미 받은 자산군은 다시 받지 않으므로 중복 과금이 없습니다.

param([switch]$Remove)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat  = Join-Path $root "예약갱신.bat"
$names = @("자산인사이트-국장", "자산인사이트-미장(여름)", "자산인사이트-미장(겨울)")

if ($Remove) {
    foreach ($n in $names) {
        try {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction Stop
            Write-Host "  해제  $n"
        } catch { Write-Host "  없음  $n" }
    }
    Write-Host "`n예약을 모두 해제했습니다."
    return
}

if (-not (Test-Path $bat)) { throw "예약갱신.bat을 찾을 수 없습니다: $bat" }

$times = @{ $names[0] = "08:00"; $names[1] = "21:30"; $names[2] = "22:30" }
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root

# 노트북이 배터리일 때도 돌게 하고, PC가 꺼져 있어 놓친 예약은
# 켜자마자 한 번 따라잡게 한다.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

foreach ($n in $names) {
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $times[$n]
    try { Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction Stop } catch {}
    Register-ScheduledTask -TaskName $n -Action $action -Trigger $trigger `
        -Settings $settings -Description "자산 인사이트 자동 갱신 (run.py --auto)" | Out-Null
    Write-Host ("  등록  {0,-22} 평일 {1}" -f $n, $times[$n])
}

Write-Host "`n등록 완료. 확인:  Get-ScheduledTask 자산인사이트-*"
Write-Host "실행 기록은 data\예약실행.log 에 쌓입니다."
Write-Host "PC가 켜져 있어야 돌아갑니다 (절전은 괜찮고, 종료면 켠 뒤 따라잡습니다)."
