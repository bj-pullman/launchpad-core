param(
    [string]$AppRoot = "",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [string]$BackupRoot = "C:\launchpad-backups",
    [string]$ServiceName = "Launchpad-private",
    [switch]$CheckOnly,
    [switch]$Apply,
    [switch]$NoRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $CheckOnly -and -not $Apply) {
    $CheckOnly = $true
}

if ([string]::IsNullOrWhiteSpace($AppRoot)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $AppRoot = Split-Path -Parent $ScriptDir
}

$AppRoot = (Resolve-Path $AppRoot).Path

$ProtectedFiles = @(
    ".env",
    "web.config",
    "wsgi.py",
    "service/Launchpad-private.exe",
    "service/Launchpad-private.xml",
    "service/launchpad-private.xml",
    "modules/core/app_factory.py"
)

function Invoke-Git {
    param([string[]]$Arguments)

    Push-Location $AppRoot
    try {
        $stdoutFile = [System.IO.Path]::GetTempFileName()
        $stderrFile = [System.IO.Path]::GetTempFileName()

        try {
            $process = Start-Process `
                -FilePath "git" `
                -ArgumentList $Arguments `
                -WorkingDirectory $AppRoot `
                -NoNewWindow `
                -Wait `
                -PassThru `
                -RedirectStandardOutput $stdoutFile `
                -RedirectStandardError $stderrFile

            $stdout = Get-Content $stdoutFile -Raw
            $stderr = Get-Content $stderrFile -Raw

            if ($process.ExitCode -ne 0) {
                throw "git $($Arguments -join ' ') failed: $stderr $stdout"
            }

            if ([string]::IsNullOrWhiteSpace($stdout)) {
                return @()
            }

            return $stdout -split "`r?`n" | Where-Object {
                -not [string]::IsNullOrWhiteSpace($_)
            }
        }
        finally {
            Remove-Item $stdoutFile -Force -ErrorAction SilentlyContinue
            Remove-Item $stderrFile -Force -ErrorAction SilentlyContinue
        }
    }
    finally {
        Pop-Location
    }
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $AppRoot
    )

    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()

    try {
        $process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory `
            -NoNewWindow `
            -Wait `
            -PassThru `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $stdout = Get-Content $stdoutFile -Raw
        $stderr = Get-Content $stderrFile -Raw

        if ($process.ExitCode -ne 0) {
            throw "$FilePath $($Arguments -join ' ') failed: $stderr $stdout"
        }

        return ($stdout + $stderr).Trim()
    }
    finally {
        Remove-Item $stdoutFile -Force -ErrorAction SilentlyContinue
        Remove-Item $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-UpdateStatus {
    $result = [ordered]@{
        ok = $true
        app_root = $AppRoot
        remote = $Remote
        branch = $Branch
        current_branch = ""
        current_commit = ""
        remote_commit = ""
        update_available = $false
        working_tree_dirty = $false
        dirty_files = @()
        protected_files_changed = @()
        changed_files = @()
        commits = @()
        error = $null
    }

    try {
        $result.current_branch = (Invoke-Git @("rev-parse", "--abbrev-ref", "HEAD")) -join ""
        $result.current_commit = (Invoke-Git @("rev-parse", "HEAD")) -join ""

        Invoke-Git @("fetch", $Remote, $Branch) | Out-Null

        $remoteRef = "$Remote/$Branch"
        $result.remote_commit = (Invoke-Git @("rev-parse", $remoteRef)) -join ""

        $status = Invoke-Git @("status", "--porcelain")
        foreach ($line in $status) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $result.dirty_files += $line
            }
        }

        $result.working_tree_dirty = ($result.dirty_files.Count -gt 0)

        $changed = Invoke-Git @("diff", "--name-status", "HEAD..$remoteRef")
        foreach ($line in $changed) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $result.changed_files += $line

                foreach ($protected in $ProtectedFiles) {
                    if ($line -like "*$protected") {
                        $result.protected_files_changed += $line
                    }
                }
            }
        }

        $commits = Invoke-Git @("log", "--oneline", "HEAD..$remoteRef")
        foreach ($commit in $commits) {
            if (-not [string]::IsNullOrWhiteSpace($commit)) {
                $result.commits += $commit
            }
        }

        $result.update_available = ($result.current_commit -ne $result.remote_commit)
    }
    catch {
        $result.ok = $false
        $result.error = $_.Exception.Message
    }

    return $result
}

