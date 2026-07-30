[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Version = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string]$OutputRoot = '',
    [string]$PythonExecutable = '',
    [string]$MySqlDumpPath = '',
    [string]$SevenZipPath = '',
    [string]$PrivateArchivePasswordEnvironmentVariable = '',
    [switch]$SkipPrivateArchive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path (Split-Path -Parent $repoRoot) 'yibanpaiban-artifacts'
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory = $repoRoot)
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Find-CommandPath {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return ''
}

function Get-PlainTextPassword {
    $secure = Read-Host 'Private archive password' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($plain) -or $plain.Length -lt 12) {
            throw 'Private archive password must contain at least 12 characters.'
        }
        return $plain
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-ArchivePassword {
    param([string]$EnvironmentVariable)
    if ($EnvironmentVariable) {
        $value = [Environment]::GetEnvironmentVariable($EnvironmentVariable, 'Process')
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -lt 12) {
            throw "Environment variable $EnvironmentVariable must contain a password with at least 12 characters."
        }
        return $value
    }
    return Get-PlainTextPassword
}

function Copy-IfPresent {
    param([string]$Source, [string]$Destination)
    if (Test-Path -LiteralPath $Source) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
    }
}

function Assert-PublicStageSafe {
    param([string]$Stage)
    $forbidden = @(
        'backend/.env',
        'backend/data',
        'backend/uploads',
        '.git',
        '.claude',
        '.agents',
        'frontend/node_modules',
        'backend/venv',
        'backend/.venv'
    )
    foreach ($relativePath in $forbidden) {
        if (Test-Path -LiteralPath (Join-Path $Stage $relativePath)) {
            throw "Public release unexpectedly contains $relativePath"
        }
    }
    $secretFiles = Get-ChildItem -LiteralPath $Stage -Recurse -Force -File | Where-Object {
        $_.Name -eq '.env' -or $_.Name -eq 'encryption.key' -or $_.Extension -in @('.db', '.sqlite', '.sqlite3')
    }
    if ($secretFiles) {
        throw "Public release contains forbidden runtime file: $($secretFiles[0].FullName)"
    }
}

function Write-Sha256 {
    param([string]$FilePath)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $FilePath).Hash.ToLowerInvariant()
    $line = "$hash  $([System.IO.Path]::GetFileName($FilePath))"
    Set-Content -LiteralPath "$FilePath.sha256" -Value $line -Encoding ascii
}

