[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageZip,
    [Parameter(Mandatory = $true)]
    [string]$ReleaseId,
    [int]$Port = 18765,
    [string]$TaskName = 'GoalOfOurs-MVP',
    [int]$TailscalePort = 0,
    [ValidateSet('mock', 'opencode')]
    [string]$LlmMode = 'mock'
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
    if (-not (Test-Path -LiteralPath $sourceFull)) {
        throw "Source does not exist: $sourceFull"
    }
    Move-Item -LiteralPath $sourceFull -Destination $destinationFull
}

function Remove-SafePath {
    param([string]$Path)
    $full = Get-SafePath $Path
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
}

function Set-EnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    $lines = @()
    if (Test-Path -LiteralPath $Path) {
        $lines = @(Get-Content -LiteralPath $Path)
    }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match ('^\s*' + [regex]::Escape($Name) + '\s*=')) {
            $lines[$i] = "$Name=$Value"
            $found = $true
        }
    }
    if (-not $found) {
        $lines += "$Name=$Value"
    }
    Set-Content -LiteralPath $Path -Value $lines -Encoding utf8
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

$PackageFull = Get-SafePath $PackageZip
$AppRoot = Get-SafePath (Join-Path $Root 'app')
$Current = Get-SafePath (Join-Path $AppRoot 'current')
$Previous = Get-SafePath (Join-Path $AppRoot 'previous')
$Releases = Get-SafePath (Join-Path $AppRoot 'releases')
$DataRoot = Get-SafePath (Join-Path $Root 'data')
$LogsRoot = Get-SafePath (Join-Path $Root 'logs')
$BackupsRoot = Get-SafePath (Join-Path $Root 'backups')
$ConfigRoot = Get-SafePath (Join-Path $Root 'config')
$OpsRoot = Get-SafePath (Join-Path $Root 'ops')
$Staging = Get-SafePath (Join-Path $AppRoot ('staging-' + $ReleaseId))
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

foreach ($path in @(
    $AppRoot,
    $Current,
    $Previous,
    $Releases,
    $DataRoot,
    $LogsRoot,
    $BackupsRoot,
    $ConfigRoot,
    $OpsRoot
)) {
    if ($path -in @($Current, $Previous)) {
        continue
    }
    New-Item -ItemType Directory -Path $path -Force | Out-Null
}
New-Item -ItemType Directory -Path (Get-SafePath (Join-Path $BackupsRoot 'releases')) -Force | Out-Null
New-Item -ItemType Directory -Path (Get-SafePath (Join-Path $BackupsRoot 'db')) -Force | Out-Null
New-Item -ItemType Directory -Path (Get-SafePath (Join-Path $LogsRoot 'archive')) -Force | Out-Null

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($existingTask.TaskPath -ne '\') {
        throw "Refusing to replace an unexpected task path: $($existingTask.TaskPath)"
    }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Stop-OwnedMvpProcess -MvpPort $Port -PidFile (Get-SafePath (Join-Path $DataRoot 'mvp.pid'))
$listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ','
    throw "Port $Port is still occupied by PID(s): $owners. No process was stopped."
}

if (Test-Path -LiteralPath (Join-Path $DataRoot 'mvp.db')) {
    Copy-Item -LiteralPath (Join-Path $DataRoot 'mvp.db') -Destination (Join-Path $BackupsRoot ('db\mvp-before-deploy-' + $Stamp + '.db')) -Force
}

Remove-SafePath $Staging
Expand-Archive -LiteralPath $PackageFull -DestinationPath $Staging -Force
$stagedApp = Get-SafePath (Join-Path $Staging 'mvp\app.py')
$stagedWeb = Get-SafePath (Join-Path $Staging 'mvp\web\index.html')
if (-not (Test-Path -LiteralPath $stagedApp) -or -not (Test-Path -LiteralPath $stagedWeb)) {
    throw 'Staged package is missing mvp/app.py or mvp/web/index.html.'
}
$forbidden = @(Get-ChildItem -LiteralPath $Staging -Recurse -Force -File | Where-Object {
    $_.Name -eq '.env' -or
    $_.Name -like '*.db' -or
    $_.Name -like '*.sqlite*' -or
    $_.Name -like '*.pyc' -or
    $_.Name -like '*.log'
})
if ($forbidden.Count -gt 0) {
    throw "Staged package contains forbidden runtime files: $($forbidden[0].FullName)"
}

$envFile = Get-SafePath (Join-Path $ConfigRoot 'mvp.env')
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $OpsRoot 'mvp.env.example') -Destination $envFile
}
Set-EnvValue -Path $envFile -Name 'LLM_MODE' -Value $LlmMode
Set-EnvValue -Path $envFile -Name 'SQLITE_PATH' -Value (Join-Path $DataRoot 'mvp.db')

$packageBackup = Get-SafePath (Join-Path $BackupsRoot ('releases\' + ([IO.Path]::GetFileName($PackageFull))))
Copy-Item -LiteralPath $PackageFull -Destination $packageBackup -Force

if (Test-Path -LiteralPath $Previous) {
    $oldPrevious = Get-SafePath (Join-Path $Releases ('previous-' + $Stamp))
    Move-SafePath $Previous $oldPrevious
}
if (Test-Path -LiteralPath $Current) {
    Move-SafePath $Current $Previous
}
Move-SafePath $Staging $Current

$runScript = Get-SafePath (Join-Path $OpsRoot 'run-mvp.ps1')
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
    throw "Task $TaskName started, but /api/health did not return 200 within 40 seconds. Check $LogsRoot."
}

if ($TailscalePort -gt 0) {
    $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
    if (-not $tailscale) {
        throw 'Tailscale CLI was not found, so the requested tailnet share could not be configured.'
    }
    & $tailscale.Source serve --bg --yes "--tcp=$TailscalePort" ("tcp://127.0.0.1:" + $Port)
    if ($LASTEXITCODE -ne 0) {
        throw "Tailscale Serve failed with exit code $LASTEXITCODE."
    }
    Write-Output "TAILSCALE_TCP=tcp://127.0.0.1:$Port via tailnet port $TailscalePort"
}

Write-Output "DEPLOY_OK release=$ReleaseId"
Write-Output "APP_PATH=$Current"
Write-Output "DATA_PATH=$(Join-Path $DataRoot 'mvp.db')"
Write-Output "CONFIG_PATH=$envFile"
Write-Output "LOG_PATH=$LogsRoot"
Write-Output "TASK_NAME=$TaskName"
Write-Output "PORT=$Port"
