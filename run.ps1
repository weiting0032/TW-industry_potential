# One-shot launcher for Windows: create the venv if missing, install deps, start the app.
# Console output is intentionally English only: Windows decodes .ps1 with the system
# code page (not UTF-8), so non-ASCII text here turns into mojibake and can break parsing.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    if (Test-Path ".venv") {
        Write-Host "ERROR: .venv exists but has no Windows interpreter (.venv\Scripts\python.exe)."
        Write-Host "It was most likely created on macOS or Linux. Rename or delete .venv, then re-run."
        exit 1
    }
    Write-Host "Creating virtual environment .venv"
    python -m venv .venv
}

& $py -m pip install --quiet --upgrade pip
if ($?) { & $py -m pip install --quiet -r requirements-fetch.txt }

Write-Host "Starting Streamlit at http://localhost:8501"
& $py -m streamlit run app.py --server.port 8501
