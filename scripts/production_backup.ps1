param(
    [string]$AppRoot = "",
    [string]$BackupRoot = "C:\launchpad-backups",
    [string]$Reason = "manual",
    [switch]$IncludeAppSnapshot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $AppRoot = Split-Path -Parent $ScriptDir
}

$AppRoot = (Resolve-Path $AppRoot).Path

$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$ArchiveRoot = Join-Path $BackupRoot "archive"
$BackupPath = Join-Path $ArchiveRoot $Timestamp
$LatestPath = Join-Path $BackupRoot "latest"

$ProtectedFiles = @(
    ".env",
    "web.config",
    "wsgi.py",
    "service\Launchpad-private.xml",
    "service\launchpad-private.xml"
)

$DatabasePatterns = @(
    "*.db",
    "*.sqlite",
    "*.sqlite3"
)

function New-Folder {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Copy-IfExists {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (Test-Path $Source) {
        $destDir = Split-Path -Parent $Destination
        New-Folder $destDir
        Copy-Item -Path $Source -Destination $Destination -Force
        return $true
    }

    return $false
}

function Invoke-GitSafe {
    param([string[]]$Arguments)

    Push-Location $AppRoot
    try {
        $output = & git @Arguments 2>&1
        return ($output -join "`n")
    }
    catch {
        return $_.Exception.Message
    }
    finally {
        Pop-Location
    }
}

New-Folder $BackupRoot
New-Folder $ArchiveRoot
New-Folder $BackupPath

$Metadata = [ordered]@{
    ok = $true
    reason = $Reason
    timestamp = $Timestamp
    app_root = $AppRoot
    backup_root = $BackupRoot
    backup_path = $BackupPath
    include_app_snapshot = [bool]$IncludeAppSnapshot
    protected_files = @()
    databases = @()
    app_snapshot = $null
    git = [ordered]@{
        branch = ""
        commit = ""
        status = ""
        remotes = ""
    }
    errors = @()
}

try {
    $Metadata.git.branch = Invoke-GitSafe @("rev-parse", "--abbrev-ref", "HEAD")
    $Metadata.git.commit = Invoke-GitSafe @("rev-parse", "HEAD")
    $Metadata.git.status = Invoke-GitSafe @("status", "--short")
    $Metadata.git.remotes = Invoke-GitSafe @("remote", "-v")

    # Git metadata files
    $GitDir = Join-Path $BackupPath "git"
    New-Folder $GitDir

    $Metadata.git.branch | Out-File -FilePath (Join-Path $GitDir "branch.txt") -Encoding UTF8
    $Metadata.git.commit | Out-File -FilePath (Join-Path $GitDir "commit.txt") -Encoding UTF8
    $Metadata.git.status | Out-File -FilePath (Join-Path $GitDir "status.txt") -Encoding UTF8
    $Metadata.git.remotes | Out-File -FilePath (Join-Path $GitDir "remotes.txt") -Encoding UTF8

    # Protected/config/service files
    foreach ($relative in $ProtectedFiles) {
        $source = Join-Path $AppRoot $relative
        $destination = Join-Path (Join-Path $BackupPath "protected") $relative

        if (Copy-IfExists -Source $source -Destination $destination) {
            $Metadata.protected_files += $relative
        }
    }

    # Database files
    $DatabaseDir = Join-Path $BackupPath "databases"
    New-Folder $DatabaseDir

    foreach ($pattern in $DatabasePatterns) {
        $matches = Get-ChildItem -Path $AppRoot -Recurse -File -Filter $pattern -ErrorAction SilentlyContinue |
            Where-Object {
                $_.FullName -notmatch "\\.git\\" -and
                $_.FullName -notmatch "\\venv\\" -and
                $_.FullName -notmatch "\\__pycache__\\"
            }

        foreach ($file in $matches) {
            $relativePath = $file.FullName.Substring($AppRoot.Length).TrimStart("\", "/")
            $destination = Join-Path $DatabaseDir $relativePath

            if (Copy-IfExists -Source $file.FullName -Destination $destination) {
                $Metadata.databases += $relativePath
            }
        }
    }

    # Optional full app snapshot, excluding noisy/heavy/runtime folders
    if ($IncludeAppSnapshot) {
        $SnapshotDir = Join-Path $BackupPath "app"
        New-Folder $SnapshotDir

        robocopy $AppRoot $SnapshotDir /E `
            /XD ".git" "venv" "__pycache__" ".pytest_cache" "node_modules" `
            /XF "*.pyc" "*.pyo" "*.log" "*.log.old" | Out-Null

        $robocopyCode = $LASTEXITCODE

        if ($robocopyCode -gt 7) {
            throw "Robocopy app snapshot failed with exit code $robocopyCode."
        }

        $Metadata.app_snapshot = $SnapshotDir
    }

    # Write metadata before latest copy
    $MetadataPath = Join-Path $BackupPath "metadata.json"
    $Metadata | ConvertTo-Json -Depth 8 | Out-File -FilePath $MetadataPath -Encoding UTF8

    # Refresh latest
    if (Test-Path $LatestPath) {
        Remove-Item $LatestPath -Recurse -Force
    }

    New-Folder $LatestPath

    robocopy $BackupPath $LatestPath /E | Out-Null
    $latestCopyCode = $LASTEXITCODE

    if ($latestCopyCode -gt 7) {
        throw "Robocopy latest backup copy failed with exit code $latestCopyCode."
    }
}
catch {
    $Metadata.ok = $false
    $Metadata.errors += $_.Exception.Message

    try {
        $Metadata | ConvertTo-Json -Depth 8 |
            Out-File -FilePath (Join-Path $BackupPath "metadata.json") -Encoding UTF8
    }
    catch {
        # Do not mask original error.
    }
}

$Metadata | ConvertTo-Json -Depth 8