param(
    [string]$AppRoot = "",
    [string]$BackupRoot = "C:\launchpad-backups",
    [string]$BackupPath = "",
    [switch]$RestoreDatabases,
    [switch]$RestoreProtectedFiles,
    [switch]$RestoreAppSnapshot,
    [switch]$RestartService,
    [string]$ServiceName = "Launchpad-private"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $AppRoot = Split-Path -Parent $ScriptDir
}

$AppRoot = (Resolve-Path $AppRoot).Path

if ([string]::IsNullOrWhiteSpace($BackupPath)) {
    $BackupPath = Join-Path $BackupRoot "latest"
}

if (-not (Test-Path $BackupPath)) {
    throw "Backup path does not exist: $BackupPath"
}

$MetadataPath = Join-Path $BackupPath "metadata.json"

$Result = [ordered]@{
    ok = $true
    app_root = $AppRoot
    backup_path = $BackupPath
    metadata_path = $MetadataPath
    restored_databases = @()
    restored_protected_files = @()
    restored_app_snapshot = $false
    restart = ""
    errors = @()
}

function Copy-TreeIfExists {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        return $false
    }

    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination | Out-Null
    }

    robocopy $Source $Destination /E | Out-Null
    $code = $LASTEXITCODE

    if ($code -gt 7) {
        throw "Robocopy failed from '$Source' to '$Destination' with exit code $code."
    }

    return $true
}

function Restart-AppService {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

    if ($null -eq $service) {
        return "Service '$ServiceName' not found; restart skipped."
    }

    Restart-Service -Name $ServiceName -Force
    return "Service '$ServiceName' restarted."
}

try {
    if ($RestoreProtectedFiles) {
        $ProtectedSource = Join-Path $BackupPath "protected"

        if (Test-Path $ProtectedSource) {
            Get-ChildItem -Path $ProtectedSource -Recurse -File | ForEach-Object {
                $relative = $_.FullName.Substring($ProtectedSource.Length).TrimStart("\", "/")
                $destination = Join-Path $AppRoot $relative
                $destinationDir = Split-Path -Parent $destination

                if (-not (Test-Path $destinationDir)) {
                    New-Item -ItemType Directory -Path $destinationDir | Out-Null
                }

                Copy-Item -Path $_.FullName -Destination $destination -Force
                $Result.restored_protected_files += $relative
            }
        }
    }

    if ($RestoreDatabases) {
        $DatabaseSource = Join-Path $BackupPath "databases"

        if (Test-Path $DatabaseSource) {
            Get-ChildItem -Path $DatabaseSource -Recurse -File | ForEach-Object {
                $relative = $_.FullName.Substring($DatabaseSource.Length).TrimStart("\", "/")
                $destination = Join-Path $AppRoot $relative
                $destinationDir = Split-Path -Parent $destination

                if (-not (Test-Path $destinationDir)) {
                    New-Item -ItemType Directory -Path $destinationDir | Out-Null
                }

                Copy-Item -Path $_.FullName -Destination $destination -Force
                $Result.restored_databases += $relative
            }
        }
    }

    if ($RestoreAppSnapshot) {
        $SnapshotSource = Join-Path $BackupPath "app"

        if (-not (Test-Path $SnapshotSource)) {
            throw "Backup does not contain an app snapshot. Run backup with -IncludeAppSnapshot first."
        }

        Copy-TreeIfExists -Source $SnapshotSource -Destination $AppRoot | Out-Null
        $Result.restored_app_snapshot = $true
    }

    if ($RestartService) {
        $Result.restart = Restart-AppService
    }
}
catch {
    $Result.ok = $false
    $Result.errors += $_.Exception.Message
}

$Result | ConvertTo-Json -Depth 8