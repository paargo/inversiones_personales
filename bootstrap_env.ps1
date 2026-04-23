param(
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$BundledPython = "C:\Users\Pablo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

function Write-Status {
    param([string]$Message)
    Write-Host $Message
}

if ($ForceRecreate -and (Test-Path $VenvPath)) {
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPython)) {
    if (Test-Path $BundledPython) {
        Write-Status "Creating .venv with bundled Python..."
        & $BundledPython -m venv --system-site-packages $VenvPath
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        Write-Status "Creating .venv with python on PATH..."
        & python -m venv $VenvPath
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        Write-Status "Creating .venv with py launcher..."
        & py -3 -m venv $VenvPath
    }
    else {
        throw "No Python interpreter found. Install Python or use the bundled runtime."
    }
}

Write-Status "Upgrading pip..."
& $VenvPython -m pip install --upgrade pip

Write-Status "Installing project dependencies..."
& $VenvPython -m pip install -r requirements.txt

Write-Status ""
Write-Status "Environment ready."
Write-Status "Activate with: .\\.venv\\Scripts\\Activate.ps1"
Write-Status "Run the app with: .\\.venv\\Scripts\\python.exe -m streamlit run app.py"