function New-PortableZip {
    param([string]$SourceDirectory, [string]$DestinationFile)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $sourceRoot = [System.IO.Path]::GetFullPath($SourceDirectory).TrimEnd([char[]]@('\', '/'))
    $archive = [System.IO.Compression.ZipFile]::Open(
        $DestinationFile,
        [System.IO.Compression.ZipArchiveMode]::Create
    )
    try {
        Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force -File | ForEach-Object {
            $relativePath = $_.FullName.Substring($sourceRoot.Length).TrimStart([char[]]@('\', '/'))
            # ZIP entry names must use '/' so Linux unzip creates directories.
            $entryName = $relativePath.Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive,
                $_.FullName,
                $entryName,
                [System.IO.Compression.CompressionLevel]::Optimal
            ) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }
}

if (git -C $repoRoot status --porcelain) {
    throw 'Working tree is not clean. Commit the intended source before packaging.'
}

$commit = (git -C $repoRoot rev-parse HEAD).Trim()
if (-not $commit) { throw 'Unable to resolve the source commit.' }

if (-not $PythonExecutable) {
    $candidate = Join-Path $repoRoot 'backend\venv\Scripts\python.exe'
    $PythonExecutable = if (Test-Path -LiteralPath $candidate) { $candidate } else { Find-CommandPath 'python' }
}
if (-not $PythonExecutable -or -not (Test-Path -LiteralPath $PythonExecutable)) {
    throw 'A Python executable is required. Pass -PythonExecutable explicitly.'
}

$outputVersionDir = Join-Path $OutputRoot $Version
$releaseStage = Join-Path $outputVersionDir 'release-stage'
$privateStage = Join-Path $outputVersionDir 'private-stage'
$sourceArchive = Join-Path $outputVersionDir 'source.zip'
$releaseZip = Join-Path $outputVersionDir "yibanpaiban-release-$Version.zip"
$privateArchive = Join-Path $outputVersionDir "yibanpaiban-private-$Version.private.7z"

New-Item -ItemType Directory -Force -Path $outputVersionDir | Out-Null
foreach ($stage in @($releaseStage, $privateStage)) {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
Remove-Item -LiteralPath $sourceArchive, $releaseZip, $privateArchive -Force -ErrorAction SilentlyContinue

Invoke-Checked -FilePath 'git' -Arguments @('-C', $repoRoot, 'archive', '--format=zip', "--output=$sourceArchive", $commit)
Expand-Archive -LiteralPath $sourceArchive -DestinationPath $releaseStage -Force

$releaseFrontendDir = Join-Path $releaseStage 'frontend'
Invoke-Checked -FilePath 'npm.cmd' -Arguments @('--prefix', $releaseFrontendDir, 'ci')
Invoke-Checked -FilePath 'npm.cmd' -Arguments @('--prefix', $releaseFrontendDir, 'run', 'build')
Remove-Item -LiteralPath (Join-Path $releaseFrontendDir 'node_modules') -Recurse -Force

Invoke-Checked -FilePath $PythonExecutable -Arguments @('scripts/export_mysql_schema.py', '--output', (Join-Path $releaseStage 'deploy\mysql-schema.sql')) -WorkingDirectory (Join-Path $repoRoot 'backend')
Set-Content -LiteralPath (Join-Path $releaseStage 'RELEASE_MANIFEST.txt') -Encoding ascii -Value @(
    "commit=$commit",
    "version=$Version",
    'frontend=prebuilt',
    'database=mysql-schema-only',
    'private-runtime-data=excluded'
)
Assert-PublicStageSafe -Stage $releaseStage
New-PortableZip -SourceDirectory $releaseStage -DestinationFile $releaseZip
Write-Sha256 -FilePath $releaseZip

if (-not $SkipPrivateArchive) {
    if (-not $MySqlDumpPath) { $MySqlDumpPath = Find-CommandPath 'mysqldump' }
    if (-not $MySqlDumpPath -or -not (Test-Path -LiteralPath $MySqlDumpPath)) {
        throw 'mysqldump is required for the private archive. Pass -MySqlDumpPath explicitly.'
    }
    if (-not $SevenZipPath) { $SevenZipPath = Find-CommandPath '7z' }
    if (-not $SevenZipPath) { $SevenZipPath = Find-CommandPath '7za' }
    if (-not $SevenZipPath) { $SevenZipPath = Find-CommandPath '7zr' }
    if (-not $SevenZipPath) {
        $toolDir = Join-Path $OutputRoot '.tools'
        $SevenZipPath = Join-Path $toolDir '7zr.exe'
        if (-not (Test-Path -LiteralPath $SevenZipPath)) {
            New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
            Invoke-WebRequest -Uri 'https://www.7-zip.org/a/7zr.exe' -OutFile $SevenZipPath
        }
    }

    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $privateStage -Force
    Copy-IfPresent -Source (Join-Path $repoRoot 'backend\.env') -Destination (Join-Path $privateStage 'backend\.env')
    Copy-IfPresent -Source (Join-Path $repoRoot 'backend\data') -Destination (Join-Path $privateStage 'backend\data')
    Copy-IfPresent -Source (Join-Path $repoRoot 'backend\uploads') -Destination (Join-Path $privateStage 'backend\uploads')
    Invoke-Checked -FilePath $PythonExecutable -Arguments @('scripts/backup_personal_mysql.py', '--mysqldump', $MySqlDumpPath, '--output', (Join-Path $privateStage 'private\mysql-full.sql')) -WorkingDirectory (Join-Path $repoRoot 'backend')
    Set-Content -LiteralPath (Join-Path $privateStage 'PRIVATE_BACKUP_MANIFEST.txt') -Encoding ascii -Value @(
        "commit=$commit",
        "version=$Version",
        'database=full-mysqldump',
        'runtime=backend/.env,backend/data,backend/uploads',
        'warning=contains-secrets-and-personal-data'
    )

    $password = Get-ArchivePassword -EnvironmentVariable $PrivateArchivePasswordEnvironmentVariable
    try {
        Invoke-Checked -FilePath $SevenZipPath -Arguments @('a', '-t7z', $privateArchive, (Join-Path $privateStage '*'), '-mhe=on', "-p$password") -WorkingDirectory $outputVersionDir
        Invoke-Checked -FilePath $SevenZipPath -Arguments @('t', $privateArchive, "-p$password") -WorkingDirectory $outputVersionDir
    }
    finally {
        Remove-Variable password -ErrorAction SilentlyContinue
    }
    Write-Sha256 -FilePath $privateArchive
}

Remove-Item -LiteralPath $releaseStage, $privateStage, $sourceArchive -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Release package: $releaseZip"
Write-Host "Release checksum: $releaseZip.sha256"
if (-not $SkipPrivateArchive) {
    Write-Host "Private archive: $privateArchive"
    Write-Host "Private checksum: $privateArchive.sha256"
}
