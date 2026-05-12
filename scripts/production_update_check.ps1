param(
    [string]$AppRoot = "",
    [string]$Remote = "origin",
    [string]$Branch = "main"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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
    $result.working_tree_dirty = ($status.Count -gt 0)

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

$result | ConvertTo-Json -Depth 6