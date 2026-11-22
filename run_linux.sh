#!/usr/bin/env bash
# Run Profound on Linux (tested target: Arch Linux). Usage:  ./run_linux.sh
set -e
cd "$(dirname "$0")"

if ! python3 -c "import tkinter" 2>/dev/null; then
  echo "Python with Tk is needed.  Arch:  sudo pacman -S python tk      Debian/Ubuntu:  sudo apt install python3-tk"
  exit 1
fi
if [ ! -x engine/llama-server ] && ! command -v llama-server >/dev/null; then
  echo "The AI engine (llama-server from llama.cpp) is missing. Either:"
  echo "  Arch:  yay -S llama.cpp          (or llama.cpp-vulkan for GPU)"
  echo "  or unzip the Linux build from https://github.com/ggml-org/llama.cpp/releases into ./engine/"
  exit 1
fi
if [ -z "$(ls models/*.gguf Profound-App/models/*.gguf 2>/dev/null)" ]; then
  echo "No AI model found: put a .gguf model in ./models (see README_LINUX_MAC.md)."
  exit 1
fi
python3 -c "import tkinterdnd2" 2>/dev/null || echo "Tip: 'pip install --user tkinterdnd2' enables drag & drop."
exec python3 profound_app.py "$@"
