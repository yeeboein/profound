#!/usr/bin/env bash
# Run Profound on macOS. Usage:  ./run_macos.sh
set -e
cd "$(dirname "$0")"

if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python with Tk is needed:  brew install python python-tk"
  exit 1
fi
if [ ! -x engine/llama-server ] && ! command -v llama-server >/dev/null; then
  echo "The AI engine is missing:  brew install llama.cpp"
  echo "  (or unzip the macOS build from https://github.com/ggml-org/llama.cpp/releases into ./engine/)"
  exit 1
fi
if [ -z "$(ls models/*.gguf Profound-App/models/*.gguf 2>/dev/null)" ]; then
  echo "No AI model found: put a .gguf model in ./models (see README_LINUX_MAC.md)."
  exit 1
fi
python3 -c "import tkinterdnd2" 2>/dev/null || echo "Tip: 'pip3 install tkinterdnd2' enables drag & drop."
exec python3 profound_app.py "$@"
