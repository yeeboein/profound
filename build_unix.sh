#!/usr/bin/env bash
# Build a standalone Profound on Linux or macOS (run it ON that system).
# Output: Profound-App/  with the app (Profound or Profound.app), plus engine/ and models/ next to it.
set -e
cd "$(dirname "$0")"
python3 -m pip install --user pyinstaller tkinterdnd2 >/dev/null
SEP=":"
python3 -m PyInstaller --noconfirm --windowed --onefile --name Profound \
  --add-data "logo.png${SEP}." --add-data "buddy_idle.png${SEP}." --add-data "buddy_talk.png${SEP}." \
  --add-data "icon.ico${SEP}." --add-data "vscode_ext${SEP}vscode_ext" --add-data "training_pack${SEP}training_pack" \
  --collect-all tkinterdnd2 \
  --distpath Profound-App --workpath /tmp/pf_build --specpath /tmp/pf_build profound_app.py
mkdir -p Profound-App/models Profound-App/engine
for m in models/*.gguf; do [ -e "$m" ] && mv -n "$m" Profound-App/models/; done
if [ ! -x Profound-App/engine/llama-server ] && command -v llama-server >/dev/null; then
  echo "Using the system llama-server ($(command -v llama-server)); Profound finds it automatically."
fi
echo "Built: $(pwd)/Profound-App"
