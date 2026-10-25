$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pytest
python -m compileall -q framepilot tests scripts
python -m PyInstaller --noconfirm --clean --windowed --name FramePilot `
  --collect-all rawpy `
  --hidden-import PIL._tkinter_finder `
  framepilot/main.py

Write-Host "FramePilot package created at $root\dist\FramePilot"

