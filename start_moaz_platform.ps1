$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$Host.UI.RawUI.WindowTitle = "Moaz PMM Research Platform"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Moaz PMM Visual Analytics Platform" -ForegroundColor Cyan
Write-Host "  Local automatic Excel mode" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
if ([string]::IsNullOrWhiteSpace($env:PMM_DATA_DIR)) {
    Write-Host "Research database folder: using the application's built-in Windows default." -ForegroundColor Gray
} else {
    Write-Host "Research database folder override:" -ForegroundColor Gray
    Write-Host "  $env:PMM_DATA_DIR" -ForegroundColor White
    if (Test-Path -LiteralPath $env:PMM_DATA_DIR -PathType Container) {
        Write-Host "[OK] PMM_DATA_DIR is accessible." -ForegroundColor Green
    } else {
        Write-Warning "PMM_DATA_DIR is not currently accessible."
        Write-Host "The platform will still start; its built-in fallback/manual upload remains available." -ForegroundColor Yellow
    }
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $RepoRoot "requirements.txt"
$RequirementsMarker = Join-Path $RepoRoot ".venv\requirements.sha256"

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host ""
    Write-Host "[1/3] Creating the local Python environment..." -ForegroundColor Cyan

    $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    $PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue

    if ($PyLauncher) {
        & $PyLauncher.Source -3.12 -m venv ".venv"
        if ($LASTEXITCODE -ne 0) {
            & $PyLauncher.Source -3 -m venv ".venv"
        }
    } elseif ($PythonCommand) {
        & $PythonCommand.Source -m venv ".venv"
    } else {
        Write-Host ""
        Write-Host "Python was not found on this Windows computer." -ForegroundColor Red
        Write-Host "Install Python 3.12 (or another current Python 3) and run this launcher again." -ForegroundColor Yellow
        Read-Host "Press Enter to close"
        exit 1
    }

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Write-Host ""
        Write-Host "Could not create .venv." -ForegroundColor Red
        Read-Host "Press Enter to close"
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "[1/3] Local Python environment already exists." -ForegroundColor Green
}

$NeedInstall = $true
if ((Test-Path -LiteralPath $Requirements) -and (Test-Path -LiteralPath $RequirementsMarker)) {
    $CurrentHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    $InstalledHash = (Get-Content -LiteralPath $RequirementsMarker -Raw).Trim()
    if ($CurrentHash -eq $InstalledHash) {
        $NeedInstall = $false
    }
}

if ($NeedInstall) {
    Write-Host "[2/3] Installing/updating required Python packages..." -ForegroundColor Cyan
    Invoke-Checked $VenvPython "-m" "pip" "install" "--upgrade" "pip"
    Invoke-Checked $VenvPython "-m" "pip" "install" "-r" $Requirements
    $CurrentHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
    Set-Content -LiteralPath $RequirementsMarker -Value $CurrentHash -Encoding ASCII
} else {
    Write-Host "[2/3] Python packages are already up to date." -ForegroundColor Green
}

$Port = $null
foreach ($Candidate in 8501..8510) {
    $InUse = Test-NetConnection -ComputerName "127.0.0.1" -Port $Candidate -InformationLevel Quiet -WarningAction SilentlyContinue
    if (-not $InUse) {
        $Port = $Candidate
        break
    }
}
if ($null -eq $Port) {
    Write-Host "No free Streamlit port was found between 8501 and 8510." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$Url = "http://127.0.0.1:$Port/?view=researcher"

Write-Host "[3/3] Starting the platform on port $Port..." -ForegroundColor Cyan
Write-Host "Researcher URL: $Url" -ForegroundColor White
Write-Host ""
Write-Host "Keep this window open while you use the platform." -ForegroundColor Gray
Write-Host "To stop the platform, close this window or press Ctrl+C." -ForegroundColor Gray
Write-Host ""

$StreamlitArgs = @(
    "-m", "streamlit", "run", "app.py",
    "--server.address", "127.0.0.1",
    "--server.port", "$Port",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false"
)

$Process = Start-Process -FilePath $VenvPython -ArgumentList $StreamlitArgs -WorkingDirectory $RepoRoot -PassThru -NoNewWindow

$Ready = $false
for ($i = 0; $i -lt 60; $i++) {
    if ($Process.HasExited) {
        break
    }
    $Ready = Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($Ready) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if ($Ready) {
    Start-Process $Url
    Write-Host "[OK] Platform opened in the default browser." -ForegroundColor Green
} else {
    Write-Warning "The Streamlit server did not become ready automatically."
    Write-Host "If it is still running, open this URL manually: $Url" -ForegroundColor Yellow
}

if (-not $Process.HasExited) {
    Wait-Process -Id $Process.Id
}

if ($Process.HasExited -and $Process.ExitCode -ne 0) {
    Write-Host ""
    Write-Host "The platform stopped with exit code $($Process.ExitCode)." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit $Process.ExitCode
}
