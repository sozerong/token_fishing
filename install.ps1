<#
    token fishing - install / update / uninstall (Windows)

        powershell -ExecutionPolicy Bypass -File install.ps1
        powershell -ExecutionPolicy Bypass -File install.ps1 update
        powershell -ExecutionPolicy Bypass -File install.ps1 uninstall

    Do NOT run this from an elevated ("Run as administrator") prompt. Everything
    this tool touches lives in your own profile (~\.claude). Installing as another
    user would register the statusline hook in that user's profile instead of
    yours, and the tool would never find your usage data.
#>

param(
    [ValidateSet('install', 'update', 'uninstall')]
    [string]$Action = 'install'
)

$ErrorActionPreference = 'Stop'
$Package = 'token-fishing'
$Command = 'tokenfishing'
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Write-Bold($text) { Write-Host $text -ForegroundColor Cyan }
function Write-Info($text) { Write-Host "  $text" }
function Write-Warn($text) { Write-Host "  ! $text" -ForegroundColor Yellow }
function Write-Fail($text) { Write-Host "  x $text" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- sanity checks

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail @'
Do not run this as administrator. It installs into your own user profile.
     Close this window and run it again from a normal PowerShell prompt.
'@
}

function Find-Python {
    foreach ($candidate in @('py -3.13', 'py -3.12', 'py -3.11', 'python')) {
        $parts = $candidate.Split(' ')
        $exe = $parts[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $args = @()
        if ($parts.Count -gt 1) { $args += $parts[1] }
        $args += @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)')
        & $exe @args 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$PythonCmd = Find-Python
if (-not $PythonCmd) {
    Write-Fail @'
Python 3.11 or newer is required but was not found.
     Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
'@
}

function Invoke-Python {
    param([string[]]$Arguments)
    $parts = $PythonCmd.Split(' ')
    $exe = $parts[0]
    $all = @()
    if ($parts.Count -gt 1) { $all += $parts[1] }
    $all += $Arguments
    & $exe @all
}

function Test-OnPath {
    if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
    Write-Warn "$Command is installed but not on your PATH yet."
    $scripts = Invoke-Python @('-c', 'import site, os; print(os.path.join(site.USER_BASE, "Scripts"))')
    Write-Info 'Add it for this session:'
    Write-Info "    `$env:PATH += `";$scripts`""
    Write-Info 'Or permanently, then open a new terminal:'
    Write-Info "    setx PATH `"`$env:PATH;$scripts`""
}

# ------------------------------------------------------------------- operations

function Invoke-Install {
    Write-Bold 'Installing token fishing'

    Invoke-Python @('-c', 'import tkinter') 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'tkinter is missing - reinstall Python with the "tcl/tk" option enabled.'
    }

    if (Get-Command pipx -ErrorAction SilentlyContinue) {
        Write-Info 'using pipx (isolated environment)'
        pipx install --force $RepoDir | Out-Null
    } else {
        Write-Info 'using pip --user (install pipx for an isolated environment)'
        Invoke-Python @('-m', 'pip', 'install', '--user', '--upgrade', $RepoDir) | Out-Null
    }

    # The hook stores an absolute path to the installed file, so it has to be
    # re-registered after every install - the path changes when the venv does.
    Write-Bold 'Registering the Claude Code statusline hook'
    if (Get-Command $Command -ErrorAction SilentlyContinue) {
        & $Command --install-statusline
    } else {
        Invoke-Python @('-m', 'ccpet', '--install-statusline')
    }

    Write-Bold 'Done'
    Test-OnPath
    Write-Info "Run it with:            $Command"
    Write-Info "Pet screen:             $Command --animal"
    Write-Info "Keep your shell free:   $Command -d"
}

function Invoke-Update {
    Write-Bold 'Updating token fishing'
    if (Test-Path (Join-Path $RepoDir '.git')) {
        git -C $RepoDir pull --ff-only
    } else {
        Write-Warn 'not a git checkout - reinstalling the current source instead'
    }
    Invoke-Install
}

function Invoke-Uninstall {
    Write-Bold 'Removing token fishing'

    # Unregister first: the command disappears with the package, and a stale
    # statusLine entry would leave Claude Code running a file that is gone.
    if (Get-Command $Command -ErrorAction SilentlyContinue) {
        & $Command --uninstall-statusline
    } else {
        Invoke-Python @('-m', 'ccpet', '--uninstall-statusline') 2>$null
    }

    if ((Get-Command pipx -ErrorAction SilentlyContinue) -and (pipx list 2>$null | Select-String $Package)) {
        pipx uninstall $Package | Out-Null
    } else {
        Invoke-Python @('-m', 'pip', 'uninstall', '-y', $Package) 2>$null | Out-Null
    }

    Write-Bold 'Done'
    Write-Info 'Your Claude Code transcripts in ~\.claude\projects were not touched.'
}

switch ($Action) {
    'install'   { Invoke-Install }
    'update'    { Invoke-Update }
    'uninstall' { Invoke-Uninstall }
}
