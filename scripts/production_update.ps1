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
    "modules/core/app_factory.py",
    "service/Launchpad-private.exe",
    "service/Launchpad-private.xml",
    "service/launchpad-private.xml"
)

$ProtectedPatterns = @(
    "service/*.xml",
    "service/*.exe",
    "service/*.config",
    "service/*.ps1",
    "service/*.bat",
    "service/*.cmd"
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

function Get-RepoFileText {
    param(
        [string]$Ref,
        [string]$Path
    )

    try {
        $content = Invoke-Git @("show", "$Ref`:$Path")
        if ($content.Count -eq 0) {
            return ""
        }

        return ($content -join "`n")
    }
    catch {
        return ""
    }
}

function Get-FriendlyVersion {
    param([string]$Ref)

    try {
        $manifestText = Get-RepoFileText -Ref $Ref -Path "release_manifest.json"
        $versionBase = "1.3"

        if (-not [string]::IsNullOrWhiteSpace($manifestText)) {
            try {
                $manifest = $manifestText | ConvertFrom-Json
                if ($manifest.version_base) {
                    $versionBase = [string]$manifest.version_base
                }
            }
            catch {
                $versionBase = "1.3"
            }
        }

        $commitCount = (Invoke-Git @("rev-list", "--count", $Ref)) -join ""
        $shortHash = (Invoke-Git @("rev-parse", "--short=4", $Ref)) -join ""

        $hashNumber = 0
        foreach ($char in $shortHash.ToCharArray()) {
            $hashNumber += [int][char]$char
        }

        return "Version $versionBase.$commitCount.$hashNumber"
    }
    catch {
        return "Version unknown"
    }
}

function Get-ReleaseManifest {
    param([string]$Ref)

    $default = [ordered]@{
        version_base = "1.3"
        title = "Launchpad Update"
        summary = ""
        release_notes_path = "release_notes/latest.md"
        requires_restart = $true
        requires_backup = $true
        high_risk = $false
        manual_steps_required = $false
        manual_steps = @()
        expected_downtime = "Usually less than one minute while the app service restarts."
        what_to_expect = @(
            "A backup is generated automatically before applying the update.",
            "The Launchpad service may restart during the update.",
            "Protected hosting files are not overwritten automatically."
        )
    }

    $manifestText = Get-RepoFileText -Ref $Ref -Path "release_manifest.json"

    if ([string]::IsNullOrWhiteSpace($manifestText)) {
        return $default
    }

    try {
        $manifest = $manifestText | ConvertFrom-Json

        foreach ($property in $manifest.PSObject.Properties) {
            $default[$property.Name] = $property.Value
        }

        return $default
    }
    catch {
        return $default
    }
}

function Get-ReleaseNotesUrl {
    param(
        [string]$ManifestPath
    )

    if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
        $ManifestPath = "release_notes/latest.md"
    }

    return "https://github.com/bj-pullman/launchpad-private/blob/$Branch/$ManifestPath"
}

function Get-UpdateStatus {
    $result = [ordered]@{
        ok = $true
        branch = $Branch
        remote = $Remote

        current_commit = ""
        remote_commit = ""

        current_version = ""
        remote_version = ""

        update_available = $false
        working_tree_dirty = $false

        release_manifest = $null
        release_notes_url = ""

        commits = @()
        changed_files = @()
        protected_files_changed = @()

        errors = @()
    }

    try {
        Invoke-Git @("fetch", $Remote, $Branch, "--prune") | Out-Null

        $remoteRef = "$Remote/$Branch"

        $result.current_commit = (Invoke-Git @("rev-parse", "HEAD")) -join ""
        $result.remote_commit = (Invoke-Git @("rev-parse", $remoteRef)) -join ""

        $result.current_version = Get-FriendlyVersion "HEAD"
        $result.remote_version = Get-FriendlyVersion $remoteRef

        $manifest = Get-ReleaseManifest $remoteRef
        $result.release_manifest = $manifest
        $result.release_notes_url = Get-ReleaseNotesUrl $manifest.release_notes_path

        $statusOutput = Invoke-Git @("status", "--porcelain")
        if ($statusOutput.Count -gt 0) {
            $result.working_tree_dirty = $true
        }

        if ($result.current_commit -ne $result.remote_commit) {
            $result.update_available = $true

            $commitLines = Invoke-Git @("log", "--oneline", "HEAD..$remoteRef")
            foreach ($line in $commitLines) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    $result.commits += $line.Trim()
                }
            }

            $changedFiles = Invoke-Git @("diff", "--name-status", "HEAD..$remoteRef")
            foreach ($line in $changedFiles) {
                if ([string]::IsNullOrWhiteSpace($line)) {
                    continue
                }

                $trimmed = $line.Trim()
                $result.changed_files += $trimmed

                $changedPath = ($trimmed -split "\s+", 2)[-1].Trim()

                foreach ($protected in $ProtectedFiles) {
                    if ($changedPath -ieq $protected) {
                        $result.protected_files_changed += $trimmed
                    }
                }

                foreach ($pattern in $ProtectedPatterns) {
                    if ($changedPath -like $pattern) {
                        $result.protected_files_changed += $trimmed
                    }
                }
            }
        }

        $result.commits = @($result.commits | Select-Object -Unique)
        $result.changed_files = @($result.changed_files | Select-Object -Unique)
        $result.protected_files_changed = @($result.protected_files_changed | Select-Object -Unique)
    }
    catch {
        $result.ok = $false
        $result.errors += $_.Exception.Message
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
    $filesToRestore = @()

    foreach ($file in $ProtectedFiles) {
        $filesToRestore += $file
    }

    $changedFiles = Invoke-Git @("diff", "--name-only", "--cached")

    foreach ($changedFile in $changedFiles) {
        foreach ($pattern in $ProtectedPatterns) {
            if ($changedFile -like $pattern) {
                $filesToRestore += $changedFile
            }
        }
    }

    $filesToRestore = @($filesToRestore | Sort-Object -Unique)

    foreach ($file in $filesToRestore) {
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
            throw ($statusBefore.errors -join "; ")
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
    Get-UpdateStatus | ConvertTo-Json -Depth 12
    exit
}

if ($Apply) {
    Apply-Update | ConvertTo-Json -Depth 12
    exit
}