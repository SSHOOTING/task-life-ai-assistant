$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$localRoot = [System.IO.Path]::GetFullPath((Join-Path $repo ".local"))
$smokeRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $localRoot ("ci-deploy-smoke-" + [guid]::NewGuid().ToString("N")))
)
$localPrefix = $localRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $smokeRoot.StartsWith($localPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe smoke-test path: $smokeRoot"
}

$goodZip = (Resolve-Path (Join-Path $repo "dist\goal-of-ours-mvp.zip")).Path
$deployScript = (Resolve-Path (Join-Path $repo "deploy\bluepc\deploy.ps1")).Path
$appRoot = Join-Path $smokeRoot "app"
$badZip = Join-Path $smokeRoot "goal-of-ours-mvp-bad.zip"

function Invoke-BluePcDeploy {
    param([string[]]$Arguments)
    $callId = [guid]::NewGuid().ToString("N")
    $stdoutLog = Join-Path $smokeRoot "deploy-$callId.out.log"
    $stderrLog = Join-Path $smokeRoot "deploy-$callId.err.log"
    $exitFile = Join-Path $smokeRoot "deploy-$callId.exit"
    $quotedArguments = for ($index = 0; $index -lt $Arguments.Count; $index++) {
        $argument = $Arguments[$index]
        if ($argument.StartsWith("-")) {
            $argument
        } else {
            "'" + $argument.Replace("'", "''") + "'"
        }
    }
    $command = @"
`$deploymentExit = 1
`$ProgressPreference = 'SilentlyContinue'
try {
    & '$($deployScript.Replace("'", "''"))' $($quotedArguments -join " ")
    if (`$null -eq `$LASTEXITCODE) {
        `$deploymentExit = 0
    } else {
        `$deploymentExit = [int]`$LASTEXITCODE
    }
} catch {
    [Console]::Error.WriteLine("DEPLOY_CALL_ERROR: " + `$_.Exception.Message)
    `$deploymentExit = 1
}
Set-Content -LiteralPath '$($exitFile.Replace("'", "''"))' -Value ([string]`$deploymentExit)
exit `$deploymentExit
"@
    $encodedCommand = [Convert]::ToBase64String(
        [System.Text.Encoding]::Unicode.GetBytes($command)
    )
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-EncodedCommand", $encodedCommand
        ) `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-Path -LiteralPath $exitFile) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
    }
    if (-not (Test-Path -LiteralPath $exitFile)) {
        throw "Deployment call $callId did not produce an exit code."
    }
    if (Test-Path -LiteralPath $stdoutLog) {
        Get-Content -LiteralPath $stdoutLog -ErrorAction SilentlyContinue | Write-Host
    }
    if (Test-Path -LiteralPath $stderrLog) {
        Get-Content -LiteralPath $stderrLog -ErrorAction SilentlyContinue | Write-Host
    }
    return [int](Get-Content -LiteralPath $exitFile -Raw)
}

function Get-DeployState {
    $statePath = Join-Path $appRoot "deploy-state.json"
    return (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json)
}

function Assert-Healthy {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18766/health" -TimeoutSec 5
    if ([int]$response.StatusCode -ne 200) {
        throw "Health check failed: $($response.StatusCode)"
    }
}

New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
Copy-Item -LiteralPath $goodZip -Destination $badZip
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression
$zip = [System.IO.Compression.ZipFile]::Open($badZip, [System.IO.Compression.ZipArchiveMode]::Update)
try {
    $entry = $zip.GetEntry("mvp/app.py")
    if ($null -eq $entry) {
        throw "mvp/app.py is missing from the test archive."
    }
    $entry.Delete()
    $newEntry = $zip.CreateEntry("mvp/app.py")
    $writer = New-Object System.IO.StreamWriter($newEntry.Open())
    try {
        $writer.Write("raise SystemExit('intentional smoke-test failure')" + "`n")
    } finally {
        $writer.Dispose()
    }
} finally {
    $zip.Dispose()
}

try {
    $exitCode = Invoke-BluePcDeploy @(
        "-ReleaseZip", $goodZip,
        "-AppDir", $appRoot,
        "-ReleaseId", "good-1",
        "-Port", "18766",
        "-HealthTimeoutSeconds", "20"
    )
    if ($exitCode -ne 0) {
        throw "good-1 deployment failed with exit code $exitCode."
    }
    Assert-Healthy
    if ((Get-DeployState).release_id -ne "good-1") {
        throw "Unexpected state after good-1 deployment."
    }
    Write-Host "SMOKE good-1 deploy and health: OK"

    $exitCode = Invoke-BluePcDeploy @(
        "-ReleaseZip", $badZip,
        "-AppDir", $appRoot,
        "-ReleaseId", "bad-1",
        "-Port", "18766",
        "-HealthTimeoutSeconds", "8"
    )
    if ($exitCode -eq 0) {
        throw "bad-1 deployment unexpectedly succeeded."
    }
    if ((Get-DeployState).release_id -ne "good-1") {
        throw "Automatic rollback did not restore good-1."
    }
    Assert-Healthy
    Write-Host "SMOKE bad-1 failure and automatic rollback: OK"

    $exitCode = Invoke-BluePcDeploy @(
        "-ReleaseZip", $goodZip,
        "-AppDir", $appRoot,
        "-ReleaseId", "good-2",
        "-Port", "18766",
        "-HealthTimeoutSeconds", "20"
    )
    if ($exitCode -ne 0) {
        throw "good-2 deployment failed with exit code $exitCode."
    }
    $state = Get-DeployState
    if ($state.release_id -ne "good-2" -or $state.previous.release_id -ne "good-1") {
        throw "Unexpected state after good-2 deployment."
    }
    Write-Host "SMOKE good-2 deploy: OK"

    $exitCode = Invoke-BluePcDeploy @(
        "-AppDir", $appRoot,
        "-Rollback",
        "-Port", "18766",
        "-HealthTimeoutSeconds", "20"
    )
    if ($exitCode -ne 0) {
        throw "Manual rollback failed with exit code $exitCode."
    }
    if ((Get-DeployState).release_id -ne "good-1") {
        throw "Manual rollback did not restore good-1."
    }
    Assert-Healthy
    Write-Host "SMOKE manual rollback: OK"
} finally {
    $statePath = Join-Path $appRoot "deploy-state.json"
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $processId = [int]$state.process_id
        if ($processId -gt 0) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
            if ($null -ne $process -and
                $process.CommandLine.Contains($appRoot) -and
                $process.CommandLine.Contains("mvp.app")) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
    }

    if (Test-Path -LiteralPath $smokeRoot) {
        $resolvedSmoke = [System.IO.Path]::GetFullPath($smokeRoot)
        if (-not $resolvedSmoke.StartsWith($localPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing cleanup outside .local: $resolvedSmoke"
        }
        Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
    }
}
