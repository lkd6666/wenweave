[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Version = (Get-Date -Format 'yyyyMMdd-HHmmss'),
    [string]$OutputRoot = '',
    [string]$PythonExecutable = '',
    [string]$MySqlDumpPath = '',
    [string]$SevenZipPath = '',
    [string]$PrivateArchivePasswordEnvironmentVariable = '',
    [string]$LayoutCaptureAppOrigin = $env:LAYOUT_CAPTURE_APP_ORIGIN,
    [ValidatePattern('^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){0,3}$')]
    [string]$LayoutCaptureExtensionVersion = (Get-Date -Format 'yyyy.M.d.HHmm'),
    [switch]$SkipPrivateArchive
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $OutputRoot) {
    $OutputRoot = Join-Path (Split-Path -Parent $repoRoot) 'yibanpaiban-artifacts'
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

if ([string]::IsNullOrWhiteSpace($LayoutCaptureAppOrigin)) {
    throw 'A production HTTPS application origin is required. Pass -LayoutCaptureAppOrigin or set LAYOUT_CAPTURE_APP_ORIGIN.'
}
$layoutCaptureUri = $null
if (-not [Uri]::TryCreate($LayoutCaptureAppOrigin, [UriKind]::Absolute, [ref]$layoutCaptureUri) -or
    $layoutCaptureUri.Scheme -ne 'https' -or
    $layoutCaptureUri.GetLeftPart([UriPartial]::Authority).TrimEnd('/') -ne $LayoutCaptureAppOrigin.TrimEnd('/')) {
    throw 'LayoutCaptureAppOrigin must be an HTTPS origin without a path, query, or fragment.'
}
foreach ($versionPart in $LayoutCaptureExtensionVersion.Split('.')) {
    if ([int]$versionPart -gt 65535) {
        throw 'Each LayoutCaptureExtensionVersion component must be at most 65535.'
    }
}

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

function Write-DirectorySha256 {
    param([string]$Directory)
    $root = [System.IO.Path]::GetFullPath($Directory).TrimEnd([char[]]@('\', '/'))
    $lines = Get-ChildItem -LiteralPath $root -Recurse -Force -File |
        Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
        Sort-Object FullName |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($root.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
            $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            "$hash  $relativePath"
        }
    Set-Content -LiteralPath (Join-Path $root 'SHA256SUMS.txt') -Value $lines -Encoding ascii
}

function Remove-ExistingPath {
    param([string]$Path, [switch]$Recurse)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse:$Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $Path) {
        throw "Unable to remove existing temporary path: $Path"
    }
}

function Remove-TemporaryPath {
    param([string]$Path, [switch]$Recurse)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        Remove-ExistingPath -Path $Path -Recurse:$Recurse
    }
    catch {
        Write-Warning "Temporary path could not be removed; delete it manually: $Path"
    }
}

function Move-FileIntoPlace {
    param([string]$Source, [string]$Destination)
    if (Test-Path -LiteralPath $Destination) {
        # Replace preserves the existing artifact until the replacement is complete.
        $backupPath = "$Destination.replace-backup"
        Remove-ExistingPath -Path $backupPath
        try {
            [System.IO.File]::Replace($Source, $Destination, $backupPath)
        }
        finally {
            Remove-TemporaryPath -Path $backupPath
        }
    }
    else {
        [System.IO.File]::Move($Source, $Destination)
    }
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
$extensionPackageDir = Join-Path $outputVersionDir "layout-capture-extension-$Version"
$extensionArchive = Join-Path $outputVersionDir "layout-capture-extension-enterprise-$Version.zip"
$releaseZipCandidate = "$releaseZip.new"
$privateArchiveCandidate = "$privateArchive.new"
$extensionArchiveCandidate = "$extensionArchive.new"

New-Item -ItemType Directory -Force -Path $outputVersionDir | Out-Null
foreach ($stage in @($releaseStage, $privateStage)) {
    Remove-ExistingPath -Path $stage -Recurse
}
Remove-ExistingPath -Path $extensionPackageDir -Recurse
foreach ($temporaryPath in @($sourceArchive, $releaseZipCandidate, $privateArchiveCandidate, $extensionArchiveCandidate)) {
    Remove-ExistingPath -Path $temporaryPath
}

Invoke-Checked -FilePath 'git' -Arguments @('-C', $repoRoot, 'archive', '--format=zip', "--output=$sourceArchive", $commit)
Expand-Archive -LiteralPath $sourceArchive -DestinationPath $releaseStage -Force

$releaseFrontendDir = Join-Path $releaseStage 'frontend'
Invoke-Checked -FilePath 'npm.cmd' -Arguments @('--prefix', $releaseFrontendDir, 'ci')
$previousCaptureOrigin = [Environment]::GetEnvironmentVariable('LAYOUT_CAPTURE_APP_ORIGIN', 'Process')
$previousCaptureMode = [Environment]::GetEnvironmentVariable('LAYOUT_CAPTURE_BUILD_MODE', 'Process')
$previousCaptureVersion = [Environment]::GetEnvironmentVariable('LAYOUT_CAPTURE_EXTENSION_VERSION', 'Process')
try {
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_APP_ORIGIN', $LayoutCaptureAppOrigin.TrimEnd('/'), 'Process')
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_BUILD_MODE', 'production', 'Process')
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_EXTENSION_VERSION', $LayoutCaptureExtensionVersion, 'Process')
    Invoke-Checked -FilePath 'npm.cmd' -Arguments @('--prefix', $releaseFrontendDir, 'run', 'build:layout-capture-extension')
}
finally {
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_APP_ORIGIN', $previousCaptureOrigin, 'Process')
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_BUILD_MODE', $previousCaptureMode, 'Process')
    [Environment]::SetEnvironmentVariable('LAYOUT_CAPTURE_EXTENSION_VERSION', $previousCaptureVersion, 'Process')
}
Invoke-Checked -FilePath 'npm.cmd' -Arguments @('--prefix', $releaseFrontendDir, 'run', 'build')
$extensionBuildDir = Join-Path $releaseFrontendDir 'extension-dist'
if (-not (Test-Path -LiteralPath (Join-Path $extensionBuildDir 'manifest.json'))) {
    throw 'Layout capture extension build did not produce manifest.json.'
}
$extensionDownloadMetadata = Join-Path $releaseFrontendDir 'dist\downloads\layout-capture-extension.json'
if (-not (Test-Path -LiteralPath $extensionDownloadMetadata)) {
    throw 'Frontend build did not include the layout capture extension download metadata.'
}
$extensionDownloadFileName = (Get-Content -Raw -LiteralPath $extensionDownloadMetadata | ConvertFrom-Json).file_name
if (-not $extensionDownloadFileName -or [System.IO.Path]::GetFileName($extensionDownloadFileName) -ne $extensionDownloadFileName) {
    throw 'Layout capture extension download metadata contains an invalid file name.'
}
$extensionWebDownload = Join-Path $releaseFrontendDir "dist\downloads\$extensionDownloadFileName"
if (-not (Test-Path -LiteralPath $extensionWebDownload)) {
    throw 'Frontend build did not include the layout capture extension download.'
}
Copy-Item -LiteralPath $extensionBuildDir -Destination $extensionPackageDir -Recurse -Force
Write-DirectorySha256 -Directory $extensionPackageDir
New-PortableZip -SourceDirectory $extensionPackageDir -DestinationFile $extensionArchiveCandidate
Move-FileIntoPlace -Source $extensionArchiveCandidate -Destination $extensionArchive
Write-Sha256 -FilePath $extensionArchive
Remove-Item -LiteralPath $extensionBuildDir -Recurse -Force
Remove-Item -LiteralPath (Join-Path $releaseFrontendDir 'node_modules') -Recurse -Force

Invoke-Checked -FilePath $PythonExecutable -Arguments @('scripts/export_mysql_schema.py', '--output', (Join-Path $releaseStage 'deploy\mysql-schema.sql')) -WorkingDirectory (Join-Path $repoRoot 'backend')
Set-Content -LiteralPath (Join-Path $releaseStage 'RELEASE_MANIFEST.txt') -Encoding ascii -Value @(
    "commit=$commit",
    "version=$Version",
    'frontend=prebuilt',
    "layout-capture-extension=$LayoutCaptureExtensionVersion ($($LayoutCaptureAppOrigin.TrimEnd('/')))",
    'database=mysql-schema-only',
    'private-runtime-data=excluded'
)
if ($LayoutCaptureAppOrigin.TrimEnd('/') -match '^https://(www\.)?example\.com$') {
    Set-Content -LiteralPath (Join-Path $releaseStage 'DEPLOYER_ACTION_REQUIRED.txt') -Encoding utf8 -Value @"
必须操作：替换排版采集扩展的占位来源

此发行包中的排版采集扩展当前仅允许与 $($LayoutCaptureAppOrigin.TrimEnd('/')) 通信。这只是占位来源，不能用于真实部署。

在将系统提供给实际用户之前，请在发行源代码目录使用真实的 HTTPS 站点来源重新执行打包：

  .\scripts\package-release.ps1 -Version <新版本号> -LayoutCaptureAppOrigin 'https://你的实际域名' -SkipPrivateArchive

真实来源必须只包含协议和域名（可含端口），不能包含路径、查询参数或片段。例如：https://editor.example.cn。

仅修改 backend/.env 中的 CORS_ORIGINS、Nginx 配置或已解压文件，均不会修改已经编译并安装的浏览器扩展白名单；必须重新构建并让用户重新安装新扩展包。
"@
}
Assert-PublicStageSafe -Stage $releaseStage
New-PortableZip -SourceDirectory $releaseStage -DestinationFile $releaseZipCandidate
Move-FileIntoPlace -Source $releaseZipCandidate -Destination $releaseZip
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

    try {
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
            Invoke-Checked -FilePath $SevenZipPath -Arguments @('a', '-t7z', $privateArchiveCandidate, (Join-Path $privateStage '*'), '-mhe=on', "-p$password") -WorkingDirectory $outputVersionDir
            Invoke-Checked -FilePath $SevenZipPath -Arguments @('t', $privateArchiveCandidate, "-p$password") -WorkingDirectory $outputVersionDir
        }
        finally {
            Remove-Variable password -ErrorAction SilentlyContinue
        }
        Move-FileIntoPlace -Source $privateArchiveCandidate -Destination $privateArchive
        Write-Sha256 -FilePath $privateArchive
    }
    finally {
        Remove-TemporaryPath -Path $privateStage -Recurse
        Remove-TemporaryPath -Path $privateArchiveCandidate
    }
}

Remove-TemporaryPath -Path $releaseStage -Recurse
Remove-TemporaryPath -Path $sourceArchive
Remove-TemporaryPath -Path $releaseZipCandidate
Remove-TemporaryPath -Path $extensionArchiveCandidate
Write-Host "Release package: $releaseZip"
Write-Host "Release checksum: $releaseZip.sha256"
Write-Host "Layout capture extension directory: $extensionPackageDir"
Write-Host "Layout capture extension package: $extensionArchive"
Write-Host "Layout capture extension checksum: $extensionArchive.sha256"
if (-not $SkipPrivateArchive) {
    Write-Host "Private archive: $privateArchive"
    Write-Host "Private checksum: $privateArchive.sha256"
}
