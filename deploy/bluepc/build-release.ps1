[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\dist\bluepc'),
    [string]$Commit = 'HEAD'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

Push-Location $repoRoot
try {
    & git rev-parse --verify "$Commit^{commit}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Git revision not found: $Commit"
    }

    $fullSha = (& git rev-parse "$Commit^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $fullSha) {
        throw "Could not resolve Git revision: $Commit"
    }
    $shortSha = $fullSha.Substring(0, 12)

    $dirty = & git status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect the Git work tree.'
    }
    if ($dirty) {
        throw 'Tracked files are modified. Commit the release before building.'
    }

    $outputFull = [IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Path $outputFull -Force | Out-Null

    $zipName = "goal-of-ours-mvp-$shortSha.zip"
    $zipPath = Join-Path $outputFull $zipName
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    & git archive --format=zip "--output=$zipPath" $fullSha -- mvp
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $zipPath)) {
        throw 'git archive failed.'
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName })
    }
    finally {
        $archive.Dispose()
    }

    $required = @(
        'mvp/app.py',
        'mvp/schema.sql',
        'mvp/web/index.html'
    )
    foreach ($item in $required) {
        if ($entries -notcontains $item) {
            throw "Release archive is missing required file: $item"
        }
    }

    $forbidden = $entries | Where-Object {
        $_ -match '(^|/)(__pycache__|\.pytest_cache)(/|$)' -or
        $_ -match '\.(pyc|pyo|db|sqlite|sqlite3|log)$' -or
        $_ -match '(^|/)\.env($|\.)'
    }
    if ($forbidden) {
        throw "Release archive contains forbidden runtime files: $($forbidden -join ', ')"
    }

    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $file = Get-Item -LiteralPath $zipPath
    $manifest = [ordered]@{
        commit = $fullSha
        short_commit = $shortSha
        built_at = (Get-Date).ToUniversalTime().ToString('o')
        package = $zipName
        sha256 = $hash
        size_bytes = $file.Length
    }
    $manifestPath = Join-Path $outputFull "goal-of-ours-mvp-$shortSha.manifest.json"
    $manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8

    [pscustomobject]@{
        Commit = $fullSha
        ShortCommit = $shortSha
        PackagePath = $zipPath
        ManifestPath = $manifestPath
        Sha256 = $hash
        SizeBytes = $file.Length
    }
}
finally {
    Pop-Location
}
