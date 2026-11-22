# Profound

An offline AI coding app for your desktop. Chat with a local AI model that writes and edits code for you,
with no internet connection and no account. It runs entirely on your own computer.

## Features

- **Chat in two modes.** In **Ask** mode, Profound just tells you the code. In **Edit** mode, it works directly in the files of your open folder.
- **Code tab.** Code appears live in its own tab while the AI writes it, so the chat stays clean. In chat, follow-ups keep editing the same file.
- **Live HTML preview.** It sits in its own tab and updates as you type. It has Desktop, Tablet and Phone sizes and reports page errors.
- **Quick build and restyle.** These are for small models: Profound assembles pages from 360+ hand-tuned CSS components and applies complete stylesheets (Glass, Neon, Pastel, Luxury, Retro and more).
- **Train.** Feed Profound your own code and it learns your style through example search. It ships with a starter pack of 380 HTML/CSS examples.
- **Models.** The default is the Gemma 4 family. The "Best AI for you" option picks a model that fits your RAM, and the RAM Usage slider sets the limit. You can also add your own GGUF models.
- **Attachments.** Images (with vision models) and any other files, by button or drag and drop.
- **Other features.** Saved chats (rename and delete), style presets, a VS Code / VSCodium extension, and a dark green theme.
- **Platforms.** Windows (main), Linux (including Arch) and macOS.

## Requirements

- **RAM:** 4 GB minimum (with a small model); 16 GB recommended for Gemma 4 12B.
- **Python:** Python 3.10+ with Tk. This is only needed to run from source or build.

## Get the AI engine and a model

These files are too large for GitHub, so download them separately:

1. **Engine:** download a [llama.cpp release](https://github.com/ggml-org/llama.cpp/releases) for your system (Windows: the CPU x64 zip), then extract it so `llama-server` sits in an `engine/` folder next to `profound_app.py`.
2. **Model:** download one or more GGUF models into `models/`. The app is tuned for these:

   | Model | File | RAM needed |
   |-------|------|------------|
   | Gemma 4 12B (best, sees images) | `gemma-4-12B-it-Q4_0.gguf` + `mmproj-gemma-4-12B-it-Q8_0.gguf` | about 8 GB |
   | Ministral 3 3B | `Ministral-3-3B-Instruct-2512-Q4_K_M.gguf` | about 4 GB |
   | Gemma 4 E2B (4 GB PCs) | `gemma-4-E2B-it-qat-UD-Q2_K_XL.gguf` | about 1.5 GB |

## Run from source

```powershell
python profound_app.py
```

For Linux and macOS, see [README_LINUX_MAC.md](README_LINUX_MAC.md) (`run_linux.sh`, `run_macos.sh`).

## Build the Windows app

```powershell
pip install pyinstaller
.\build.ps1
```

This creates `Profound-App\Profound.exe` and copies `engine\` into it. Put your models in `Profound-App\models\`.

## Project layout

| File | What it does |
|------|--------------|
| `profound_app.py` | The whole app: UI, chat, editor, preview, training, engine control |
| `page_builder.py` | Quick build page assembler |
| `restyle.py` | Complete stylesheets applied to existing pages |
| `make_css_pack.py` | Generates the CSS components and templates in `training_pack/` |
| `vscode_ext/` | VS Code / VSCodium extension |
| `build.ps1`, `build_unix.sh` | Build scripts |
