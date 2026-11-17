[CmdletBinding()]
param(
    [string]$BluePcHost = 'bluepc',
    [int]$Port = 18765,
    [string]$TaskName = 'GoalOfOurs-MVP',
    [switch]$RestoreLatestDatabase
)

$ErrorActionPreference = 'Stop'

$restoreValue = if ($RestoreLatestDatabase) { '$true' } else { '$false' }
$script = @"
`$ErrorActionPreference = 'Stop'
& 'C:\GoalOfOurs\ops\rollback.ps1' -Port $Port -TaskName '$TaskName' -RestoreLatestDatabase:$restoreValue
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))

& ssh $BluePcHost powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded
if ($LASTEXITCODE -ne 0) {
    throw "Rollback failed with exit code $LASTEXITCODE."
}