function Invoke-Backup {
    $backupScript = Join-Path $AppRoot "scripts\production_backup.ps1"

    if (-not (Test-Path $backupScript)) {
        throw "Backup script not found: $backupScript"
    }

    $output = Invoke-External `
        -FilePath "powershell.exe" `
        -Arguments @(
            "-ExecutionPolicy", "Bypass",
            "-File", $backupScript,
            "-AppRoot", $AppRoot,
            "-BackupRoot", $BackupRoot,
            "-Reason", "pre-update"
        )

    try {
        return $output | ConvertFrom-Json
    }
    catch {
        throw "Backup completed but did not return valid JSON: $output"
    }
}

function Restore-ProtectedFilesFromHead {
    foreach ($file in $ProtectedFiles) {
        Push-Location $AppRoot
        try {
            $existsInHead = $true

            & git cat-file -e "HEAD:$file" 2>$null
            if ($LASTEXITCODE -ne 0) {
                $existsInHead = $false
            }

            if ($existsInHead) {
                & git restore --staged -- $file 2>$null
                & git restore --source=HEAD -- $file 2>$null
            }
        }
        finally {
            Pop-Location
        }
    }
}

function Install-Requirements {
    $requirements = Join-Path $AppRoot "requirements.txt"
    $pip = Join-Path $AppRoot "venv\Scripts\pip.exe"

    if (-not (Test-Path $requirements)) {
        return "requirements.txt not found; skipped."
    }

    if (-not (Test-Path $pip)) {
        throw "pip not found at $pip"
    }

    return Invoke-External `
        -FilePath $pip `
        -Arguments @("install", "-r", $requirements)
}

function Restart-AppService {
    if ($NoRestart) {
        return "Restart skipped by -NoRestart."
    }

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

    if ($null -eq $service) {
        return "Service '$ServiceName' not found; restart skipped."
    }

    Restart-Service -Name $ServiceName -Force
    return "Service '$ServiceName' restarted."
}

function Apply-Update {
    $summary = [ordered]@{
        ok = $true
        app_root = $AppRoot
        remote = $Remote
        branch = $Branch
        backup = $null
        stash_created = $false
        merge_commit = ""
        requirements = ""
        restart = ""
        status_before = $null
        status_after = $null
        error = $null
    }

    try {
        $statusBefore = Get-UpdateStatus
        $summary.status_before = $statusBefore

        if (-not $statusBefore.ok) {
            throw $statusBefore.error
        }

        if (-not $statusBefore.update_available) {
            $summary.status_after = $statusBefore
            return $summary
        }

        $backup = Invoke-Backup
        $summary.backup = $backup

        if ($backup.ok -ne $true) {
            throw "Backup failed; update aborted."
        }

        if ($statusBefore.working_tree_dirty) {
            Invoke-Git @(
                "stash",
                "push",
                "-u",
                "-m",
                "Production local changes before automated update"
            ) | Out-Null

            $summary.stash_created = $true
        }

        $remoteRef = "$Remote/$Branch"

        Invoke-Git @("merge", "--no-commit", "--no-ff", $remoteRef) | Out-Null

        Restore-ProtectedFilesFromHead

        $mergeStatus = Invoke-Git @("status", "--porcelain")
        $conflicts = $mergeStatus | Where-Object {
            $_ -match "^(UU|AA|DD|DU|UD|AU|UA)"
        }

        if ($conflicts.Count -gt 0) {
            throw "Merge conflicts detected: $($conflicts -join '; ')"
        }

        Invoke-Git @(
            "commit",
            "-m",
            "Automated production update from $Remote/$Branch"
        ) | Out-Null

        $summary.merge_commit = (Invoke-Git @("rev-parse", "HEAD")) -join ""

        $summary.requirements = Install-Requirements
        $summary.restart = Restart-AppService
        $summary.status_after = Get-UpdateStatus
    }
    catch {
        $summary.ok = $false
        $summary.error = $_.Exception.Message
    }

    return $summary
}

if ($CheckOnly) {
    Get-UpdateStatus | ConvertTo-Json -Depth 8
    exit
}

if ($Apply) {
    Apply-Update | ConvertTo-Json -Depth 10
    exit
}