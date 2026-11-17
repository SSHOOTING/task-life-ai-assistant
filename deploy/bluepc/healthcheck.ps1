[CmdletBinding()]
param(
    [string]$BluePcHost = 'bluepc',
    [int]$Port = 18765,
    [string]$TaskName = 'GoalOfOurs-MVP',
    [int]$TailscalePort = 18766,
    [string]$DirectHost,
    [switch]$SkipDirectCheck
)

$ErrorActionPreference = 'Stop'

$remoteScript = @"
`$ErrorActionPreference = 'Stop'
& 'C:\GoalOfOurs\ops\healthcheck.ps1' -Port $Port -TaskName '$TaskName' -SmokeTest
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($remoteScript))

& ssh $BluePcHost powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded
if ($LASTEXITCODE -ne 0) {
    throw "Remote health check failed with exit code $LASTEXITCODE."
}

if (-not $SkipDirectCheck) {
    if (-not $DirectHost) {
        $tailscaleIp = & ssh $BluePcHost "tailscale ip -4"
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not read the blue PC Tailscale IPv4 address.'
        }
        $DirectHost = (
            $tailscaleIp |
                Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } |
                Select-Object -First 1
        )
        if (-not $DirectHost) {
            throw 'The blue PC Tailscale IPv4 address was empty.'
        }
        $DirectHost = [string]$DirectHost
        $DirectHost = $DirectHost.Trim()
    }
    $baseUrl = "http://${DirectHost}:$TailscalePort"
    try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            $healthText = & $curl.Source --noproxy '*' --silent --show-error --fail "$baseUrl/api/health"
            if ($LASTEXITCODE -ne 0) {
                throw 'Tailnet health request failed.'
            }
            $health = $healthText | ConvertFrom-Json
            $pageStatus = & $curl.Source --noproxy '*' --silent --output NUL --write-out '%{http_code}' "$baseUrl/"
            if ($LASTEXITCODE -ne 0 -or $pageStatus -ne '200') {
                throw 'Tailnet H5 request failed.'
            }
        }
        else {
            $health = Invoke-RestMethod -Uri "$baseUrl/api/health" -NoProxy -TimeoutSec 8
            $page = Invoke-WebRequest -Uri "$baseUrl/" -UseBasicParsing -NoProxy -TimeoutSec 8
            if ($page.StatusCode -ne 200) {
                throw 'Tailnet H5 request failed.'
            }
        }
        if (-not $health.ok) {
            throw 'Tailnet health endpoint returned an invalid response.'
        }
        Write-Output "DIRECT_OK $baseUrl/api/health"
        Write-Output "DIRECT_OK $baseUrl/"
    }
    catch {
        Write-Output "DIRECT_UNAVAILABLE $baseUrl"
        Write-Output 'Use the SSH-hosted check above, or configure host firewall/Tailscale access for team browsers.'
        exit 2
    }
}
