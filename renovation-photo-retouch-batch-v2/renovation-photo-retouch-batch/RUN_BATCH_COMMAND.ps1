# Optional: from Windows PowerShell, run .\RUN_BATCH_COMMAND.ps1 'C:\Photos\Batch1.zip'
param([string]$InputPath='')
Set-Location $PSScriptRoot
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { Write-Error 'Please run install_windows.bat first'; exit 1 }
if ($InputPath) { & $python -m app.batch --input $InputPath } else { & $python -m app.batch }
exit $LASTEXITCODE
