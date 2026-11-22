# Rebuilds the standalone app folder: Profound-App\Profound.exe + engine\ + models\
$d = $PSScriptRoot
$out = Join-Path $d "Profound-App"
Get-Process Profound, llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1
New-Item -ItemType Directory -Force $out | Out-Null
python -m PyInstaller --onefile --windowed --name Profound --icon "$d\icon.ico" `
    --add-data "$d\logo.png;." --add-data "$d\buddy_idle.png;." --add-data "$d\buddy_talk.png;." --add-data "$d\icon.ico;." --add-data "$d\vscode_ext;vscode_ext" --add-data "$d\training_pack;training_pack" --add-data "$d\README_LINUX_MAC.md;." `
    --distpath $out --workpath "$env:TEMP\pf_build" --specpath "$env:TEMP\pf_build" "$d\profound_app.py" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller failed" -ForegroundColor Red; exit 1 }
if (-not (Test-Path "$out\engine")) { Copy-Item "$d\engine" "$out\engine" -Recurse }
New-Item -ItemType Directory -Force "$out\models" | Out-Null
# Move finished models (not .part downloads) into the app so there is only one copy on disk
Get-ChildItem "$d\models\*.gguf" -ErrorAction SilentlyContinue | ForEach-Object {
    if (-not (Test-Path "$out\models\$($_.Name)")) { Move-Item $_.FullName "$out\models\" } else { Remove-Item $_.FullName }
}
Write-Host "Built: $out\Profound.exe"




