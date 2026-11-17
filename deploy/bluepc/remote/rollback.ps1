[CmdletBinding()]
param(
    [int]$Port = 18765,
    [string]$TaskName = 'GoalOfOurs-MVP',
    [switch]$RestoreLatestDatabase
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\GoalOfOurs'
$RootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')

function Get-SafePath {
    param([string]$Path)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $full.Equals($RootFull, [StringComparison]::OrdinalIgnoreCase) -and
        -not $full.StartsWith($RootFull + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside ${RootFull}: $full"
    }
    return $full
}

function Move-SafePath {
    param([string]$Source, [string]$Destination)
    $sourceFull = Get-SafePath $Source
    $destinationFull = Get-SafePath $Destination
    Move-Item -LiteralPath $sourceFull -Destination $destinationFull
}

function Stop-OwnedMvpProcess {
    param(
        [int]$MvpPort,
        [string]$PidFile
    )
    $ExpectedPython = [IO.Path]::GetFullPath('C:\Program Files\Python314\python.exe')
    $candidatePids = New-Object System.Collections.Generic.List[int]

    if (Test-Path -LiteralPath $PidFile) {
        $rawPid = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $parsedPid = 0
        if ([int]::TryParse([string]$rawPid, [ref]$parsedPid)) {
            $candidatePids.Add($parsedPid)
        }
    }

    $listeners = @(Get-NetTCPConnection -LocalPort $MvpPort -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        if (-not $candidatePids.Contains([int]$listener.OwningProcess)) {
            $candidatePids.Add([int]$listener.OwningProcess)
        }
    }

    foreach ($processId in $candidatePids) {
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId = " + $processId) -ErrorAction SilentlyContinue
        if (-not $process) {
            continue
        }
        $executable = if ($process.ExecutablePath) { [IO.Path]::GetFullPath($process.ExecutablePath) } else { '' }
        $commandLine = [string]$process.CommandLine
        $isOwnedMvp = $executable.Equals($ExpectedPython, [StringComparison]::OrdinalIgnoreCase) -and
            $commandLine -match '(?i)(^|\s)-m\s+mvp\.app(\s|$)' -and
            $commandLine -match ('(?i)--port\s+' + $MvpPort + '(\s|$)')
        if (-not $isOwnedMvp) {
            throw "PID $processId is using port $MvpPort but is not a verified MVP process. It will not be stopped."
        }
        Stop-Process -Id $processId -Force
        Write-Output "STOPPED_OWNED_MVP_PID=$processId"
    }

    for ($i = 0; $i -lt 20; $i++) {
        $remaining = Get-NetTCPConnection -LocalPort $MvpPort -State Listen -ErrorAction SilentlyContinue
        if (-not $remaining) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Port $MvpPort is still occupied after stopping the verified MVP process."
}

function Wait-Health {
    param([int]$HealthPort)
    $deadline = (Get-Date).AddSeconds(40)
    do {
        try {
            $response = Invoke-WebRequest -Uri ("http://127.0.0.1:" + $HealthPort + "/api/health") -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds 1
        }
    } while ((Get-Date) -lt $deadline)
    return $false
}

$AppRoot = Get-SafePath (Join-Path $Root 'app')
$Current = Get-SafePath (Join-Path $AppRoot 'current')
$Previous = Get-SafePath (Join-Path $AppRoot 'previous')
$Releases = Get-SafePath (Join-Path $AppRoot 'releases')
$DataRoot = Get-SafePath (Join-Path $Root 'data')
$BackupsRoot = Get-SafePath (Join-Path $Root 'backups')
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

if (-not (Test-Path -LiteralPath $Previous)) {
    throw "No previous release is available at $Previous."
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Stop-OwnedMvpProcess -MvpPort $Port -PidFile (Get-SafePath (Join-Path $DataRoot 'mvp.pid'))
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ','
    throw "Port $Port is still occupied by PID(s): $owners. No process was stopped."
}

if ($RestoreLatestDatabase) {
    $currentDb = Get-SafePath (Join-Path $DataRoot 'mvp.db')
    $latestBackup = Get-ChildItem -LiteralPath (Join-Path $BackupsRoot 'db') -Filter '*.db' -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latestBackup) {
        throw 'No database backup is available.'
    }
    if (Test-Path -LiteralPath $currentDb) {
        Copy-Item -LiteralPath $currentDb -Destination (Join-Path $BackupsRoot ('db\mvp-before-rollback-' + $Stamp + '.db')) -Force
    }
    Copy-Item -LiteralPath $latestBackup.FullName -Destination $currentDb -Force
    Write-Output "DB_RESTORED=$($latestBackup.FullName)"
}

if (Test-Path -LiteralPath $Current) {
    $failedRelease = Get-SafePath (Join-Path $Releases ('rolled-back-' + $Stamp))
    Move-SafePath $Current $failedRelease
}
Move-SafePath $Previous $Current

$runScript = Get-SafePath (Join-Path $Root 'ops\run-mvp.ps1')
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$actionArgs = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $runScript + '" -Port ' + $Port + ' -ListenHost "0.0.0.0"'
$action = New-ScheduledTaskAction -Execute $powershell -Argument $actionArgs -WorkingDirectory $Current
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
if (-not (Wait-Health -HealthPort $Port)) {
    throw "Rollback started the task, but /api/health did not return 200 within 40 seconds."
}

Write-Output 'ROLLBACK_OK'
Write-Output "APP_PATH=$Current"
Write-Output "TASK_NAME=$TaskName"
Write-Output "PORT=$Port"
