[CmdletBinding()]
param(
    [int]$Port = 18765,
    [string]$TaskName = 'GoalOfOurs-MVP',
    [switch]$SmokeTest
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\GoalOfOurs'
$failures = New-Object System.Collections.Generic.List[string]

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    $failures.Add("scheduled task missing: $TaskName")
}
else {
    Write-Output "TASK_STATE=$($task.State)"
    if ($task.State -ne 'Running') {
        $failures.Add("scheduled task is not running: $($task.State)")
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $listener) {
    $failures.Add("no listener on port $Port")
}
else {
    Write-Output "LISTENER=$($listener.LocalAddress):$($listener.LocalPort) PID=$($listener.OwningProcess)"
}

try {
    $health = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $Port + "/api/health") -TimeoutSec 8
    if (-not $health.ok) {
        $failures.Add('/api/health did not return ok=true')
    }
    else {
        Write-Output 'HEALTH_OK=/api/health'
    }
}
catch {
    $failures.Add("/api/health failed: $($_.Exception.Message)")
}

try {
    $page = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $Port + "/") -UseBasicParsing -TimeoutSec 8
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'MVP') {
        $failures.Add('H5 page did not return the expected content')
    }
    else {
        Write-Output 'H5_OK=/'
    }
}
catch {
    $failures.Add("/ failed: $($_.Exception.Message)")
}

if ($SmokeTest) {
    try {
        $sampleBytes = [Convert]::FromBase64String('5LuK5aSp6IOM5a6M5Y2V6K+N5LqG77yM6K665paH5byA5aS05Lmf5pS55LqG77yM6Lef5pyL5Y+L6IGK5a6M5rKh6YKj5LmI54Sm6JmR5LqG44CC')
        $sampleContent = [Text.Encoding]::UTF8.GetString($sampleBytes)
        $body = @{
            user_id = 'U-BLUEPC-SMOKE'
            source = 'h5'
            source_message_id = 'bluepc-smoke-test-v1'
            content = $sampleContent
        } | ConvertTo-Json
        $payload = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $Port + "/api/v1/turns") -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 20
        if ($payload.code -ne 'OK' -or @($payload.data.tasks).Count -ne 2) {
            $failures.Add('fixed smoke turn did not create the expected two records')
        }
        else {
            Write-Output "SMOKE_OK=event:$($payload.data.event_id) tasks:$(@($payload.data.tasks).Count)"
        }
    }
    catch {
        $failures.Add("smoke turn failed: $($_.Exception.Message)")
    }
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) {
        Write-Output "FAIL=$failure"
    }
    exit 1
}

Write-Output "HEALTHCHECK_OK root=$Root port=$Port"
