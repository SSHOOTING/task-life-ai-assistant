[CmdletBinding()]
param(
    [int]$Port = 18765,
    [string]$ListenHost = '0.0.0.0'
)

$ErrorActionPreference = 'Stop'
$Root = 'C:\GoalOfOurs'
$Current = Join-Path $Root 'app\current'
$ConfigFile = Join-Path $Root 'config\mvp.env'
$LogsRoot = Join-Path $Root 'logs'
$ArchiveRoot = Join-Path $LogsRoot 'archive'
$PidFile = Join-Path $Root 'data\mvp.pid'
$Python = 'C:\Program Files\Python314\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python not found: $Python"
}
if (-not (Test-Path -LiteralPath (Join-Path $Current 'mvp\app.py'))) {
    throw "Deployed app not found: $Current"
}
New-Item -ItemType Directory -Path $LogsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null

if (Test-Path -LiteralPath $ConfigFile) {
    foreach ($line in Get-Content -LiteralPath $ConfigFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }
        if ($trimmed -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name = $matches[1]
            $value = $matches[2].Trim()
            Set-Item -Path ("Env:" + $name) -Value $value
        }
    }
}

if (-not $env:LLM_MODE) {
    $env:LLM_MODE = 'mock'
}
if (-not $env:SQLITE_PATH) {
    $env:SQLITE_PATH = Join-Path $Root 'data\mvp.db'
}
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $LogsRoot 'mvp.stdout.log'
$stderr = Join-Path $LogsRoot 'mvp.stderr.log'
if (Test-Path -LiteralPath $stdout) {
    Move-Item -LiteralPath $stdout -Destination (Join-Path $ArchiveRoot ("mvp.stdout-" + $stamp + '.log'))
}
if (Test-Path -LiteralPath $stderr) {
    Move-Item -LiteralPath $stderr -Destination (Join-Path $ArchiveRoot ("mvp.stderr-" + $stamp + '.log'))
}

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList @('-u', '-m', 'mvp.app', '--host', $ListenHost, '--port', ([string]$Port)) `
    -WorkingDirectory $Current `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

$processId = $process.Id
Set-Content -LiteralPath $PidFile -Value $processId -Encoding ascii
try {
    $process.WaitForExit()
    $exitCode = $process.ExitCode
}
finally {
    if (Test-Path -LiteralPath $PidFile) {
        $recordedPid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ([string]$recordedPid -eq [string]$processId) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        }
    }
}
exit $exitCode
