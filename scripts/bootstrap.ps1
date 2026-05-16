Param()
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$RootDir/.."
if (-Not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip setuptools wheel
if (Test-Path "$RootDir/../requirements.txt") { pip install -r "$RootDir/../requirements.txt" }
Write-Host "Environment ready. To activate: .\.venv\Scripts\Activate.ps1"
