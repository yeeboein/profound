# Profound on Arch Linux and macOS

Profound is the same app on every system. On Linux and macOS it needs three things:
**Python with Tk**, the **llama.cpp engine** (`llama-server`) and at least one **AI model** (`.gguf`).

## Arch Linux

```bash
sudo pacman -S python tk
yay -S llama.cpp            # or llama.cpp-vulkan / llama.cpp-cuda for GPU speed
pip install --user tkinterdnd2   # optional: drag & drop files onto the window
./run_linux.sh
```

## macOS (Apple Silicon or Intel)

```bash
brew install python python-tk llama.cpp
pip3 install tkinterdnd2         # optional: drag & drop
./run_macos.sh
```

## Models

Copy the `.gguf` files from your Windows `Profound-App/models` folder into `models/` (or `Profound-App/models/`).
Only copy what that computer can run:

| Model | File size | RAM needed |
|---|---|---|
| Gemma 4 12B (smart) | 6.7 GB | 16 GB |
| Ministral 3 3B (small & smart) | 2.0 GB | 4 GB |
| Gemma 4 E2B Mobile (small) | 2.0 GB | 4 GB |

To let Gemma 4 12B see images, also copy `mmproj-gemma-4-12B-it-Q8_0.gguf`.

## Building a standalone app

Run `./build_unix.sh` **on** the Linux or Mac machine (apps can't be built for macOS from Windows).

## Differences from Windows

- The live preview opens in your web browser instead of inside the app (it still updates as you type).
- Drag & drop needs `tkinterdnd2` (see above); the paperclip button always works.
- Run (F5) opens Terminal on macOS, or your terminal (konsole, gnome-terminal, alacritty, kitty, xterm...) on Linux.
