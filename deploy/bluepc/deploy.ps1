[CmdletBinding()]
param(
    [string]$BluePcHost = 'bluepc',
    [int]$Port = 18765,
    [string]$RemoteRoot = 'C:\GoalOfOurs',
    [string]$TaskName = 'GoalOfOurs-MVP',
    [int]$TailscalePort = 18766,
    [switch]$SkipTailscaleServe,
    [ValidateSet('mock', 'opencode')]
    [string]$LlmMode = 'mock',
    [string]$ReleaseZip
)

$ErrorActionPreference = 'Stop'

function Assert-RemoteRoot {
    param([string]$Path)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if (-not $full.Equals('C:\GoalOfOurs', [StringComparison]::OrdinalIgnoreCase)) {
        throw "This deployment only permits RemoteRoot=C:\GoalOfOurs. Received: $full"
    }
    return $full
}

function Invoke-RemotePowerShell {
    param(
        [string]$HostName,
        [string]$Script
    )
    $encoded = [Convert]::ToBase64String(
        [Text.Encoding]::Unicode.GetBytes($Script)
    )
    & ssh $HostName powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded
    if ($LASTEXITCODE -ne 0) {
        throw "Remote PowerShell failed with exit code $LASTEXITCODE."
    }
}

$root = Assert-RemoteRoot $RemoteRoot
$effectiveTailscalePort = if ($SkipTailscaleServe) { 0 } else { $TailscalePort }
if ($effectiveTailscalePort -eq $Port) {
    throw 'TailscalePort must differ from the application Port.'
}

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw 'ssh was not found on the development machine.'
}
if (-not (Get-Command scp -ErrorAction SilentlyContinue)) {
    throw 'scp was not found on the development machine.'
}

if (-not $ReleaseZip) {
    $release = & (Join-Path $PSScriptRoot 'build-release.ps1')
}
else {
    $zipItem = Get-Item -LiteralPath $ReleaseZip
    $release = [pscustomobject]@{
        Commit = 'provided-package'
        ShortCommit = 'provided'
        PackagePath = $zipItem.FullName
        ManifestPath = $null
        Sha256 = (Get-FileHash -LiteralPath $zipItem.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        SizeBytes = $zipItem.Length
    }
}

$package = Get-Item -LiteralPath $release.PackagePath
$releaseId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + $release.ShortCommit
$remotePackage = Join-Path $root ('incoming\' + $package.Name)

$bootstrap = @"
`$ErrorActionPreference = 'Stop'
`$root = [IO.Path]::GetFullPath('$root')
if (-not `$root.Equals('C:\GoalOfOurs', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe deployment root: `$root"
}
foreach (`$relative in @('ops', 'incoming')) {
    `$path = [IO.Path]::GetFullPath((Join-Path `$root `$relative))
    if (-not `$path.StartsWith(`$root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path: `$path"
    }
    New-Item -ItemType Directory -Path `$path -Force | Out-Null
}
"@
Invoke-RemotePowerShell -HostName $BluePcHost -Script $bootstrap

$uploadFiles = @(
    @{ Local = (Join-Path $PSScriptRoot 'remote\deploy-release.ps1'); Remote = 'C:/GoalOfOurs/ops/deploy-release.ps1' },
    @{ Local = (Join-Path $PSScriptRoot 'remote\rollback.ps1'); Remote = 'C:/GoalOfOurs/ops/rollback.ps1' },
    @{ Local = (Join-Path $PSScriptRoot 'remote\healthcheck.ps1'); Remote = 'C:/GoalOfOurs/ops/healthcheck.ps1' },
    @{ Local = (Join-Path $PSScriptRoot 'remote\run-mvp.ps1'); Remote = 'C:/GoalOfOurs/ops/run-mvp.ps1' },
    @{ Local = (Join-Path $PSScriptRoot 'config\mvp.env.example'); Remote = 'C:/GoalOfOurs/ops/mvp.env.example' }
)
foreach ($file in $uploadFiles) {
    & scp -q $file.Local ("${BluePcHost}:" + $file.Remote)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload $($file.Local)."
    }
}

& scp -q $package.FullName ("${BluePcHost}:" + $remotePackage.Replace('\', '/'))
if ($LASTEXITCODE -ne 0) {
    throw 'Failed to upload the release package.'
}

$remoteDeploy = @"
`$ErrorActionPreference = 'Stop'
& '$root\ops\deploy-release.ps1' -PackageZip '$remotePackage' -ReleaseId '$releaseId' -Port $Port -TaskName '$TaskName' -LlmMode '$LlmMode' -TailscalePort $effectiveTailscalePort
if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }
"@
Invoke-RemotePowerShell -HostName $BluePcHost -Script $remoteDeploy

[pscustomobject]@{
    BluePcHost = $BluePcHost
    RemoteRoot = $root
    Port = $Port
    TaskName = $TaskName
    TailscalePort = $effectiveTailscalePort
    LlmMode = $LlmMode
    ReleaseId = $releaseId
    Commit = $release.Commit
    PackagePath = $package.FullName
    PackageSha256 = $release.Sha256
}
