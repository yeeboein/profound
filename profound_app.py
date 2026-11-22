"""Profound - a standalone offline AI code editor (native window, built-in AI engine).
Runs llama.cpp's llama-server from the 'engine' folder (or one installed on the system) with .gguf models
from 'models'. Works on Windows, Linux (incl. Arch) and macOS. No internet needed."""
import atexit
import bisect
import ctypes
import glob
import signal
import http.server
import json
import math
import mimetypes
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import types
import urllib.parse
import urllib.request
import uuid
import webbrowser
from collections import Counter

try:
    import restyle  # complete stylesheets Profound applies itself when a small model is asked to style a page
except Exception:
    restyle = None
try:
    import page_builder  # Quick build page assembler (uses make_css_pack's components)
except Exception:  # keeps the app working even if the builder is missing
    page_builder = None
from tkinter import colorchooser, messagebox, simpledialog, filedialog, ttk

try:
    import ctypes.wintypes as wt
except (ImportError, ValueError):  # not on Windows
    wt = None

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
LINUX = not WIN and not MAC
SANS = "Segoe UI" if WIN else ("Helvetica Neue" if MAC else "Noto Sans")
SANS_SEMI = "Segoe UI Semibold" if WIN else SANS
MONO = "Consolas" if WIN else ("Menlo" if MAC else "DejaVu Sans Mono")

FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
if MAC and FROZEN and APP_DIR.endswith(os.path.join("Contents", "MacOS")):
    APP_DIR = os.path.abspath(os.path.join(APP_DIR, "..", "..", ".."))  # folder that holds Profound.app
ENGINE = os.path.join(APP_DIR, "engine", "llama-server.exe" if WIN else "llama-server")
if not os.path.exists(ENGINE) and shutil.which("llama-server"):
    ENGINE = shutil.which("llama-server")  # e.g. Arch: AUR llama.cpp, macOS: brew install llama.cpp
MODELS = os.path.join(APP_DIR, "models")
if not FROZEN and not glob.glob(os.path.join(MODELS, "*.gguf")) and os.path.isdir(os.path.join(APP_DIR, "Profound-App", "models")):
    MODELS = os.path.join(APP_DIR, "Profound-App", "models")  # running from source after a build moved the models
if WIN:
    _DATA_BASE = os.environ.get("LOCALAPPDATA", APP_DIR)
elif MAC:
    _DATA_BASE = os.path.expanduser("~/Library/Application Support")
else:
    _DATA_BASE = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
DATA_DIR = os.path.join(_DATA_BASE, "Profound")
TRAIN_DIR = os.path.join(DATA_DIR, "train")
CHATS_DIR = os.path.join(DATA_DIR, "chats")
CFG_PATH = os.path.join(DATA_DIR, "settings.json")
LOG_PATH = os.path.join(DATA_DIR, "error.log")
NO_WINDOW = 0x08000000


def _die_with_parent():
    """Linux: the engine stops automatically if Profound is killed."""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:
        pass


BG_PROC = {"creationflags": NO_WINDOW} if WIN else ({"preexec_fn": _die_with_parent} if LINUX else {})


def open_path(p):
    """Open a file or folder with the system's file manager / default app."""
    if WIN:
        os.startfile(p)
    else:
        subprocess.Popen(["open" if MAC else "xdg-open", p])


def open_terminal(cmd, cwd):
    """Run a command in a new terminal window that stays open afterwards."""
    if WIN:
        subprocess.Popen(f"cmd /k call {cmd}", cwd=cwd, creationflags=0x10)
        return True
    script = f'cd "{cwd}" && {cmd}; echo; read -p "Press Enter to close..."'
    if MAC:
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script {json.dumps(script)}',
                          "-e", 'tell application "Terminal" to activate'])
        return True
    for term, args in (("x-terminal-emulator", ["-e"]), ("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("kgx", ["--"]),
                       ("alacritty", ["-e"]), ("kitty", []), ("foot", []), ("wezterm", ["start", "--"]),
                       ("xfce4-terminal", ["-x"]), ("xterm", ["-e"])):
        if shutil.which(term):
            subprocess.Popen([term, *args, "bash", "-c", script])
            return True
    return False


def wheel_steps(e):
    """Mouse-wheel direction/amount on every OS (Linux sends Button-4/5, macOS small deltas)."""
    if getattr(e, "num", None) == 4:
        return -1
    if getattr(e, "num", None) == 5:
        return 1
    if MAC:
        return -e.delta
    return -int(e.delta / 120) or (-1 if e.delta > 0 else 1)
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode", "dist", "build", "target", "bin", "obj"}
WEB_EXT = {".html", ".htm", ".css", ".js"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
VISION_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}  # formats the AI engine can look at
TEXT_EXT = {".txt", ".csv", ".tsv", ".log", ".md", ".json", ".xml", ".yaml", ".yml", ".ini", ".toml", ".env.example"}
BUILTIN_PREFIXES = ("gemma-4", "ministral-3", "qwen3.5", "granite-4", "qwen2.5-coder")  # models Profound knows
# Ordered smartest first: Auto picks the highest one on this list that fits the PC's RAM.
MODEL_LABELS = [("gemma-4-31b", "Gemma 4 31B", "Smartest"), ("gemma-4-26b", "Gemma 4 26B", "Expert"),
                ("gemma-4-12b", "Gemma 4 12B", "Smart"), ("gemma-4-e4b", "Gemma 4 E4B", "Balanced"),
                ("ministral-3-8b", "Ministral 3 8B", "Balanced"), ("qwen3.5-4b", "Qwen3.5 4B", "Small coder"),
                ("ministral-3-3b", "Ministral 3 3B", "Small & smart"), ("gemma-4-e2b", "Gemma 4 E2B", "Small & light"),
                ("granite-4.2-3b", "Granite 4.2 3B", "Small"), ("qwen2.5-coder-7b", "Qwen2.5 Coder 7B", "Coding"),
                ("qwen2.5-coder-1.5b", "Qwen2.5 Coder 1.5B", "Light")]


def model_rank(name):
    """Lower = smarter (position in MODEL_LABELS); unknown models rank last."""
    low = name.lower()
    return next((i for i, (key, _, _) in enumerate(MODEL_LABELS) if low.startswith(key)), 999)


def model_label(name):
    """Friendly (title, tag) for a model file, e.g. ("Gemma 4 12B", "Smart")."""
    low = name.lower()
    for key, title, tag in MODEL_LABELS:
        if low.startswith(key):
            return title, tag
    return pretty_model(name), "Yours"


def is_builtin(name):
    return name.lower().startswith(BUILTIN_PREFIXES)

# ---- palette
BG, PANEL, PANEL2, HOVER, LINE = "#0d110e", "#131914", "#1b231d", "#253028", "#202a22"
FG, MUTED, DIM = "#e8ebf0", "#8b93a3", "#596172"
GOOD, WARN, BAD = "#4cc38a", "#e5a84b", "#ff7b7b"
EDITOR, CODE_BG, CODE_BTN, USER_BG, CARD = "#101511", "#0a0d0b", "#18201a", "#1c3021", "#171f19"
UI, UI_SM, UI_XS = (SANS, 10), (SANS, 9), (SANS, 8)
UI_B, UI_H = (SANS_SEMI, 10), (SANS_SEMI, 12)
CHAT_FONT, CHAT_B = (SANS, 10), (SANS_SEMI, 10)
ACCENTS = ["#a8e71d", "#22c55e", "#14b8a6", "#5a9dff", "#f59e0b", "#ec4899"]
THEME = {"accent": ACCENTS[0]}

DEF = {"mode": "edit", "temp": 0.3, "maxTok": 2048, "mem": 12, "autoApply": True, "autoSave": False,
       "font": 11, "lineNums": True, "accent": ACCENTS[0], "custom": "", "ram": 0, "model": "auto",
       "autoPreview": True, "lastFolder": "", "style": "none", "useTrain": True, "seeFile": True, "deepThink": False}

# ---- languages
LANG_INFO = {  # ext: (highlight family, display name)
    ".py": ("py", "Python"), ".pyw": ("py", "Python"), ".js": ("c", "JavaScript"), ".mjs": ("c", "JavaScript"),
    ".cjs": ("c", "JavaScript"), ".jsx": ("c", "React JSX"), ".ts": ("c", "TypeScript"), ".tsx": ("c", "React TSX"),
    ".java": ("c", "Java"), ".c": ("c", "C"), ".h": ("c", "C header"), ".cpp": ("c", "C++"), ".cc": ("c", "C++"),
    ".hpp": ("c", "C++ header"), ".cs": ("c", "C#"), ".go": ("c", "Go"), ".rs": ("c", "Rust"), ".php": ("c", "PHP"),
    ".swift": ("c", "Swift"), ".kt": ("c", "Kotlin"), ".dart": ("c", "Dart"), ".scala": ("c", "Scala"),
    ".rb": ("hash", "Ruby"), ".pl": ("hash", "Perl"), ".r": ("hash", "R"), ".lua": ("lua", "Lua"),
    ".sh": ("sh", "Bash"), ".bash": ("sh", "Bash"), ".ps1": ("sh", "PowerShell"), ".bat": ("sh", "Batch"), ".cmd": ("sh", "Batch"),
    ".sql": ("sql", "SQL"), ".html": ("web", "HTML"), ".htm": ("web", "HTML"), ".xml": ("web", "XML"), ".svg": ("web", "SVG"),
    ".vue": ("web", "Vue"), ".css": ("css", "CSS"), ".scss": ("css", "SCSS"), ".less": ("css", "LESS"),
    ".json": ("data", "JSON"), ".yaml": ("data", "YAML"), ".yml": ("data", "YAML"), ".toml": ("data", "TOML"),
    ".ini": ("data", "INI"), ".cfg": ("data", "Config"), ".md": ("md", "Markdown"), ".txt": (None, "Text"),
}
FENCE_FAM = {"python": "py", "py": "py", "javascript": "c", "js": "c", "jsx": "c", "typescript": "c", "ts": "c", "tsx": "c",
             "java": "c", "c": "c", "cpp": "c", "c++": "c", "csharp": "c", "cs": "c", "c#": "c", "go": "c", "golang": "c",
             "rust": "c", "rs": "c", "php": "c", "swift": "c", "kotlin": "c", "kt": "c", "dart": "c", "scala": "c",
             "html": "web", "xml": "web", "svg": "web", "vue": "web", "css": "css", "scss": "css", "less": "css",
             "bash": "sh", "sh": "sh", "shell": "sh", "zsh": "sh", "powershell": "sh", "ps1": "sh", "bat": "sh", "cmd": "sh",
             "batch": "sh", "sql": "sql", "lua": "lua", "ruby": "hash", "rb": "hash", "perl": "hash", "r": "hash",
             "json": "data", "yaml": "data", "yml": "data", "toml": "data", "ini": "data", "markdown": "md", "md": "md"}
EXT_FOR = {"python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts", "jsx": ".jsx",
           "tsx": ".tsx", "java": ".java", "c": ".c", "cpp": ".cpp", "c++": ".cpp", "csharp": ".cs", "cs": ".cs", "go": ".go",
           "rust": ".rs", "rs": ".rs", "php": ".php", "swift": ".swift", "kotlin": ".kt", "dart": ".dart", "html": ".html",
           "css": ".css", "scss": ".scss", "bash": ".sh", "sh": ".sh", "powershell": ".ps1", "ps1": ".ps1", "bat": ".bat",
           "sql": ".sql", "lua": ".lua", "ruby": ".rb", "json": ".json", "yaml": ".yaml", "toml": ".toml", "markdown": ".md",
           "xml": ".xml", "svg": ".svg", "vue": ".vue", "r": ".r", "perl": ".pl"}
LANG_NAME = {"py": "Python", "python": "Python", "js": "JavaScript", "javascript": "JavaScript", "ts": "TypeScript",
             "typescript": "TypeScript", "html": "HTML", "css": "CSS", "cpp": "C++", "c++": "C++", "cs": "C#", "csharp": "C#",
             "rs": "Rust", "rust": "Rust", "go": "Go", "java": "Java", "sh": "Shell", "bash": "Bash", "ps1": "PowerShell",
             "powershell": "PowerShell", "sql": "SQL", "json": "JSON", "rb": "Ruby", "ruby": "Ruby", "php": "PHP", "lua": "Lua",
             "kotlin": "Kotlin", "swift": "Swift", "dart": "Dart", "c": "C", "yaml": "YAML", "md": "Markdown", "jsx": "JSX", "tsx": "TSX"}
RUNNERS = {  # ext: [(program, command template)]  {exe} program, {f} file, {o} compiled output
    ".py": [("python", '"{exe}" "{f}"'), ("py", '"{exe}" "{f}"')], ".pyw": [("python", '"{exe}" "{f}"')],
    ".js": [("node", '"{exe}" "{f}"')], ".mjs": [("node", '"{exe}" "{f}"')],
    ".ts": [("tsx", '"{exe}" "{f}"'), ("ts-node", '"{exe}" "{f}"'), ("deno", '"{exe}" run "{f}"')],
    ".rb": [("ruby", '"{exe}" "{f}"')], ".php": [("php", '"{exe}" "{f}"')], ".lua": [("lua", '"{exe}" "{f}"')],
    ".pl": [("perl", '"{exe}" "{f}"')], ".r": [("Rscript", '"{exe}" "{f}"')], ".go": [("go", '"{exe}" run "{f}"')],
    ".java": [("java", '"{exe}" "{f}"')], ".dart": [("dart", '"{exe}" run "{f}"')],
    ".c": [("gcc", '"{exe}" "{f}" -o "{o}" && "{o}"'), ("clang", '"{exe}" "{f}" -o "{o}" && "{o}"')],
    ".cpp": [("g++", '"{exe}" "{f}" -o "{o}" && "{o}"'), ("clang++", '"{exe}" "{f}" -o "{o}" && "{o}"')],
    ".rs": [("rustc", '"{exe}" "{f}" -o "{o}" && "{o}"')],
    ".ps1": [("powershell", '"{exe}" -NoProfile -ExecutionPolicy Bypass -File "{f}"'), ("pwsh", '"{exe}" -NoProfile -File "{f}"')],
    ".bat": [("cmd", '"{f}"')], ".cmd": [("cmd", '"{f}"')], ".sh": [("bash", '"{exe}" "{f}"')],
}
RUN_NAMES = {".py": "Python", ".js": "Node.js", ".ts": "tsx, ts-node or Deno", ".rb": "Ruby", ".php": "PHP", ".lua": "Lua",
             ".go": "Go", ".java": "Java", ".c": "GCC or Clang", ".cpp": "G++ or Clang", ".rs": "Rust", ".dart": "Dart",
             ".sh": "Bash (Git Bash or WSL)", ".pl": "Perl", ".r": "R"}

# ---- UI style presets ("Style" picker)
STYLES = {
    "minimal": ("Clean Minimal", "Lots of white space, crisp and calm", ["#ffffff", "#111827", "#2563eb", "#e5e7eb"],
                "Clean minimal: white #ffffff background, near-black #111827 text, one blue accent #2563eb, light grey #e5e7eb borders, "
                "generous whitespace, 8px radius, subtle 1px borders, no heavy shadows, simple system sans-serif font."),
    "darksaas": ("Dark SaaS", "Modern startup look with glow", ["#0b0f19", "#111827", "#6366f1", "#22d3ee"],
                 "Dark SaaS: #0b0f19 page, #111827 cards, indigo #6366f1 to cyan #22d3ee gradient accents and buttons, soft glowing "
                 "shadows, 12-16px radius, bold large headings, subtle 1px rgba(255,255,255,.08) borders."),
    "glass": ("Glassmorphism", "Frosted glass on vivid gradients", ["#7c3aed", "#db2777", "#f59e0b", "#ffffff"],
              "Glassmorphism: vivid gradient background (#7c3aed to #db2777 to #f59e0b), frosted translucent cards "
              "background rgba(255,255,255,.14) with backdrop-filter: blur(16px), white text, 1px rgba(255,255,255,.3) borders, 20px radius."),
    "neon": ("Neon Cyberpunk", "Glowing neon on deep black", ["#0a0014", "#ff2bd6", "#00f0ff", "#f5f500"],
             "Neon cyberpunk: near-black #0a0014 background, neon pink #ff2bd6 and cyan #00f0ff with glowing text-shadow and box-shadow, "
             "yellow #f5f500 highlights, monospace headings, sharp corners, subtle scanline/grid background."),
    "pastel": ("Soft Pastel", "Friendly, playful and rounded", ["#fdf6f0", "#f9c6d3", "#bdeadf", "#d9ccff"],
               "Soft pastel: cream #fdf6f0 background, pastel pink #f9c6d3, mint #bdeadf and lavender #d9ccff, dark text #3d3a4b, "
               "very rounded 24px corners, soft large shadows, friendly rounded font."),
    "material": ("Material", "Google Material Design 3", ["#fffbfe", "#6750a4", "#e8def8", "#1c1b1f"],
                 "Material Design 3: #fffbfe surface, primary #6750a4, secondary container #e8def8, text #1c1b1f, elevated cards with "
                 "soft shadows, 16px radius, pill-shaped buttons, clear typographic scale."),
    "brutal": ("Neo-Brutalism", "Bold borders and hard shadows", ["#fffdf5", "#000000", "#ffde59", "#5ce1e6"],
               "Neo-brutalism: off-white #fffdf5 background, thick 3px solid black borders, hard offset shadows (6px 6px 0 #000), "
               "bright yellow #ffde59 and aqua #5ce1e6 blocks, chunky bold type, no blur, slightly rotated stickers."),
    "retro": ("Retro 90s", "Classic Windows 95 vibes", ["#008080", "#c0c0c0", "#000080", "#ffffff"],
              "Retro 90s / Windows 95: teal #008080 desktop background, grey #c0c0c0 windows with beveled 3D borders, navy #000080 "
              "title bars with white text, square corners, pixel-style small font, chunky buttons."),
    "luxury": ("Luxury", "Elegant black and gold", ["#0c0c0c", "#c9a227", "#f5f1e6", "#2a2a2a"],
               "Luxury elegant: black #0c0c0c background, gold #c9a227 accents and thin gold lines, ivory #f5f1e6 text, serif headings "
               "(Georgia, 'Times New Roman'), wide letter-spacing on small caps labels, lots of space."),
    "earthy": ("Nature", "Calm earthy tones", ["#f4efe6", "#2f5d50", "#c8663b", "#e3d5b8"],
               "Nature / earthy: sand #f4efe6 background, forest green #2f5d50, terracotta #c8663b accents, beige #e3d5b8 cards, "
               "organic rounded shapes, warm and calm feel."),
}

# Quick build (small models only): page types and the template each one starts from (in training_pack/)
QB_PAGES = [("landing", "Landing page", "saas-landing.html"), ("portfolio", "Portfolio", "portfolio-pastel.html"),
            ("pricing", "Pricing page", "pricing.html"), ("dashboard", "Dashboard", "dashboard.html"),
            ("login", "Login screen", "login-glass.html"), ("blog", "Blog article", "blog-article.html"),
            ("product", "Product page", "product-page.html"), ("todo", "To-do app", "todo-brutal.html"),
            ("404", "404 page", "404-neon.html"), ("kit", "UI components", "ui-components.html")]
QB_SECTIONS = ["Navbar", "Hero", "Features", "Testimonials", "Pricing", "FAQ", "Contact form", "Footer"]
QB_COLORS = ["#2563eb", "#7c3aed", "#db2777", "#16a34a", "#f59e0b", "#ef4444", "#0ea5e9", "#111827"]

LANG_LIST = ("Python, JavaScript, TypeScript, HTML, CSS, Java, C, C++, C#, Go, Rust, PHP, Ruby, Swift, Kotlin, Dart, Lua, "
             "SQL, Bash, PowerShell and more")
BASE_RULES = (f"You are Profound, an expert software engineer fluent in every major programming language ({LANG_LIST}). "
              "Write clean, modern, complete, runnable code that follows each language's best practices, with short helpful comments "
              "and sensible error handling. Be concise: lead with the code, keep explanations short, and only use the language the "
              "user asked for. Always tag code fences with the language. Put code ONLY inside fenced code blocks, never in the "
              "explanation. After the code, explain what you did in 2-4 short bullet points. For web pages write ONE HTML file: "
              "all CSS in a <style> block at the top (inside <head>), then the HTML below it, and any JavaScript in a <script> "
              "at the end of <body>. When asked to style, restyle or add CSS without details, do NOT ask questions: pick a polished, "
              "modern design and return the COMPLETE updated file. Web pages must work offline: no external CDNs, "
              "web fonts or remote images; use system font stacks and inline SVG.")
EDIT_SYSTEM = (BASE_RULES + " You work inside the user's code editor. When you write or change a file, output the COMPLETE new "
               "contents of that file in one fenced code block whose opening fence is ```language:relative/path (for example "
               "```html:index.html or ```rust:src/main.rs). When changing the currently open file, use its exact path. Never use "
               "placeholders like '...rest of file'. Keep explanations brief.")
ASK_SYSTEM = (BASE_RULES + " The user just wants to be TOLD: answer questions clearly, show focused code in fenced code blocks, "
              "and explain it simply. Do not mention applying or saving files.")
STYLE_REQ = re.compile(r"\b(styl\w*|css|pretty|prettier|nicer|beautif\w*|design\w*|look\w* (better|good|nice|modern)|"
                       r"modern\w*|colou?r\w*|theme\w*|make it (look|nice|cool|better)|glass\w*|neon|gradient\w*|animat\w*)\b", re.I)
STYLE_GUIDE = ("How to style it well (do all of this): put ONE <style> block in <head> with AT LEAST 15 CSS rules: "
               ":root colour variables (--bg, --surface, --text, --muted, --accent); body (system font stack, background, colour, "
               "line-height 1.6, margin 0); a centred container (max-width, margin: 0 auto, padding); a header/hero with a big bold "
               "heading and a short muted subtitle; nice paragraph spacing; lists turned into cards or pills (padding, border-radius, "
               "background var(--surface), box-shadow); links and buttons with :hover states and a transition; spacing with gap and "
               "margin; and a @media (max-width: 600px) rule. Keep ALL the existing text and HTML. Reply with the COMPLETE file.")
SUGGESTIONS = ["Make a modern landing page in one HTML file", "Write a Python script that renames files in a folder",
               "Explain the open file in simple words", "Find and fix bugs in the open file"]


# ---------------------------------------------------------------- helpers
def log_error(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


def total_ram_gb():
    class MEM(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                    ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
    if not WIN:
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        except (ValueError, OSError, AttributeError):
            return 8.0
    m = MEM()
    m.l = ctypes.sizeof(MEM)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 2 ** 30
    except Exception:
        return 8.0


def plan(model_bytes, ram_gb, mem=None):
    """Context size that fits the RAM budget -> (fits, ctx, needed_gb_minimum, used_gb)."""
    m = mem if mem else model_bytes / 1e9 * 1.05
    free = ram_gb - m - 0.3
    per = (0.03 + m * 0.008) / 1024
    ctx = int(free / per // 256 * 256) if free > 0 else 0
    ctx = max(512, min(16384, ctx))
    return free > 1024 * per, ctx, m + 0.3 + 1024 * per, m + 0.3 + ctx * per


# Measured RAM (GB, model + engine buffers) where it differs a lot from the file size.
MODEL_MEM = {"ministral-3-3b": 3.6, "gemma-4-e2b": 1.2}


def mplan(m, ram_gb):
    """plan() for a model dict, using measured RAM figures when Profound knows them."""
    low = m["name"].lower()
    mem = next((v for k, v in MODEL_MEM.items() if low.startswith(k)), None)
    return plan(m["size"], ram_gb, mem=mem)


def pretty_model(name):
    n = re.sub(r"\.gguf$", "", name, flags=re.I)
    n = re.sub(r"[-_.]?(instruct|chat|it)\b.*$", "", n, flags=re.I) or n
    parts = [p.upper() if re.fullmatch(r"\d+(\.\d+)?[bm]", p, re.I) else p[:1].upper() + p[1:] for p in re.split(r"[-_]", n)]
    return " ".join(parts)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def find_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.exists(p):
                return p
    return shutil.which("msedge")


def style_window(win):
    """Dark title bar, matching caption colour and rounded corners (Windows 11)."""
    if not WIN:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)
        r, g, b = int(PANEL[1:3], 16), int(PANEL[3:5], 16), int(PANEL[5:7], 16)
        col = ctypes.c_int(r | (g << 8) | (b << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), 4)
        rnd = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rnd), 4)
    except Exception:
        pass


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def shade(hex_color, amt):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    f = (lambda c: min(255, int(c + (255 - c) * amt))) if amt > 0 else (lambda c: max(0, int(c * (1 + amt))))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


def rrect(c, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle on a canvas."""
    r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, splinesteps=16, **kw)


def draw_icon(c, name, x, y, size, color):
    """Profound's own vector icons, drawn on a 16x16 grid."""
    s = size / 16.0
    w = max(1.3, 1.55 * s)

    def P(*pts):
        return [x + p * s if i % 2 == 0 else y + p * s for i, p in enumerate(pts)]

    def L(*pts):
        c.create_line(*P(*pts), fill=color, width=w, capstyle="round", joinstyle="round")

    def O(x1, y1, x2, y2, fill=""):
        c.create_oval(*P(x1, y1, x2, y2), outline=color, width=w, fill=fill)

    def F(*pts):
        c.create_polygon(*P(*pts), fill=color, outline=color, width=1, joinstyle="round")
    if name == "folder":
        L(2, 4, 6.3, 4, 7.8, 5.6, 14, 5.6, 14, 13, 2, 13, 2, 4)
    elif name == "file":
        L(4, 2, 9.5, 2, 13, 5.5, 13, 14, 4, 14, 4, 2)
        L(9.5, 2, 9.5, 5.5, 13, 5.5)
    elif name == "plus":
        L(8, 3, 8, 13)
        L(3, 8, 13, 8)
    elif name == "refresh":
        c.create_arc(*P(3, 3, 13, 13), start=60, extent=280, style="arc", outline=color, width=w)
        L(9.8, 1.9, 11.9, 3.9, 9.6, 5.6)
    elif name == "gear":
        O(5.4, 5.4, 10.6, 10.6)
        for a in range(0, 360, 45):
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            L(8 + ca * 4.6, 8 + sa * 4.6, 8 + ca * 6.6, 8 + sa * 6.6)
    elif name == "spark":
        F(7, 1.8, 8.5, 6.5, 13.2, 8, 8.5, 9.5, 7, 14.2, 5.5, 9.5, 0.8, 8, 5.5, 6.5)
        F(13, 1.2, 13.6, 2.9, 15.3, 3.5, 13.6, 4.1, 13, 5.8, 12.4, 4.1, 10.7, 3.5, 12.4, 2.9)
    elif name == "chat":
        L(4, 3, 12, 3, 13.8, 4.8, 13.8, 9.2, 12, 11, 7, 11, 4, 13.6, 4, 11, 3.9, 11, 2.2, 9.2, 2.2, 4.8, 4, 3)
    elif name == "pencil":
        L(3, 13, 3.6, 10.2, 10.8, 3, 13, 5.2, 5.8, 12.4, 3, 13)
        L(9.3, 4.5, 11.5, 6.7)
    elif name == "code":
        L(5.5, 4.2, 2, 8, 5.5, 11.8)
        L(10.5, 4.2, 14, 8, 10.5, 11.8)
        L(9.2, 3, 6.8, 13)
    elif name == "eye":
        c.create_arc(*P(1.5, 3.5, 14.5, 16), start=25, extent=130, style="arc", outline=color, width=w)
        c.create_arc(*P(1.5, 0, 14.5, 12.5), start=205, extent=130, style="arc", outline=color, width=w)
        O(6.2, 6.2, 9.8, 9.8, fill=color)
    elif name == "play":
        F(5, 3, 13, 8, 5, 13)
    elif name == "save":
        L(3, 2.5, 11, 2.5, 13.5, 5, 13.5, 13.5, 2.5, 13.5, 2.5, 2.5, 3, 2.5)
        L(5.5, 2.5, 5.5, 5.8, 10, 5.8, 10, 2.5)
        L(5, 13.5, 5, 9.5, 11, 9.5, 11, 13.5)
    elif name == "history":
        O(2.5, 2.5, 13.5, 13.5)
        L(8, 5, 8, 8, 10.4, 9.6)
    elif name == "trash":
        L(2.8, 4.5, 13.2, 4.5)
        L(6.2, 4.5, 6.6, 2.5, 9.4, 2.5, 9.8, 4.5)
        L(4.2, 4.5, 5, 13.5, 11, 13.5, 11.8, 4.5)
        L(6.9, 7.2, 6.9, 11)
        L(9.1, 7.2, 9.1, 11)
    elif name == "send":
        F(2.2, 2.6, 14, 8, 2.2, 13.4, 4.4, 8)
    elif name == "stop":
        F(4, 4, 12, 4, 12, 12, 4, 12)
    elif name == "palette":
        O(2, 2, 14, 14)
        for dx, dy in ((5, 6.2), (8, 4.6), (11, 6.2), (10.6, 9.8)):
            O(dx - 0.8, dy - 0.8, dx + 0.8, dy + 0.8, fill=color)
    elif name == "copy":
        L(5.5, 5.5, 13, 5.5, 13, 14, 5.5, 14, 5.5, 5.5)
        L(3, 11, 3, 2, 10.5, 2)
    elif name == "vscode":
        L(11.8, 2, 11.8, 14)
        L(11.8, 2, 3, 10.2)
        L(11.8, 14, 3, 5.8)
    elif name == "x":
        L(4.5, 4.5, 11.5, 11.5)
        L(11.5, 4.5, 4.5, 11.5)
    elif name == "check":
        L(3, 8.5, 6.5, 12, 13, 4.5)
    elif name == "chip":
        L(4.5, 4.5, 11.5, 4.5, 11.5, 11.5, 4.5, 11.5, 4.5, 4.5)
        for k in (6.5, 9.5):
            L(k, 2, k, 4.5)
            L(k, 11.5, k, 14)
            L(2, k, 4.5, k)
            L(11.5, k, 14, k)
    elif name == "external":
        L(9.5, 2.5, 13.5, 2.5, 13.5, 6.5)
        L(13.5, 2.5, 7.5, 8.5)
        L(11.5, 9.5, 11.5, 13.5, 2.5, 13.5, 2.5, 4.5, 6.5, 4.5)
    elif name == "arrow":
        L(3, 8, 13, 8)
        L(9, 4, 13, 8, 9, 12)
    elif name == "expand":
        L(4, 6, 8, 10, 12, 6)
    elif name == "warn":
        L(8, 2.5, 14.2, 13.5, 1.8, 13.5, 8, 2.5)
        L(8, 6.5, 8, 9.5)
        O(7.6, 11.3, 8.4, 12.1, fill=color)
    elif name == "clip":
        L(10.5, 5, 10.5, 11, 9.5, 13, 8, 13.6, 6.5, 13, 5.5, 11, 5.5, 4.5, 6.3, 2.8, 7.8, 2.2, 9.3, 2.8, 10, 4.5)
        L(8, 5.5, 8, 10.5)
    elif name == "image":
        L(2.5, 3.5, 13.5, 3.5, 13.5, 12.5, 2.5, 12.5, 2.5, 3.5)
        L(3, 11.5, 6.5, 7.5, 9, 10, 10.5, 8.5, 13, 11)
        O(9.8, 5.2, 11.4, 6.8, fill=color)


LANG_COLOR = {"Python": "#4b8bbe", "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "React JSX": "#61dafb", "React TSX": "#61dafb",
              "HTML": "#e34c26", "CSS": "#8b5cf6", "SCSS": "#c6538c", "Rust": "#dea584", "Go": "#00add8", "Java": "#b07219",
              "C": "#a8b9cc", "C header": "#a8b9cc", "C++": "#f34b7d", "C++ header": "#f34b7d", "C#": "#2fbf71", "PHP": "#777bb4",
              "Ruby": "#cc342d", "Swift": "#f05138", "Kotlin": "#a97bff", "Dart": "#00b4ab", "Lua": "#5e7cf2", "SQL": "#e38c00",
              "Bash": "#89e051", "PowerShell": "#5391fe", "Batch": "#c1f12e", "JSON": "#cbcb41", "YAML": "#cb171e",
              "Markdown": "#9aa4b2", "XML": "#0060ac", "SVG": "#ffb13b", "Vue": "#41b883"}


def lang_color(path):
    return LANG_COLOR.get(LANG_INFO.get(os.path.splitext(path)[1].lower(), (None, ""))[1], "#7d8594")


def make_job():
    """Windows job object so child processes die with the app, even if it crashes."""
    try:
        k = ctypes.windll.kernel32

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("a", "b", "c", "d", "e", "f")]

        class BASIC(ctypes.Structure):
            _fields_ = [("pu", ctypes.c_int64), ("ju", ctypes.c_int64), ("flags", ctypes.c_uint32),
                        ("minws", ctypes.c_size_t), ("maxws", ctypes.c_size_t), ("apl", ctypes.c_uint32),
                        ("aff", ctypes.c_size_t), ("prio", ctypes.c_uint32), ("sched", ctypes.c_uint32)]

        class EXT(ctypes.Structure):
            _fields_ = [("basic", BASIC), ("io", IO), ("pm", ctypes.c_size_t), ("jm", ctypes.c_size_t),
                        ("pk", ctypes.c_size_t), ("pj", ctypes.c_size_t)]
        k.CreateJobObjectW.restype = ctypes.c_void_p
        job = k.CreateJobObjectW(None, None)
        info = EXT()
        info.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
        k.SetInformationJobObject(ctypes.c_void_p(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        return job
    except Exception:
        return None


JOB = make_job()


def add_to_job(proc):
    if JOB:
        try:
            ctypes.windll.kernel32.AssignProcessToJobObject(ctypes.c_void_p(JOB), ctypes.c_void_p(int(proc._handle)))
        except Exception:
            pass


def find_mmproj(model_path):
    """The vision add-on (mmproj-*.gguf) that belongs to a model, if installed."""
    stem = re.sub(r"[-_.](q\d\w*|bf16|f16|f32|iq\d\w*)\.gguf$", "", os.path.basename(model_path), flags=re.I).lower()
    for p in glob.glob(os.path.join(os.path.dirname(model_path), "mmproj*.gguf")):
        if os.path.basename(p).lower().startswith("mmproj-" + stem):
            return p
    return None


class Engine:
    """Owns the llama-server child process."""
    def __init__(self):
        self.proc, self.port, self.model, self.ctx, self.vision = None, None, None, None, False

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, model_path, ctx):
        self.stop()
        self.port, self.model, self.ctx = free_port(), model_path, ctx
        cmd = [ENGINE, "-m", model_path, "-c", str(ctx), "--host", "127.0.0.1", "--port", str(self.port), "-np", "1"]
        mm = find_mmproj(model_path)
        self.vision = bool(mm)
        if mm:  # vision add-on: lets the model see attached images
            cmd += ["--mmproj", mm]
        self.proc = subprocess.Popen(cmd, **BG_PROC, cwd=os.path.dirname(ENGINE),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        add_to_job(self.proc)

    def wait_ready(self, timeout=300):
        end = time.time() + timeout
        while time.time() < end:
            if not self.alive():
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if r.status == 200:
                        return True
            except Exception:
                pass
            time.sleep(0.4)
        return False

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except Exception:
                self.proc.kill()
        self.proc = None


# ---------------------------------------------------------------- "Train": a local library of the user's code
STOP = set("the a an and or to of in is it for on with this that be as at by from me my i you your can please make write "
           "create add use using how what why do does want need like some file code".split())


def tokenize(text):
    out = []
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        low = ident.lower()
        if len(low) > 1 and low not in STOP:
            out.append(low)
        parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", ident)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts if len(p) > 1 and p.lower() not in STOP)
    return out


WEB_LANGS = {"HTML", "CSS", "SCSS", "LESS", "JavaScript", "TypeScript", "React JSX", "React TSX", "Vue", "SVG"}
LANG_WORDS = [  # words in a request -> which languages' examples are relevant
    (r"\b(html|css|scss|web ?page|website|landing|frontend|front-end|ui|layout|navbar|nav|button|buttons|form|tailwind|dom|"
     r"pricing|hero|section|card|cards|toggle|switch|spinner|loader|modal|tooltip|footer|header|gallery|dashboard|"
     r"portfolio|template|page|component|components|animation|gradient|glass\w*|neon|brutal\w*|pastel|theme|style)\b", WEB_LANGS),
    (r"\b(javascript|js|typescript|ts|react|vue|node)\b", WEB_LANGS),
    (r"\b(python|py|django|flask|pandas|pip)\b", {"Python"}), (r"\brust|cargo\b", {"Rust"}), (r"\bjava\b", {"Java"}),
    (r"c\+\+|\bcpp\b", {"C++", "C++ header"}), (r"c#|\bcsharp\b|\.net\b", {"C#"}), (r"\bgo(lang)?\b", {"Go"}),
    (r"\bphp\b", {"PHP"}), (r"\bruby|rails\b", {"Ruby"}), (r"\bsql|database|query\b", {"SQL"}),
    (r"\bbash|shell\b", {"Bash"}), (r"\bpowershell\b", {"PowerShell"}), (r"\bkotlin\b", {"Kotlin"}), (r"\bswift\b", {"Swift"}),
    (r"\blua\b", {"Lua"}), (r"\bdart|flutter\b", {"Dart"}),
]


def wanted_langs(text, path=""):
    """Languages a request is about, from its words and the open file (empty set = unknown)."""
    out = set()
    low = text.lower()
    for pat, langs in LANG_WORDS:
        if re.search(pat, low):
            out |= langs
    if path:
        name = LANG_INFO.get(os.path.splitext(path)[1].lower(), (None, None))[1]
        if name:
            out |= WEB_LANGS if name in WEB_LANGS else {name}
    return out


STYLE_SYNONYMS = {"glassmorphism": "glass", "glassy": "glass", "frosted": "glass", "brutalist": "brutal", "brutalism": "brutal",
                  "neobrutalism": "brutal", "cyberpunk": "neon", "synthwave": "neon", "90s": "retro", "windows95": "retro",
                  "win95": "retro", "elegant": "luxury", "gold": "luxury", "nature": "earthy", "eco": "earthy", "organic": "earthy",
                  "saas": "darksaas", "startup": "darksaas", "clean": "minimal", "simple": "minimal", "soft": "pastel",
                  "cute": "pastel", "google": "material", "spinner": "loaders", "loader": "loaders", "loading": "loaders",
                  "faq": "accordion", "switch": "toggle", "testimonials": "testimonial", "nav": "navbar", "menu": "dropdown"}


class Library:
    """Code you feed Profound. Relevant pieces are given to the AI as examples to learn from (retrieval)."""
    def __init__(self):
        os.makedirs(TRAIN_DIR, exist_ok=True)
        self.index_path = os.path.join(TRAIN_DIR, "library.json")
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.items = json.load(f)
        except Exception:
            self.items = []
        self.reindex()

    def save(self):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, indent=1)

    def text_of(self, it):
        try:
            with open(os.path.join(TRAIN_DIR, it["id"] + ".txt"), "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""

    def add(self, name, text, lang, source="", save=True):
        iid = uuid.uuid4().hex[:12]
        with open(os.path.join(TRAIN_DIR, iid + ".txt"), "w", encoding="utf-8") as f:
            f.write(text)
        self.items.append({"id": iid, "name": name, "lang": lang, "source": source, "chars": len(text),
                           "added": time.strftime("%Y-%m-%d"), "enabled": True})
        if save:
            self.save()

    def remove(self, iid):
        self.items = [i for i in self.items if i["id"] != iid]
        try:
            os.remove(os.path.join(TRAIN_DIR, iid + ".txt"))
        except OSError:
            pass
        self.save()
        self.reindex()

    def set_enabled(self, iid, v):
        for i in self.items:
            if i["id"] == iid:
                i["enabled"] = v
        self.save()
        self.reindex()

    def reindex(self):
        self.chunks, self.df = [], Counter()
        for it in self.items:
            if not it.get("enabled", True):
                continue
            lines = self.text_of(it).split("\n")
            for s in range(0, max(1, len(lines)), 45):
                chunk = "\n".join(lines[s:s + 60]).strip()
                if not chunk:
                    continue
                toks = Counter(tokenize(chunk + " " + it["name"]))
                self.chunks.append((it, chunk, toks, sum(toks.values()) or 1))
                self.df.update(set(toks))
        self.avgdl = (sum(c[3] for c in self.chunks) / len(self.chunks)) if self.chunks else 1

    def import_starter(self):
        """Add Profound's bundled examples once: hand-made pages, hundreds of CSS components (training_pack/css)
        and page templates (training_pack/templates). Returns how many were added."""
        root = os.path.join(RES_DIR, "training_pack")
        have = {i.get("source") for i in self.items}
        added = 0
        for p in sorted(glob.glob(os.path.join(root, "**", "*.*"), recursive=True)):
            rel = os.path.relpath(p, root).replace("\\", "/")
            src = "starter:" + rel if "/" in rel else "starter:" + os.path.basename(p)
            ext = os.path.splitext(p)[1].lower()
            if src in have or ext not in LANG_INFO:
                continue
            with open(p, "r", encoding="utf-8") as f:
                self.add(rel, f.read(), LANG_INFO[ext][1], src, save=False)
            added += 1
        if added:
            self.save()
        self.reindex()
        return added

    def search(self, query, lang=None, k=3, budget=6000, langs=None, min_score=0.0):
        """Best-matching chunks. langs: only these languages; otherwise only matches scoring >= min_score."""
        q = set(tokenize(query))
        q |= {STYLE_SYNONYMS[t] for t in q if t in STYLE_SYNONYMS}  # e.g. "glassmorphism" also finds "glass" examples
        if not q or not self.chunks:
            return []
        n = len(self.chunks)
        scored = []
        for it, chunk, toks, dl in self.chunks:
            if langs and it.get("lang") not in langs:
                continue
            s = 0.0
            for t in q:
                f = toks.get(t)
                dft = self.df[t]
                if not f and len(t) >= 3:  # partial words: "slug" matches "slugify"
                    f = sum(c for k, c in toks.items() if k.startswith(t)) * 0.7
                    dft = max(1, dft)
                if f:
                    idf = math.log(1 + (n - dft + 0.5) / (dft + 0.5))
                    s += idf * f * 2.4 / (f + 1.4 * (0.25 + 0.75 * dl / self.avgdl))
            if s > 0:
                if lang and it.get("lang", "").lower() == lang.lower():
                    s *= 1.4
                if langs or s >= min_score:
                    scored.append((s, it, chunk))
        scored.sort(key=lambda x: -x[0])
        out, used = [], 0
        for s, it, chunk in scored:
            if len(out) >= k or used + len(chunk) > budget:
                continue
            out.append((it, chunk))
            used += len(chunk)
        return out


# ---------------------------------------------------------------- live HTML preview (served locally, embedded as a tab)
PREVIEW_JS = """<script>(function(){
document.title='PROFOUND_PREVIEW___PORT__';
try{var y=sessionStorage.getItem('pf_scroll');if(y!==null){sessionStorage.removeItem('pf_scroll');addEventListener('load',function(){scrollTo(0,+y)});}}catch(e){}
function report(m){try{fetch('/__err',{method:'POST',body:String(m).slice(0,400)})}catch(e){}}
addEventListener('error',function(e){if(e.message){report(e.message+(e.lineno?' (line '+e.lineno+')':''));}
 else if(e.target&&(e.target.src||e.target.href)){report('Could not load '+(e.target.src||e.target.href).replace(location.origin+'/',''));}},true);
addEventListener('unhandledrejection',function(e){report('Unhandled promise: '+((e.reason&&e.reason.message)||e.reason));});
var ce=console.error;console.error=function(){report([].slice.call(arguments).join(' '));ce.apply(console,arguments);};
var v=null,c=null,T='PROFOUND_PREVIEW___PORT__';
addEventListener('DOMContentLoaded',function(){document.title=T;});
setInterval(function(){if(document.title!==T)document.title=T;fetch('/__v',{cache:'no-store'}).then(function(r){return r.text()}).then(function(t){
 var p=t.split(':');
 if(v!==null&&p[0]!==v){try{sessionStorage.setItem('pf_scroll',scrollY)}catch(e){}location.reload();return;}
 if(c!==null&&p[1]!==c){document.querySelectorAll('link[rel=stylesheet]').forEach(function(l){l.href=l.href.split('?')[0]+'?v='+p[1];});}
 v=p[0];c=p[1];}).catch(function(){})},500);
})();</script>"""


class Preview:
    """Serves the page you're editing (including unsaved changes). CSS changes hot-swap without a reload,
    other changes reload while keeping the scroll position, and page errors are reported back to the app."""
    def __init__(self, app):
        self.app, self.version, self.css_version, self.buffers = app, 0, 0, {}
        self.page, self.snippet, self.errors = None, None, []
        self.port = free_port()
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def _handler(self):
        pv = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
                    return self.send(403, b"", "text/plain")
                path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
                if path == "/__v":
                    return self.send(200, f"{pv.version}:{pv.css_version}".encode(), "text/plain")
                if path == "/":
                    html = pv.snippet if pv.snippet is not None else pv.buffers.get(pv.page)
                    if html is None:
                        html = (pv.read_disk(pv.page) if pv.page else None) or \
                               "<body style='font-family:Segoe UI;color:#888;display:grid;place-items:center;height:90vh'>Open an HTML file to preview it</body>"
                    b = html.encode("utf-8")
                    js = PREVIEW_JS.replace("__PORT__", str(pv.port)).encode()
                    i = b.lower().find(b"<head>")  # as early as possible, so errors during page load are caught too
                    if i > -1:
                        b = b[:i + 6] + js + b[i + 6:]
                    else:
                        b = js + b
                    return self.send(200, b, "text/html; charset=utf-8")
                base = os.path.dirname(pv.page or "") if pv.snippet is None else ""
                rel = os.path.normpath(os.path.join(base, path.lstrip("/"))).replace("\\", "/")
                ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
                if rel in pv.buffers:
                    return self.send(200, pv.buffers[rel].encode("utf-8"), ctype + "; charset=utf-8")
                data = pv.read_disk(rel, binary=True)
                if data is None:
                    return self.send(404, b"not found", "text/plain")
                self.send(200, data, ctype)

            def do_POST(self):
                if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost") or self.path != "/__err":
                    return self.send(403, b"", "text/plain")
                msg = self.rfile.read(min(2000, int(self.headers.get("Content-Length", 0)))).decode("utf-8", "replace").strip()
                if msg and msg not in pv.errors and len(pv.errors) < 30:
                    pv.errors.append(msg)
                    pv.app.q.put(("pverr",))
                self.send(204, b"", "text/plain")
        return H

    def read_disk(self, rel, binary=False):
        try:
            p = self.app.abs_path(rel)
            with open(p, "rb") as f:
                d = f.read()
            return d if binary else d.decode("utf-8", "replace")
        except Exception:
            return None

    def sync(self):
        """UI thread: snapshot open web files. CSS-only edits hot-swap; anything else reloads the page."""
        new = {t.path: t.content() for t in self.app.tabs if isinstance(t, EditorTab) and os.path.splitext(t.path)[1].lower() in WEB_EXT}
        if new != self.buffers:
            changed = {k for k in set(new) | set(self.buffers) if new.get(k) != self.buffers.get(k)}
            self.buffers = new
            if changed and all(k.lower().endswith(".css") for k in changed):
                self.css_version += 1
            else:
                self.bump()

    def bump(self):
        self.version += 1
        if self.errors:
            self.errors = []
            self.app.q.put(("pverr",))

    def set_page(self, page=None, snippet=None):
        if page:
            self.page = page
        self.snippet = snippet
        self.sync()
        self.bump()


# ---------------------------------------------------------------- VS Code / VSCodium bridge
BRIDGE_PORT = 39291
VSIX_TYPES = ('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension=".json" ContentType="application/json"/><Default Extension=".js" ContentType="application/javascript"/>'
              '<Default Extension=".png" ContentType="image/png"/><Default Extension=".svg" ContentType="image/svg+xml"/>'
              '<Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>')
VSIX_MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="profound" Version="1.0.0" Publisher="profound"/>
    <DisplayName>Profound</DisplayName>
    <Description xml:space="preserve">Offline AI coding assistant powered by the Profound desktop app.</Description>
    <Categories>Programming Languages,Other</Categories>
    <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.70.0"/></Properties>
    <Icon>extension/icon.png</Icon>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/icon.png" Addressable="true"/>
  </Assets>
</PackageManifest>"""
REWRITE_SYSTEM = (BASE_RULES + " You are editing code inside the user's editor. Return the COMPLETE updated code in exactly one "
                  "fenced code block, followed by at most two short sentences about what changed.")


def build_vsix(out_path):
    import zipfile
    src = os.path.join(RES_DIR, "vscode_ext")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", VSIX_TYPES)
        z.writestr("extension.vsixmanifest", VSIX_MANIFEST)
        for f in os.listdir(src):
            z.write(os.path.join(src, f), "extension/" + f)
    return out_path


def find_editor_cli(kind):
    la, pf = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")
    if kind == "code":
        cands = [shutil.which("code"), os.path.join(la, "Programs", "Microsoft VS Code", "bin", "code.cmd"),
                 os.path.join(pf, "Microsoft VS Code", "bin", "code.cmd"),
                 "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
                 shutil.which("code-oss"), "/opt/visual-studio-code/bin/code"]
    else:
        cands = [shutil.which("codium"), os.path.join(la, "Programs", "VSCodium", "bin", "codium.cmd"),
                 os.path.join(pf, "VSCodium", "bin", "codium.cmd"), shutil.which("vscodium"),
                 "/Applications/VSCodium.app/Contents/Resources/app/bin/codium", "/opt/vscodium-bin/bin/codium"]
    return next((c for c in cands if c and os.path.exists(c)), None)


class Bridge:
    """Local API so the VS Code / VSCodium extension can use Profound's AI (127.0.0.1 only)."""
    def __init__(self, app):
        self.app, self.ok = app, False
        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), self._handler())
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.ok = True
        except OSError:
            pass  # another Profound window already serves the bridge

    def _handler(self):
        br = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def allowed(self):
                # The custom header blocks web pages (browsers can't send it cross-site without a preflight we never answer)
                return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost") and self.headers.get("X-Profound") == "1"

            def do_GET(self):
                if not self.allowed():
                    return self.send(403, b"{}")
                if self.path == "/api/status":
                    a = br.app
                    m = a.engine.model
                    return self.send(200, json.dumps({"ready": a.ready, "model": pretty_model(os.path.basename(m)) if m else ""}).encode())
                self.send(404, b"{}")

            def do_POST(self):
                if not self.allowed() or self.path != "/api/ask":
                    return self.send(403, b"{}")
                try:
                    p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                except ValueError:
                    return self.send(400, b"bad request", "text/plain")
                a = br.app
                if not a.ready:
                    return self.send(503, "Profound's AI is still loading. Try again in a moment.".encode(), "text/plain")
                mode = p.get("mode", "ask")
                sysmsg = REWRITE_SYSTEM if mode == "rewrite" else ASK_SYSTEM
                extra, ex_txt, _ = a.extras(p.get("prompt", ""), p.get("file", ""))
                user = p.get("prompt", "")
                if p.get("code"):
                    what = "Selected code" if p.get("selection") else "Current file"
                    user += f"\n\n{what} ({p.get('file', '')}, {p.get('language', '')}):\n```{p.get('language', '')}\n{p['code'][:14000]}\n```"
                if ex_txt:
                    user += "\n\n---\n" + ex_txt
                body = {"messages": [{"role": "system", "content": sysmsg + extra}, {"role": "user", "content": user}],
                        "stream": True, "temperature": a.S["temp"],
                        "chat_template_kwargs": {"enable_thinking": bool(a.S.get("deepThink"))}}
                if a.S["maxTok"] > 0:
                    body["max_tokens"] = a.S["maxTok"]
                a.q.put(("bridge", mode))
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{a.engine.port}/v1/chat/completions",
                                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=900) as r:
                        for raw in r:
                            line = raw.decode("utf-8", "replace").strip()
                            if not line.startswith("data:"):
                                continue
                            d = line[5:].strip()
                            if d == "[DONE]":
                                break
                            tok = json.loads(d)["choices"][0].get("delta", {}).get("content")
                            if tok:
                                self.wfile.write(tok.encode("utf-8"))
                                self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    try:
                        self.wfile.write(f"\n[Profound error: {e}]".encode())
                    except OSError:
                        pass
        return H


# ---- Win32 helpers for embedding the preview window inside the app
U32 = ctypes.windll.user32 if WIN else None
if WIN:
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    U32.SetParent.argtypes = [wt.HWND, wt.HWND]
    U32.MoveWindow.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
    U32.IsWindow.argtypes = [wt.HWND]
    U32.GetWindowTextW.argtypes = [wt.HWND, ctypes.c_wchar_p, ctypes.c_int]
    try:
        U32.GetWindowLongPtrW.restype = ctypes.c_longlong
        U32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        U32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_longlong]
    except AttributeError:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


if WIN:
    U32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
    U32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
    U32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(POINT)]
    U32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    U32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    U32.RedrawWindow.argtypes = [wt.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]


if WIN:
    U32.LoadImageW.restype = wt.HANDLE
    U32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    U32.SendMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
    U32.SendMessageW.restype = ctypes.c_ssize_t


def set_crisp_icon(win):
    """Give Windows the icon at the exact pixel sizes it draws (taskbar + title bar), so it never rescales (no blur)."""
    if not WIN:
        return
    try:
        ico = os.path.join(RES_DIR, "icon.ico")
        win.update_idletasks()
        hwnd = U32.GetParent(win.winfo_id()) or win.winfo_id()
        try:
            dpi = U32.GetDpiForWindow(hwnd) or 96
        except AttributeError:
            dpi = 96
        for which, base in ((1, 24), (0, 16)):  # ICON_BIG -> taskbar size, ICON_SMALL -> title bar size
            px = round(base * dpi / 96)
            h = U32.LoadImageW(None, ico, 1, px, px, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                U32.SendMessageW(hwnd, 0x0080, which, h)  # WM_SETICON
    except Exception as e:
        log_error(f"icon: {e}")


EDGE_TITLE_PX = 30  # height of the title strip Edge draws inside app windows (at 100% scaling)


def find_window_titled(prefix):
    found = []

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(256)
        U32.GetWindowTextW(h, buf, 256)
        if buf.value.startswith(prefix):
            found.append(h)
        return True
    U32.EnumWindows(EnumProc(cb), 0)
    return found[0] if found else None


# ---------------------------------------------------------------- image thumbnails + file drop
_THUMB_CACHE = {}


def _to_png(path, max_px):
    """Convert JPG/BMP/WebP etc. to a small PNG Tk can show (Tk itself only reads PNG/GIF)."""
    out = os.path.join(tempfile.gettempdir(), f"profound_thumb_{abs(hash((path, max_px)))}.png")
    if os.path.exists(out):
        return out
    try:
        if sys.platform == "win32":
            ps = ("Add-Type -AssemblyName System.Drawing;"
                  f"$i=[System.Drawing.Image]::FromFile('{path.replace(chr(39), chr(39) * 2)}');"
                  f"$k=[Math]::Min(1.0,{max_px}/[Math]::Max($i.Width,$i.Height));"
                  "$b=New-Object System.Drawing.Bitmap ([int][Math]::Max(1,$i.Width*$k)),([int][Math]::Max(1,$i.Height*$k));"
                  "$g=[System.Drawing.Graphics]::FromImage($b);$g.InterpolationMode='HighQualityBicubic';"
                  "$g.DrawImage($i,0,0,$b.Width,$b.Height);"
                  f"$b.Save('{out}',[System.Drawing.Imaging.ImageFormat]::Png)")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=20, creationflags=NO_WINDOW)
        elif sys.platform == "darwin":
            subprocess.run(["sips", "-s", "format", "png", "-Z", str(max_px), path, "--out", out], capture_output=True, timeout=20)
        else:
            tool = shutil.which("magick") or shutil.which("convert")
            if tool:
                subprocess.run([tool, path, "-thumbnail", f"{max_px}x{max_px}", out], capture_output=True, timeout=20)
    except Exception:
        return None
    return out if os.path.exists(out) else None


def make_thumb(path, max_px):
    """A PhotoImage of the picture that fits in max_px (None if it can't be shown)."""
    key = (path, max_px)
    if key in _THUMB_CACHE:
        return _THUMB_CACHE[key]
    img = None
    try:
        ext = os.path.splitext(path)[1].lower()
        src = path if ext in (".png", ".gif") else _to_png(path, max_px)
        if src:
            img = tk.PhotoImage(file=src)
            w, h = img.width(), img.height()
            big = max(w, h)
            if big > max_px:
                img = img.subsample(math.ceil(big / max_px))
            elif big * 2 <= max_px and big <= 64:  # tiny pixel art: enlarge crisply
                img = img.zoom(max(1, max_px // 2 // big))
    except Exception:
        img = None
    _THUMB_CACHE[key] = img
    return img


def enable_file_drop(root, deliver):
    """Accept files dropped on the window. deliver(files) must NOT touch Tk (it may run inside Windows' message
    loop); it should just queue them. Windows: native drag & drop via a message hook. Elsewhere: tkinterdnd2."""
    if sys.platform == "win32":
        try:
            shell32, k32 = ctypes.windll.shell32, ctypes.windll.kernel32
            shell32.DragAcceptFiles.argtypes = [wt.HWND, wt.BOOL]
            shell32.DragQueryFileW.argtypes = [wt.HANDLE, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]
            shell32.DragQueryFileW.restype = ctypes.c_uint
            shell32.DragFinish.argtypes = [wt.HANDLE]
            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
            U32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
            U32.SetWindowsHookExW.restype = wt.HHOOK
            U32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
            U32.CallNextHookEx.restype = ctypes.c_ssize_t

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", wt.HWND), ("message", ctypes.c_uint), ("wParam", wt.WPARAM), ("lParam", wt.LPARAM),
                            ("time", wt.DWORD), ("pt", wt.POINT), ("lPrivate", wt.DWORD)]

            def hook(code, wp, lp):
                if code >= 0 and wp == 1:  # a message being removed from the queue (PM_REMOVE)
                    m = ctypes.cast(lp, ctypes.POINTER(MSG)).contents
                    if m.message == 0x0233:  # WM_DROPFILES
                        hdrop = m.wParam
                        files = []
                        for i in range(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)):
                            ln = shell32.DragQueryFileW(hdrop, i, None, 0)
                            buf = ctypes.create_unicode_buffer(ln + 1)
                            shell32.DragQueryFileW(hdrop, i, buf, ln + 1)
                            files.append(buf.value)
                        shell32.DragFinish(hdrop)
                        m.message = 0  # turn it into WM_NULL so nothing else handles it
                        deliver(files)
                return U32.CallNextHookEx(None, code, wp, lp)
            root._drop_hook_proc = HOOKPROC(hook)  # keep a reference
            root._drop_hook = U32.SetWindowsHookExW(3, root._drop_hook_proc, None, k32.GetCurrentThreadId())  # WH_GETMESSAGE
            shell32.DragAcceptFiles(U32.GetParent(root.winfo_id()) or root.winfo_id(), True)
            return True
        except Exception as e:
            log_error(f"drag and drop: {e}")
            return False
    try:
        from tkinterdnd2 import DND_FILES  # optional add-on on Linux / macOS
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", lambda e: deliver(list(root.tk.splitlist(e.data))))
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- widgets
class RoundButton(tk.Canvas):
    """Rounded, flat button. kinds: soft, ghost, accent, seg, code, chip"""
    all = []

    def __init__(self, parent, text, command=None, kind="soft", font=UI, padx=14, pady=7, radius=10, width=None, bg=None,
                 icon=None, icon_size=14):
        self.text_, self.command, self.kind, self.fnt = text, command, kind, tkfont.Font(font=font)
        self.icon, self.isz = icon, icon_size
        self.padx, self.pady, self.radius, self.fixed_w = padx, pady, radius, width
        self.enabled, self.selected, self.hover = True, False, False
        self.pbg = bg or parent.cget("bg")
        w, h = self._size()
        super().__init__(parent, width=w, height=h, bg=self.pbg, highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<ButtonRelease-1>", self._click)
        RoundButton.all.append(self)
        self.draw()

    def _parts(self):
        tw = self.fnt.measure(self.text_) if self.text_ else 0
        iw = self.isz if self.icon else 0
        gap = 7 if (self.icon and self.text_) else 0
        return tw, iw, gap

    def _size(self):
        tw, iw, gap = self._parts()
        lh = self.fnt.metrics("linespace") if self.text_ else 0
        return (self.fixed_w or tw + iw + gap + 2 * self.padx), max(lh, iw) + 2 * self.pady

    def _h(self, v):
        self.hover = v
        self.draw()

    def _click(self, e):
        if self.enabled and self.command and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def colors(self):
        a = THEME["accent"]
        if self.kind == "accent" or (self.kind == "seg" and self.selected):
            return a, "#08111f", shade(a, 0.15)
        return {"ghost": (self.pbg, FG, PANEL2), "seg": (self.pbg, MUTED, HOVER), "code": (CODE_BTN, MUTED, HOVER),
                "chip": (PANEL2, FG, HOVER)}.get(self.kind, (PANEL2, FG, HOVER))

    def draw(self):
        try:
            bg, fg, hb = self.colors()
            fill = hb if (self.hover and self.enabled) else bg
            self.delete("all")
            w, h = int(self.cget("width")), int(self.cget("height"))
            if fill != self.pbg:
                rrect(self, 0, 0, w - 1, h - 1, self.radius, fill=fill, outline=fill)
            col = fg if self.enabled else DIM
            tw, iw, gap = self._parts()
            x0 = (w - (tw + iw + gap)) / 2
            if self.icon:
                draw_icon(self, self.icon, x0, (h - iw) / 2, iw, col)
            if self.text_:
                self.create_text(x0 + iw + gap, h / 2, text=self.text_, font=self.fnt, fill=col, anchor="w")
            self.configure(cursor="hand2" if self.enabled else "arrow")
        except tk.TclError:
            pass

    def set_text(self, t, icon="keep"):
        self.text_ = t
        if icon != "keep":
            self.icon = icon
        w, h = self._size()
        self.configure(width=w, height=h)
        self.draw()

    def set_enabled(self, v):
        self.enabled = v
        self.draw()

    def set_selected(self, v):
        self.selected = v
        self.draw()

    @classmethod
    def repaint_all(cls):
        cls.all = [b for b in cls.all if b.winfo_exists()]
        for b in cls.all:
            b.draw()


class Card(tk.Canvas):
    """Rounded panel. Put widgets in .inner"""
    def __init__(self, parent, fill=CARD, radius=14, padx=14, pady=10, outline=None, fit_width=False, bg=None):
        super().__init__(parent, bg=bg or parent.cget("bg"), highlightthickness=0, bd=0, height=2 * pady + 4, width=20)
        self.fill_, self.radius, self.px, self.py, self.outline_, self.fitw = fill, radius, padx, pady, outline, fit_width
        self.inner = tk.Frame(self, bg=fill)
        self.win = self.create_window(padx, pady, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._on_conf)
        self.inner.bind("<Configure>", self._on_inner)

    def _on_conf(self, e):
        if not self.fitw:
            self.itemconfigure(self.win, width=max(10, e.width - 2 * self.px))
        self._draw()

    def _on_inner(self, _):
        h = self.inner.winfo_reqheight() + 2 * self.py
        if int(self.cget("height")) != h:
            self.configure(height=h)
        if self.fitw:
            w = self.inner.winfo_reqwidth() + 2 * self.px
            if int(self.cget("width")) != w:
                self.configure(width=w)
        self._draw()

    def _draw(self):
        self.delete("shape")
        w = self.winfo_width() if not self.fitw else int(self.cget("width"))
        h = int(self.cget("height"))
        if w < 4:
            return
        o = self.outline_ or self.fill_
        rrect(self, 1, 1, w - 2, h - 2, self.radius, fill=self.fill_, outline=o, width=1.5 if self.outline_ else 1, tags="shape")
        self.tag_lower("shape")

    def set_outline(self, c):
        self.outline_ = c
        self._draw()


class Toggle(tk.Canvas):
    """iOS-style switch bound to a BooleanVar."""
    all = []

    def __init__(self, parent, variable, command=None, bg=None):
        super().__init__(parent, width=40, height=22, bg=bg or parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self.var, self.command = variable, command
        self.bind("<Button-1>", self._toggle)
        variable.trace_add("write", lambda *a: self.draw())
        Toggle.all.append(self)
        self.draw()

    def _toggle(self, _):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        try:
            on = self.var.get()
            self.delete("all")
            col = THEME["accent"] if on else "#36433a"
            rrect(self, 1, 1, 39, 21, 10, fill=col, outline=col)
            x = 29 if on else 11
            self.create_oval(x - 7, 4, x + 7, 18, fill="#ffffff", outline="")
        except tk.TclError:
            pass


class ScrollFrame(tk.Frame):
    """Vertically scrolling area; add widgets to .inner"""
    def __init__(self, parent, bg):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=24)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview, style="Slim.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.stick = False  # True = keep the view on the last message while content is still laying out
        self.sb.configure(command=self._on_bar)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Configure>", self._on_inner)
        self.wheel(self.canvas)
        self.wheel(self.inner)
        self.after(400, self._guard)

    def _on_bar(self, *args):
        self.canvas.yview(*args)
        self.stick = self.at_bottom()  # dragging up to read back stops following; dragging to the end follows again

    def _guard(self):
        """Safety net: never leave the view in empty space past the last message (and keep following when sticking)."""
        try:
            if not self.winfo_exists():
                return
            ih, ch = self.inner.winfo_height(), self.canvas.winfo_height()
            if ih <= ch:
                if self.canvas.canvasy(0) > 0:
                    self.canvas.yview_moveto(0)
            else:
                gap = self.canvas.canvasy(ch) - ih
                if gap > 2:
                    self.canvas.yview_moveto(1.0)
            self.after(400, self._guard)
        except tk.TclError:
            pass

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        self._settle()

    def _on_inner(self, e):
        self.canvas.configure(scrollregion=(0, 0, e.width, e.height))
        self._settle()

    def _settle(self):
        """Never leave the view parked in empty space past the end; follow the last message when sticking."""
        ih, ch = self.inner.winfo_height(), self.canvas.winfo_height()
        if ih <= ch:
            self.canvas.yview_moveto(0)
        elif self.stick or self.canvas.canvasy(ch) > ih:
            self.canvas.yview_moveto(1.0)

    def wheel(self, w):
        w.bind("<MouseWheel>", self._on_wheel)
        if LINUX:
            w.bind("<Button-4>", self._on_wheel)
            w.bind("<Button-5>", self._on_wheel)

    def wheel_tree(self, w):
        self.wheel(w)
        for c in w.winfo_children():
            self.wheel_tree(c)

    def _on_wheel(self, e):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(wheel_steps(e) * 2, "units")
        self.stick = self.at_bottom()  # scrolling up lets you read back; scrolling to the end follows again
        return "break"

    def at_bottom(self):
        return self.canvas.yview()[1] > 0.985

    def bottom(self):
        """Go to the last message, and keep following it while messages finish laying out."""
        self.stick = True
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)
        for ms in (60, 200, 500):
            self.after(ms, lambda: self.stick and self.canvas.yview_moveto(1.0))


def auto_text(parent, bg, fg=FG, font=CHAT_FONT, wrap="word"):
    """Read-only Text that grows to fit its content (selectable, copyable)."""
    t = tk.Text(parent, bg=bg, fg=fg, font=font, wrap=wrap, borderwidth=0, highlightthickness=0, width=1, height=1,
                padx=0, pady=0, cursor="xterm", insertwidth=0, selectbackground="#2b4a31", spacing1=1, spacing3=1)
    t._lastw, t._maxh = 0, None

    def fit():
        try:
            if wrap == "none" or t.winfo_width() < 40:
                # before it has a real width every character would "wrap", giving a giant height; use line count instead
                n = int(t.index("end-1c").split(".")[0])
            else:
                n = int(t.tk.call(t._w, "count", "-update", "-displaylines", "1.0", "end-1c") or 0) + 1
        except tk.TclError:
            n = int(t.index("end-1c").split(".")[0])
        h = min(n, t._maxh) if t._maxh else n
        if int(t.cget("height")) != max(1, h):
            t.configure(height=max(1, h))

    def on_conf(e):
        if e.width != t._lastw:
            t._lastw = e.width
            fit()
    t.fit = fit
    t.bind("<Configure>", on_conf, add="+")
    t.bind("<Key>", lambda e: None if (e.state & 0x4 and e.keysym.lower() in ("c", "a")) else "break")
    return t


# ---------------------------------------------------------------- syntax colours
def kw(words):
    return r"\b(?:" + "|".join(sorted(set(words.split()), key=len, reverse=True)) + r")\b"


C_KW = ("if else for while do switch case break continue return function func fn def class struct enum interface implements "
        "extends new delete this self super null nil None true false try catch finally throw throws import from export default "
        "package using namespace public private protected internal static final const let var val mut async await yield typeof "
        "instanceof in of is as void int long short float double char bool boolean string byte unsigned signed auto match impl "
        "trait pub mod use where type go defer chan select range lambda override virtual abstract sealed readonly get set echo "
        "require include foreach elseif when fun object companion data sizeof template typename operator crate loop unsafe dyn")
PY_KW = ("def class return if elif else for while import from as with try except finally raise in is not and or None True False "
         "lambda yield pass break continue global nonlocal async await del assert self print match case")
SH_KW = "if then fi else elif for do done while case esac function in echo export local return param foreach exit set call goto"
SQL_KW = ("select from where insert into values update set delete create table drop alter add primary key foreign references join "
          "left right inner outer on group by order having limit offset as and or not null is in like between distinct count sum avg "
          "min max index view union all exists case when then else end default unique")
LUA_KW = "function local end if then else elseif for in do while repeat until return break nil true false and or not"
HASH_KW = "def end class module if elsif else unless while until for in do return yield nil true false self require puts my sub use function library"
STR_C = r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`"
STR_PY = r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|[fbru]?\"(?:\\.|[^\"\\\n])*\"|[fbru]?'(?:\\.|[^'\\\n])*'"
NUM = r"\b\d+(?:\.\d+)?\b"
RULES = {
    "py": [("kw", kw(PY_KW), re.M), ("num", NUM, re.M), ("fn", r"(?<=def )\w+|(?<=class )\w+", re.M), ("attr", r"^\s*@\w+", re.M),
           ("str", STR_PY, re.M), ("com", r"#[^\n]*", re.M)],
    "c": [("kw", kw(C_KW), re.M), ("num", NUM, re.M), ("fn", r"\b[A-Za-z_]\w*(?=\s*\()", re.M), ("attr", r"^\s*#\s*\w+|@\w+", re.M),
          ("str", STR_C, re.M), ("com", r"//[^\n]*|/\*[\s\S]*?\*/", re.M)],
    "sh": [("kw", kw(SH_KW), re.M | re.I), ("num", NUM, re.M), ("attr", r"\$\{?[\w:]+\}?|%\w+%|-\w+(?=\s)", re.M),
           ("str", r"\"(?:\\.|[^\"\\])*\"|'[^']*'", re.M), ("com", r"<#[\s\S]*?#>|#[^\n]*|^\s*(?:rem|REM|::)[^\n]*", re.M)],
    "sql": [("kw", kw(SQL_KW), re.M | re.I), ("num", NUM, re.M), ("str", r"'(?:''|[^'])*'", re.M), ("com", r"--[^\n]*|/\*[\s\S]*?\*/", re.M)],
    "lua": [("kw", kw(LUA_KW), re.M), ("num", NUM, re.M), ("fn", r"\b\w+(?=\s*\()", re.M), ("str", STR_C, re.M),
            ("com", r"--\[\[[\s\S]*?\]\]|--[^\n]*", re.M)],
    "hash": [("kw", kw(HASH_KW), re.M), ("num", NUM, re.M), ("attr", r"[@$]\w+|:\w+", re.M), ("str", STR_C, re.M), ("com", r"#[^\n]*", re.M)],
    "css": [("attr", r"[\w-]+(?=\s*:[^;{]*[;}])", re.M), ("num", r"#[0-9a-fA-F]{3,8}\b|\b\d+(\.\d+)?(px|em|rem|%|vh|vw|s|ms|deg|fr)?\b", re.M),
            ("tag", r"^[^{}\n@]+(?=\{)|@[\w-]+", re.M), ("str", r"\"[^\"\n]*\"|'[^'\n]*'", re.M), ("com", r"/\*[\s\S]*?\*/|(?<!:)//[^\n]*", re.M)],
    "web": [("tag", r"</?[\w:-]+|/?>", re.M), ("attr", r"\s[\w:@.-]+(?==)", re.M), ("str", r"\"[^\"]*\"|'[^']*'", re.M),
            ("com", r"<!--[\s\S]*?-->", re.M)],
    "data": [("kw", r"\b(?:true|false|null|yes|no|on|off)\b", re.M | re.I), ("num", r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", re.M),
             ("attr", r"\"[^\"\n]*\"(?=\s*:)|^\s*[\w.-]+(?=\s*[:=])|^\s*\[[^\]\n]+\]", re.M), ("str", r"\"(?:\\.|[^\"\\\n])*\"|'[^'\n]*'", re.M),
             ("com", r"(?:^|\s)[#;][^\n]*", re.M)],
    "md": [("kw", r"^#{1,6}[^\n]*", re.M), ("attr", r"\*\*[^*\n]+\*\*|__[^_\n]+__", re.M), ("fn", r"\[[^\]\n]+\]\([^)\n]+\)", re.M),
           ("str", r"`[^`\n]+`|^```[\s\S]*?^```", re.M), ("com", r"^>[^\n]*", re.M)],
}
COLORS = {"kw": "#c792ea", "num": "#f78c6c", "fn": "#82aaff", "tag": "#f07178", "attr": "#ffcb6b", "str": "#c3e88d", "com": "#5f6a7d"}


def setup_hl(t, size):
    for k, c in COLORS.items():
        t.tag_configure(k, foreground=c)
    t.tag_configure("com", font=(MONO, size, "italic"))
    t.tag_raise("sel")


def highlight(t, src, fam):
    for k in COLORS:
        t.tag_remove(k, "1.0", "end")
    if not fam or fam not in RULES or len(src) > 150_000:
        return
    starts = [0]
    for i, ch in enumerate(src):
        if ch == "\n":
            starts.append(i + 1)

    def idx(o):
        line = bisect.bisect_right(starts, o) - 1
        return f"{line + 1}.{o - starts[line]}"
    for tag, pat, flags in RULES[fam]:
        for m in re.finditer(pat, src, flags):
            if m.start() != m.end():
                t.tag_add(tag, idx(m.start()), idx(m.end()))


def fam_for(lang="", path=""):
    if path:
        info = LANG_INFO.get(os.path.splitext(path)[1].lower())
        if info:
            return info[0]
    return FENCE_FAM.get((lang or "").lower())


def lang_label(lang="", path=""):
    if path:
        info = LANG_INFO.get(os.path.splitext(path)[1].lower())
        if info:
            return info[1]
    return LANG_NAME.get((lang or "").lower(), (lang or "code").capitalize())


# ---------------------------------------------------------------- editor tab
class EditorTab(tk.Frame):
    kind = "file"

    def __init__(self, app, path, content, saved):
        super().__init__(app.editor_host, bg=EDITOR)
        self.app, self.path, self.saved, self._lines, self._hl_job = app, path, saved, 0, None
        self.fam = fam_for(path=path)
        self.gutter = tk.Text(self, width=5, padx=8, takefocus=0, borderwidth=0, bg=EDITOR, fg=DIM,
                              state="disabled", cursor="arrow", wrap="none", highlightthickness=0, pady=8, spacing1=1, spacing3=1)
        self.text = tk.Text(self, undo=True, wrap="none", bg=EDITOR, fg=FG, insertbackground=THEME["accent"],
                            borderwidth=0, padx=12, pady=8, selectbackground="#2b4a31", highlightthickness=0,
                            insertwidth=2, spacing1=1, spacing3=1)
        self.vs = ttk.Scrollbar(self, orient="vertical", command=self.text.yview, style="Slim.Vertical.TScrollbar")
        self.hs = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview, style="Slim.Horizontal.TScrollbar")
        self.text.configure(yscrollcommand=self._yscroll, xscrollcommand=self.hs.set)
        self.hs.pack(side="bottom", fill="x")
        self.vs.pack(side="right", fill="y")
        self.gutter.pack(side="left", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("curline", background="#151c17")
        setup_hl(self.text, app.S["font"])
        self.gutter.bind("<MouseWheel>", lambda e: "break")
        self.text.bind("<Tab>", lambda e: (self.text.insert("insert", "    "), "break")[1])
        self.text.bind("<Return>", self._newline)
        self.text.bind("<<Modified>>", self._modified)
        for ev in ("<KeyRelease>", "<ButtonRelease-1>"):
            self.text.bind(ev, lambda e: self._curline(), add="+")
        self.set_content(content)
        self.apply_view()

    def title(self):
        return os.path.basename(self.path)

    def _newline(self, _):
        line = self.text.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        if line.rstrip().endswith((":", "{", "(", "[")):
            indent += "    "
        self.text.insert("insert", "\n" + indent)
        self.text.see("insert")
        return "break"

    def _curline(self):
        self.text.tag_remove("curline", "1.0", "end")
        self.text.tag_add("curline", "insert linestart", "insert lineend+1c")

    def _yscroll(self, a, b):
        self.vs.set(a, b)
        self.gutter.yview_moveto(a)

    def _modified(self, _=None):
        if self.text.edit_modified():
            self.text.edit_modified(False)
            self.update_gutter()
            self.app.on_tab_changed(self)
            if self._hl_job:
                self.after_cancel(self._hl_job)
            self._hl_job = self.after(250, lambda: highlight(self.text, self.content(), self.fam))

    def update_gutter(self):
        n = int(self.text.index("end-1c").split(".")[0])
        if n != self._lines:
            self._lines = n
            self.gutter.configure(state="normal", width=max(3, len(str(n))) + 1)
            self.gutter.delete("1.0", "end")
            self.gutter.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)), "r")
            self.gutter.tag_configure("r", justify="right")
            self.gutter.configure(state="disabled")
            self.gutter.yview_moveto(self.text.yview()[0])

    def apply_view(self):
        f = tkfont.Font(family=MONO, size=self.app.S["font"])
        self.text.configure(font=f, tabs=(f.measure("    "),), insertbackground=THEME["accent"])
        self.text.tag_configure("com", font=(MONO, self.app.S["font"], "italic"))
        self.gutter.configure(font=f)
        self._lines = 0
        self.update_gutter()
        if self.app.S["lineNums"]:
            self.gutter.pack(side="left", fill="y", before=self.text)
        else:
            self.gutter.pack_forget()

    def content(self):
        return self.text.get("1.0", "end-1c")

    def set_content(self, s):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", s)
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.update_gutter()
        highlight(self.text, s, self.fam)

    def dirty(self):
        return self.content() != self.saved


class SnippetsTab(tk.Frame):
    """'Code' panel: in Ask mode, code from the chat lands here instead of cluttering the conversation."""
    kind, path, icon = "snippets", "__code__", "code"

    def __init__(self, app):
        super().__init__(app.editor_host, bg=EDITOR)
        self.app, self.cards = app, []
        head = tk.Frame(self, bg=EDITOR)
        head.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(head, text="Code from chat", bg=EDITOR, fg=FG, font=(SANS_SEMI, 15)).pack(side="left")
        RoundButton(head, "Clear", self.clear, kind="soft", font=UI_SM, padx=12, pady=5, icon="trash", icon_size=12).pack(side="right")
        tk.Label(self, text="When you're just chatting (Ask mode), code shows up here so the conversation stays clean.",
                 bg=EDITOR, fg=MUTED, font=UI_SM).pack(anchor="w", padx=22)
        self.sf = ScrollFrame(self, EDITOR)
        self.sf.pack(fill="both", expand=True, padx=(16, 0), pady=10)
        self.empty = tk.Label(self.sf.inner, text="No code yet. Ask a question in Ask mode and code will appear here.",
                              bg=EDITOR, fg=DIM, font=UI)
        self.empty.pack(pady=40)

    def title(self):
        return "Code"

    def dirty(self):
        return False

    def content(self):
        return ""

    def clear(self):
        for c in self.cards:
            c.destroy()
        self.cards = []
        self.empty.pack(pady=40)

    def add(self, code, lang, path, heading, mode="ask"):
        self.empty.pack_forget()
        acts = [("Copy", lambda: self.app.copy(code)), ("Save as file", lambda: self.app.save_snippet(code, lang, path))]
        if (lang or "").lower() in ("html", "htm"):
            acts.append(("Preview", lambda: self.app.show_preview(snippet=code)))
        if mode == "edit" and self.app.workspace:
            acts.append((("Put in " + os.path.basename(path)) if path else "Put in open file", lambda: self.app.apply_code(code, path)))
        card = self.app.code_card(self.sf.inner, code, lang, path, acts, collapsed=False, heading=heading, bg=EDITOR)
        card.code, card.lang = code, (lang or "").lower()
        card.pack_configure(padx=(0, 14), pady=(0, 14))
        self.sf.wheel_tree(card)
        self.cards.append(card)
        return card

    @staticmethod
    def family(lang):
        lang = (lang or "").lower()
        return "web" if lang in ("html", "htm", "css", "javascript", "js", "") else lang

    def working(self, lang=None):
        """The file we keep editing in chat (the latest finished live card, optionally of a language family)."""
        for c in reversed(self.cards):
            if getattr(c, "status", None) is not None and c.winfo_exists() and c.done and c.code.strip():
                if lang is None or self.family(c.lang) == self.family(lang):
                    return c
        return None

    def reuse_live(self, lang, path, heading):
        """Rewrite the working file in place (same kind of code) instead of piling up new cards."""
        fam = self.family(lang)
        card = None
        for c in reversed(self.cards):
            if getattr(c, "status", None) is not None and c.winfo_exists() and c.done and self.family(c.lang) == fam:
                card = c
                break
        # a CSS/JS snippet never replaces the whole HTML page
        if card is None or (card.lang in ("html", "htm") and (lang or "").lower() not in ("html", "htm")):
            return self.add_live(lang, path, heading)
        for w in card.hdr.winfo_children():
            w.destroy()
        tk.Label(card.hdr, text=heading or path or lang_label(lang, path), bg=CODE_BG, fg=MUTED, font=UI_SM).pack(side="left")
        tk.Label(card.hdr, text="  " + lang_label(lang, path) + "  \u00B7  editing the same file", bg=CODE_BG, fg=DIM,
                 font=UI_XS).pack(side="left")
        card.status = tk.Label(card.hdr, text="\u25CF  rewriting...", bg=CODE_BG, fg=THEME["accent"], font=UI_XS)
        card.status.pack(side="right")
        t = card.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.configure(state="disabled")
        t.fit()
        card.code, card.lang, card.path, card.done = "", (lang or "").lower(), path or card.path, False
        self.cards.remove(card)
        self.cards.append(card)
        return card

    def add_live(self, lang, path, heading):
        """A code card that fills in while the AI is typing."""
        self.empty.pack_forget()
        card = Card(self.sf.inner, fill=CODE_BG, radius=12, padx=12, pady=9, bg=EDITOR)
        card.pack(fill="x", padx=(0, 14), pady=(0, 14))
        hdr = tk.Frame(card.inner, bg=CODE_BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=heading or path or lang_label(lang, path), bg=CODE_BG, fg=MUTED, font=UI_SM).pack(side="left")
        tk.Label(hdr, text="  " + lang_label(lang, path), bg=CODE_BG, fg=DIM, font=UI_XS).pack(side="left")
        card.status = tk.Label(hdr, text="●  writing...", bg=CODE_BG, fg=THEME["accent"], font=UI_XS)
        card.status.pack(side="right")
        card.hdr = hdr
        tk.Frame(card.inner, bg="#1a221c", height=1).pack(fill="x", pady=(8, 8))
        t = auto_text(card.inner, bg=CODE_BG, fg="#d6dbe4", font=(MONO, 10), wrap="char")  # wraps: nothing is cut off
        setup_hl(t, 10)
        t.configure(state="disabled")
        t.pack(fill="x")
        card.text, card.code, card.lang, card.path, card.done = t, "", (lang or "").lower(), path, False
        self.sf.wheel_tree(card)
        self.cards.append(card)
        return card

    def live_append(self, card, txt):
        t = card.text
        t.configure(state="normal")
        t.insert("end", txt)
        t.configure(state="disabled")
        t.xview_moveto(0)
        card.code += txt

    def live_finish(self, card, mode):
        if card.done:
            return
        card.done = True
        card.code = card.code.rstrip("\n")
        t = card.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", card.code)
        highlight(t, card.code, fam_for(card.lang, card.path))
        t.configure(state="disabled")
        t.xview_moveto(0)
        t.yview_moveto(0)
        t.fit()
        card.status.destroy()
        card.status = tk.Label(card.hdr, bg=CODE_BG)  # marks a live card (reusable working file)
        code, lang, path = card.code, card.lang, card.path
        acts = [("Copy", lambda: self.app.copy(code)), ("Save as file", lambda: self.app.save_snippet(code, lang, path))]
        if lang in ("html", "htm"):
            acts.append(("Preview", lambda: self.app.show_preview(snippet=code)))
        if mode == "edit" and self.app.workspace:
            acts.append((("Put in " + os.path.basename(path)) if path else "Put in open file", lambda: self.app.apply_code(code, path)))
        icons = {"Copy": "copy", "Preview": "eye", "Save": "save", "Put": "pencil"}
        for label, fn in reversed(acts):
            RoundButton(card.hdr, label, fn, kind="code", font=UI_XS, padx=9, pady=3, radius=7, bg=CODE_BG,
                        icon=icons.get(label.split()[0]), icon_size=11).pack(side="right", padx=(4, 0))

    def focus_card(self, card):
        self.app.select_tab(self)
        self.update_idletasks()
        total = max(1, self.sf.inner.winfo_height())
        self.sf.canvas.yview_moveto(max(0, card.winfo_y() - 10) / total)
        card.set_outline(THEME["accent"])
        self.after(1400, lambda: card.winfo_exists() and card.set_outline(None))


class PreviewTab(tk.Frame):
    """Live HTML preview shown as a tab: an Edge rendering window embedded inside Profound."""
    kind, path, icon = "preview", "__preview__", "eye"

    def __init__(self, app):
        super().__init__(app.editor_host, bg=EDITOR)
        self.app, self.hwnd, self.proc, self.tries = app, None, None, 0
        bar = tk.Frame(self, bg=PANEL, height=38)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.lbl = tk.Label(bar, text="Live preview", bg=PANEL, fg=MUTED, font=UI_SM)
        self.lbl.pack(side="left", padx=12)
        RoundButton(bar, "", app.hide_preview, kind="ghost", font=UI_SM, icon="x", icon_size=12,
                    padx=6, pady=6).pack(side="right", padx=(2, 8))
        RoundButton(bar, "", lambda: webbrowser.open(app.preview.url()), kind="soft", font=UI_SM, icon="external", icon_size=13,
                    padx=7, pady=6).pack(side="right", padx=(4, 2))
        RoundButton(bar, "", self.reload, icon="refresh", icon_size=13, kind="soft", font=UI_SM, padx=7, pady=6).pack(side="right")
        self.err_btn = RoundButton(bar, "", self.show_errors, kind="soft", font=UI_SM, padx=10, pady=3, icon="warn", icon_size=12)
        devs = tk.Frame(bar, bg=PANEL)
        devs.pack(side="right", padx=10)
        self.dev_btns = {}
        for key, label in (("desktop", "Desktop"), ("tablet", "Tablet"), ("phone", "Phone")):
            b = RoundButton(devs, label, lambda k=key: self.set_device(k), kind="seg", font=UI_XS, padx=9, pady=3, radius=7)
            b.pack(side="left", padx=1)
            self.dev_btns[key] = b
        self.host = tk.Frame(self, bg="#1a1f1b")
        self.host.pack(fill="both", expand=True)
        self.view = tk.Frame(self.host, bg="#ffffff")
        self.msg = tk.Label(self.view, text="Starting preview...", bg="#ffffff", fg="#999999", font=UI)
        self.msg.place(relx=0.5, rely=0.45, anchor="center")
        self.view.bind("<Configure>", self._resize)
        self.set_device("desktop")
        if not WIN:
            devs.pack_forget()  # device sizes need the embedded preview (Windows)

    def set_device(self, key):
        """Desktop fills the tab; Tablet and Phone show the page at that width, centred."""
        self.device = key
        for k, b in self.dev_btns.items():
            b.set_selected(k == key)
        self.view.place_forget()
        if key == "desktop":
            self.view.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            self.view.place(relx=0.5, y=10, anchor="n", width=820 if key == "tablet" else 390, relheight=1, height=-20)

    def update_errors(self):
        n = len(self.app.preview.errors)
        if n:
            self.err_btn.set_text(f"{n} error{'s' if n != 1 else ''}")
            if not self.err_btn.winfo_ismapped():
                self.err_btn.pack(side="right", padx=6)
        else:
            self.err_btn.pack_forget()

    def show_errors(self):
        errs = list(self.app.preview.errors)
        pop = tk.Toplevel(self)
        pop.title("Page errors")
        pop.configure(bg=PANEL)
        pop.geometry(f"560x360+{self.winfo_rootx() + 60}+{self.winfo_rooty() + 60}")
        style_window(pop)
        tk.Label(pop, text="Problems in your page", bg=PANEL, fg=FG, font=UI_H).pack(anchor="w", padx=18, pady=(16, 6))
        box = tk.Text(pop, bg=CODE_BG, fg="#ffb4b4", font=(MONO, 10), borderwidth=0, padx=12, pady=10, height=10, wrap="word")
        box.pack(fill="both", expand=True, padx=18)
        box.insert("1.0", "\n".join("• " + e for e in errs) or "No errors.")
        box.configure(state="disabled")
        row = tk.Frame(pop, bg=PANEL)
        row.pack(fill="x", padx=18, pady=14)

        def ask_fix():
            pop.destroy()
            self.app.set_mode("edit")
            self.app.quick("Fix these errors in my page:\n" + "\n".join("- " + e for e in errs))
        RoundButton(row, "Ask AI to fix", ask_fix, kind="accent", font=UI_B, padx=16, pady=7, icon="spark").pack(side="right")
        RoundButton(row, "Close", pop.destroy, kind="ghost", font=UI_SM).pack(side="right", padx=8)

    def title(self):
        return "Preview"

    def dirty(self):
        return False

    def content(self):
        return ""

    def reload(self):
        self.app.preview.bump()

    def set_label(self):
        pv = self.app.preview
        self.lbl.configure(text="Live preview  \u00B7  " + ("code from chat" if pv.snippet is not None else (pv.page or "")))

    def ensure(self):
        self.set_label()
        if WIN and self.app.active is not self and not self.winfo_ismapped():
            self.park()  # warming up in the background: keep it mapped (off-screen) so the page draws
        if not WIN:  # Linux / macOS: the live preview runs in the web browser (it still updates as you type)
            self.msg.configure(text="The live preview is open in your web browser.\nIt updates as you type.")
            if not getattr(self, "_browser_opened", False):
                self._browser_opened = True
                webbrowser.open(self.app.preview.url())
            return
        if self.hwnd and U32.IsWindow(self.hwnd):
            self.wake()
            return
        if self.hwnd:  # the embedded window went away: start a fresh one
            self.hwnd, self.proc = None, None
            self.msg.place(relx=0.5, rely=0.45, anchor="center")
        if self.proc and self.proc.poll() is None:
            return
        edge = find_edge()
        if not edge:
            self.msg.configure(text="Microsoft Edge is needed for the in-app preview.")
            webbrowser.open(self.app.preview.url())
            return
        prof = os.path.join(DATA_DIR, "preview")
        self.proc = subprocess.Popen([edge, f"--app={self.app.preview.url()}", f"--user-data-dir={prof}", "--no-first-run",
                                      "--no-default-browser-check", "--disable-session-crashed-bubble",
                                      "--disable-features=CalculateNativeWinOcclusion", "--disable-backgrounding-occluded-windows",
                                      "--disable-renderer-backgrounding", "--disable-background-timer-throttling", "--disable-gpu", "--disable-gpu-compositing", "--disable-direct-composition", "--in-process-gpu",
                                      "--window-position=-3000,-3000", "--window-size=800,600"])
        add_to_job(self.proc)
        self.tries = 0
        self.after(300, self._find)

    def _find(self):
        h = find_window_titled(f"PROFOUND_PREVIEW_{self.app.preview.port}")
        if h:
            return self._embed(h)
        self.tries += 1
        if self.tries < 50:
            self.after(200, self._find)
        else:
            self.msg.configure(text="Couldn't embed the preview here. Use 'Open in browser'.")
            self.proc = None  # allow another try next time the tab is opened

    def _embed(self, h):
        self.hwnd = h
        try:
            U32.SetParent(h, self.view.winfo_id())
            style = U32.GetWindowLongPtrW(h, -16)
            style = (style & ~(0x80000000 | 0x00C00000 | 0x00040000 | 0x00020000 | 0x00010000 | 0x00080000)) | 0x40000000 | 0x10000000
            U32.SetWindowLongPtrW(h, -16, style)
            U32.SetWindowPos(h, None, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0001 | 0x0004)  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER
            self.msg.place_forget()
            self._resize()
            self.after(400, self._resize)
            self.after(1500, self._resize)
        except Exception as e:
            log_error(f"embed failed: {e}")

    def park(self):
        """Hide the tab by moving it off-screen instead of unmapping it: a hidden Edge window stops drawing
        and comes back grey, a parked one keeps its page."""
        self.pack_forget()
        if WIN:
            self.place(x=0, y=0, relwidth=1, relheight=1)
            self.lower()  # stays where it is, just behind the active tab

    def unpark(self):
        self.place_forget()
        self.lift()

    def wake(self):
        """After being hidden, make the embedded page show and repaint (otherwise it can stay grey)."""
        h = self.hwnd
        if not (WIN and h and U32.IsWindow(h)):
            return

        def go(step=0):
            if not (self.hwnd and U32.IsWindow(self.hwnd)) or not self.winfo_ismapped():
                return
            U32.ShowWindow(h, 5)  # SW_SHOW
            self._resize(nudge=(step == 0))
            self._resize()
            U32.RedrawWindow(h, None, None, 0x0001 | 0x0004 | 0x0080 | 0x0100 | 0x0400)  # INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW|FRAME
            if step == 1:
                try:
                    self.app.preview.bump()  # nudge the page itself to redraw (keeps scroll position)
                except Exception:
                    pass
        for i, ms in enumerate((30, 250, 900)):
            self.after(ms, lambda i=i: go(i))

    def _resize(self, _=None, nudge=False):
        """Size the window so its page area exactly fills the tab (any leftover frame is clipped away)."""
        h = self.hwnd
        if not (h and U32.IsWindow(h)):
            return
        W, H = self.view.winfo_width(), self.view.winfo_height()
        wr, cr, pt = RECT(), RECT(), POINT(0, 0)
        U32.GetWindowRect(h, ctypes.byref(wr))
        U32.GetClientRect(h, ctypes.byref(cr))
        U32.ClientToScreen(h, ctypes.byref(pt))
        offx, offy = pt.x - wr.left, pt.y - wr.top
        extra_w = (wr.right - wr.left) - cr.right
        extra_h = (wr.bottom - wr.top) - cr.bottom
        try:
            dpi = U32.GetDpiForWindow(self.view.winfo_id()) or 96
        except AttributeError:
            dpi = 96
        cap = round(EDGE_TITLE_PX * dpi / 96)  # Edge draws its own title strip inside the window: slide it out of view
        U32.MoveWindow(h, -offx, -offy - cap, W + extra_w - (1 if nudge else 0), H + extra_h + cap, True)

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc, self.hwnd = None, None


class TabPill(tk.Canvas):
    def __init__(self, parent, app, tab):
        self.app, self.tab = app, tab
        self.f = tkfont.Font(font=UI_SM)
        sel = app.active is tab
        label = tab.title() + ("  \u25CF" if tab.dirty() else "")
        w = self.f.measure(label) + 62
        super().__init__(parent, width=w, height=30, bg=PANEL, highlightthickness=0, bd=0, cursor="hand2")
        self.sel, self.label, self.w, self.hover = sel, label, w, False
        self.bind("<Enter>", lambda e: self._h(True))
        self.bind("<Leave>", lambda e: self._h(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<ButtonRelease-2>", lambda e: app.close_tab(tab))
        self.draw()

    def _h(self, v):
        self.hover = v
        self.draw()

    def draw(self):
        self.delete("all")
        fill = EDITOR if self.sel else (PANEL2 if self.hover else PANEL)
        if fill != PANEL:
            rrect(self, 0, 0, self.w - 1, 29, 9, fill=fill, outline=fill)
        if self.sel:
            self.create_line(12, 28, self.w - 12, 28, fill=THEME["accent"], width=2)
        icon = getattr(self.tab, "icon", None)
        if icon:
            draw_icon(self, icon, 11, 8, 14, THEME["accent"] if self.sel else MUTED)
        else:
            col = lang_color(self.tab.path)
            self.create_oval(13, 11, 21, 19, fill=col, outline=col)
        self.create_text(31, 15, text=self.label, anchor="w", font=self.f, fill=FG if self.sel else MUTED)
        if self.sel or self.hover:
            self.create_text(self.w - 16, 15, text="\u2715", font=(SANS, 8), fill=MUTED)

    def _click(self, e):
        if e.x > self.w - 26:
            self.app.close_tab(self.tab)
        else:
            self.app.select_tab(self.tab)


class StatusPill(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=120, height=26, bg=PANEL, highlightthickness=0, bd=0)
        self.f = tkfont.Font(font=UI_SM)
        self.set("Starting AI", WARN)

    def set(self, text, color):
        w = self.f.measure(text) + 36
        self.configure(width=w)
        self.delete("all")
        rrect(self, 0, 0, w - 1, 25, 12, fill=PANEL2, outline=PANEL2)
        self.create_oval(11, 9, 19, 17, fill=color, outline="")
        self.create_text(26, 13, text=text, anchor="w", font=self.f, fill=FG)


# ---------------------------------------------------------------- the app
class App:
    def __init__(self, root, selftest=None):
        self.root, self.selftest = root, selftest
        # hidden test runs must never change the user's settings or saved chats
        self.testing = bool(selftest) or any(a.endswith("test") and a.startswith("--") for a in sys.argv[1:])
        self.S = dict(DEF)
        try:
            with open(CFG_PATH, "r", encoding="utf-8") as f:
                self.S.update(json.load(f))
        except Exception:
            pass
        if self.S["accent"] in ("#5a9dff", "#86d93f"):  # move people from older defaults to the mascot green
            self.S["accent"] = ACCENTS[0]
        THEME["accent"] = self.S["accent"]
        self.workspace, self.tabs, self.active, self.q = "", [], None, queue.Queue()
        self.history, self.busy, self.stop_flag, self.ready, self.boot_id = [], False, False, False, 0
        self.pending, self.stream, self.thinking = None, "", False
        self.settings_win = self.train_win = None
        self.cur_body = self.stream_t = None
        self._tab_sig = None
        self.chat_id, self.chat_created, self.last_question, self.used_examples = None, None, "", []
        self.gen, self._resp = 0, None
        self.engine = Engine()
        atexit.register(self.engine.stop)
        self.preview = Preview(self)
        self.library = Library()
        self.bridge = Bridge(self)
        self.total_gb = max(2, int(total_ram_gb()))
        if not self.S["ram"]:
            self.S["ram"] = float(min(4, self.total_gb))
        self.S["ram"] = min(float(self.S["ram"]), float(self.total_gb))
        self.ram_var = tk.DoubleVar(value=self.S["ram"])
        self.tree_map, self.models, self.attachments = {}, [], []
        self.chat_title, self.chat_renamed = None, False
        self.build_ui()
        if selftest or "--stoptest" in sys.argv:  # tests use the smallest installed model so they stay quick
            small = min(self.models, key=lambda m: m["size"]) if self.models else None
            if small:
                self.S.update(model=small["name"], gemmaDefault=True)
        if "--qbtest" in sys.argv or "--styletest" in sys.argv:  # tests on the model a 4 GB laptop would run
            e2b = next((m for m in self.models if m["name"].lower().startswith("gemma-4-e2b")), None)
            if e2b:
                self.S.update(model=e2b["name"], gemmaDefault=True)
        self.snippets = SnippetsTab(self)
        self.preview_tab = PreviewTab(self)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, lambda: set_crisp_icon(self.root))
        self.root.after(400, lambda: enable_file_drop(self.root, lambda files: self.q.put(("drop", files))))
        self.root.after(30, self.pump)
        self.root.after(150, self.start_engine)
        target = next((a for a in sys.argv[1:] if os.path.exists(a)), None) if not selftest else None
        if "--demo-ask" in sys.argv:  # hidden: used to screenshot the Ask-mode flow
            self.root.after(800, self.demo_tick)
        if "--demo-preview" in sys.argv:  # hidden: used to screenshot the Preview tab
            self.root.after(1500, self.run_current)
        if "--scrolltest" in sys.argv:  # hidden: checks the chat lands on the last message
            self.root.after(1200, lambda: self.scrolltest(sys.argv[sys.argv.index("--scrolltest") + 1]))
        if "--demo-ui2" in sys.argv:  # hidden: screenshot attachments + phone preview
            def demo_ui2():
                for n in ("buddy_idle.png", "make_icon.ps1"):
                    p = os.path.join(APP_DIR, n)
                    if os.path.exists(p):
                        self.attachments.append({"path": p, "name": n, "kind": "image" if n.endswith(".png") else "text",
                                                 "size": os.path.getsize(p)})
                self.refresh_attach_row()
                self.run_current()
                self.root.after(2500, lambda: self.preview_tab.set_device("phone"))
            self.root.after(1500, demo_ui2)
        for flag in ("--codetest", "--previewtest"):  # hidden: automated checks of the code streaming and the preview tab
            if flag in sys.argv:
                out = sys.argv[sys.argv.index(flag) + 1]
                self.root.after(1500, (lambda o=out: self.codetest(o)) if flag == "--codetest" else (lambda o=out: self.previewtest(o)))
        if "--qbtest" in sys.argv:  # hidden: runs a Quick build on the smallest model and checks the page
            self.root.after(1500, lambda: self.qbtest(sys.argv[sys.argv.index("--qbtest") + 1]))
        if "--readmetest" in sys.argv:  # hidden: screenshots for the README
            self.root.after(1500, lambda: self.readmetest(sys.argv[sys.argv.index("--readmetest") + 1]))
        if "--smoketest" in sys.argv:  # hidden: used by the GitHub builds to check the built app starts on each system
            self.root.after(2500, lambda: self.smoketest(sys.argv[sys.argv.index("--smoketest") + 1]))
        if "--styletest" in sys.argv:  # hidden: "make a page" then "now style it" must edit the same file
            self.root.after(1500, lambda: self.styletest(sys.argv[sys.argv.index("--styletest") + 1]))
        if "--demo-qb" in sys.argv:  # hidden: screenshot the Quick build picker
            self.root.after(2000, self.open_quick_build)
        if "--droptest" in sys.argv:  # hidden: simulates Windows dropping files on the window
            self.root.after(2500, lambda: self.droptest(sys.argv[sys.argv.index("--droptest") + 1]))
        if "--demo-models" in sys.argv:  # hidden: used to screenshot the model menu
            self.root.after(2500, self.open_model_menu)
        if "--stoptest" in sys.argv:  # hidden: verifies the Stop button (writes JSON results)
            self.stoptest_out = sys.argv[sys.argv.index("--stoptest") + 1]
            self.root.after(800, self.stoptest)
        if selftest:
            self.root.after(500, self.run_selftest)
        elif target:
            target = os.path.abspath(target)
            if os.path.isdir(target):
                self.root.after(100, lambda: self.set_workspace(target))
            else:
                self.root.after(100, lambda: (self.set_workspace(os.path.dirname(target)), self.open_file(os.path.basename(target))))
        elif self.S["lastFolder"] and os.path.isdir(self.S["lastFolder"]):
            self.root.after(100, lambda: self.set_workspace(self.S["lastFolder"]))

    # ---- settings
    def save_settings(self):
        if self.selftest or self.testing:
            return
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.S, f)
        except Exception:
            pass

    def say(self, msg, ms=2600):
        self.toast.configure(text="  " + msg + "  ")
        self.toast.place(relx=0.5, rely=1.0, y=-20, anchor="s")
        self.toast.lift()
        if getattr(self, "_toast_job", None):
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(ms, self.toast.place_forget)

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.say("Copied to clipboard")

    # ---- styles
    def setup_style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure(".", background=PANEL, foreground=FG, fieldbackground=PANEL2, bordercolor=PANEL,
                     lightcolor=PANEL, darkcolor=PANEL, troughcolor=PANEL, focuscolor=PANEL, font=UI)
        for orient in ("Vertical", "Horizontal"):
            name = f"Slim.{orient}.TScrollbar"
            st.layout(name, [(f"{orient}.Scrollbar.trough", {"children": [(f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})],
                                                              "sticky": "ns" if orient == "Vertical" else "ew"})])
            st.configure(name, troughcolor=BG, background="#2a372d", bordercolor=BG, lightcolor="#2a372d",
                         darkcolor="#2a372d", arrowsize=8, gripcount=0)
            st.map(name, background=[("active", "#3a4b3e")])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, borderwidth=0, rowheight=28, font=UI, indent=14)
        st.map("Treeview", background=[("selected", "#22382a")], foreground=[("selected", FG)])
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG, arrowcolor=MUTED,
                     bordercolor=PANEL2, lightcolor=PANEL2, darkcolor=PANEL2, padding=7)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", FG)],
               selectbackground=[("readonly", PANEL2)], selectforeground=[("readonly", FG)], background=[("readonly", PANEL2)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#22382a")
        self.root.option_add("*TCombobox*Listbox.font", UI)
        self.style = st
        self.style_accent()

    def style_accent(self):
        a = THEME["accent"]
        self.style.configure("TScale", background=a, troughcolor=PANEL2, bordercolor=PANEL, lightcolor=a, darkcolor=a, sliderlength=16)

    # ---- UI
    def build_ui(self):
        r = self.root
        r.title("Profound")
        r.geometry("1440x880")
        r.minsize(1040, 640)
        r.configure(bg=BG)
        style_window(r)
        self.load_logos()
        self.setup_style()

        top = tk.Frame(r, bg=PANEL, height=66)
        top.pack(fill="x")
        top.pack_propagate(False)
        self.logo_lbl = self.last_avatar = None
        if self.logo:
            self.logo_lbl = tk.Label(top, image=self.logo, bg=PANEL)
            self.logo_lbl.pack(side="left", padx=(14, 8))
        tk.Label(top, text="Profound", bg=PANEL, fg=FG, font=(SANS_SEMI, 13)).pack(side="left")
        self.folder_lbl = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=UI_SM)
        self.folder_lbl.pack(side="left", padx=14)
        RoundButton(top, "Settings", self.open_settings, kind="ghost", font=UI_SM, icon="gear").pack(side="right", padx=(2, 12))
        RoundButton(top, "Train", self.open_train, kind="ghost", font=UI_SM, icon="spark").pack(side="right", padx=2)
        self.model_chip = RoundButton(top, "", self.open_model_menu, kind="ghost", font=UI_SM, icon="chip", icon_size=13)
        self.model_chip.pack(side="right", padx=2)
        self.pill = StatusPill(top)
        self.pill.pack(side="right", padx=8)
        tk.Frame(r, bg=LINE, height=1).pack(fill="x")

        self.pw = tk.PanedWindow(r, orient="horizontal", bg=LINE, sashwidth=1, borderwidth=0, sashrelief="flat")
        self.pw.pack(fill="both", expand=True)

        self.left = tk.Frame(self.pw, bg=PANEL)
        bar = tk.Frame(self.left, bg=PANEL)
        bar.pack(fill="x", padx=10, pady=(12, 6))
        self.side_title = tk.Label(bar, text="FILES", bg=PANEL, fg=MUTED, font=(SANS_SEMI, 8))
        self.side_title.pack(side="left")
        RoundButton(bar, "", self.refresh_tree, kind="ghost", padx=6, pady=5, radius=7, icon="refresh").pack(side="right")
        RoundButton(bar, "", self.new_file, kind="ghost", padx=6, pady=5, radius=7, icon="plus").pack(side="right")
        self.tree = ttk.Treeview(self.left, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        self.mid = tk.Frame(self.pw, bg=EDITOR)
        tb = tk.Frame(self.mid, bg=PANEL)
        tb.pack(fill="x")
        self.tabbar = tk.Frame(tb, bg=PANEL)
        self.tabbar.pack(side="left", fill="x", expand=True, padx=8)
        self.run_btn = RoundButton(tb, "Run", self.run_current, kind="soft", font=UI_SM, padx=12, pady=5, icon="play", icon_size=12)
        self.run_btn.pack(side="right", padx=(4, 10), pady=6)
        self.save_btn = RoundButton(tb, "Save", self.save_current, kind="soft", font=UI_SM, padx=12, pady=5, icon="save", icon_size=13)
        self.save_btn.pack(side="right", pady=6)
        self.pv_btn = RoundButton(tb, "Preview", self.toolbar_preview, kind="accent", font=UI_SM, padx=12, pady=5, icon="eye",
                                  icon_size=13)
        self.pv_btn.pack(side="right", padx=(0, 4), pady=6)
        self.path_lbl = tk.Label(self.mid, text="", bg=EDITOR, fg=DIM, font=UI_XS, anchor="w")
        self.path_lbl.pack(fill="x", padx=14, pady=(4, 0))
        self.split = tk.PanedWindow(self.mid, orient="horizontal", bg=LINE, sashwidth=4, borderwidth=0, sashrelief="flat")
        self.split.pack(fill="both", expand=True)
        self.editor_host = tk.Frame(self.split, bg=EDITOR)
        self.split.add(self.editor_host, stretch="always", minsize=260)
        self.welcome = self.build_welcome(self.mid)
        self.pw.add(self.mid, minsize=380, stretch="always")

        self.right = tk.Frame(self.pw, bg=PANEL)
        self.pw.add(self.right, width=480, minsize=360)
        self.build_chat(self.right)

        self.toast = tk.Label(r, text="", bg="#26322a", fg=FG, font=UI_SM, padx=10, pady=7)
        r.bind_all("<Control-s>", lambda e: self.save_current())
        r.bind_all("<Control-w>", lambda e: self.active and self.close_tab(self.active))
        r.bind_all("<Control-o>", lambda e: self.open_folder())
        r.bind_all("<Control-n>", lambda e: self.new_file())
        r.bind_all("<F5>", lambda e: self.run_current())
        if MAC:  # Cmd instead of Ctrl on a Mac
            r.bind_all("<Command-s>", lambda e: self.save_current())
            r.bind_all("<Command-w>", lambda e: self.active and self.close_tab(self.active))
            r.bind_all("<Command-o>", lambda e: self.open_folder())
            r.bind_all("<Command-n>", lambda e: self.new_file())
        self.refresh_models()
        self.update_chip()
        self.refresh_tabs()

    def load_logos(self):
        """Mascot frames: idle (also the app logo) and talking. Your own logo_idle.png / logo_talking.png next to the exe win."""
        def scaled(img, target):
            w = img.width()
            if w > target:
                return img.subsample(max(1, round(w / target)))
            if w < target:
                return img.zoom(max(1, round(target / w)))
            return img
        self.frames = {}
        try:
            for key, fname, user in (("idle", "buddy_idle.png", "logo_idle.png"), ("talk", "buddy_talk.png", "logo_talking.png")):
                up = os.path.join(APP_DIR, user)
                big = tk.PhotoImage(file=up if os.path.exists(up) else os.path.join(RES_DIR, fname))
                self.frames[key] = {"big": big, "head": scaled(big, 60), "hero": scaled(big, 160), "tiny": scaled(big, 40)}
            self.logo, self.logo_hero, self.logo_tiny = (self.frames["idle"][k] for k in ("head", "hero", "tiny"))
        except Exception as e:
            log_error(f"logo load: {e}")
            self.frames, self.logo, self.logo_hero, self.logo_tiny = {}, None, None, None

    def animate_talk(self, i):
        """Swap between the idle and talking faces while the AI is thinking or replying."""
        if not self.frames:
            return
        talking = self.busy and i % 2 == 1
        key = "talk" if talking else "idle"
        if self.logo_lbl is not None:
            self.logo_lbl.configure(image=self.frames[key]["head"])
        av = getattr(self, "talk_avatar", None)
        if av is not None and av.winfo_exists():
            av.configure(image=self.frames[key]["tiny"])
        if self.busy:
            self.root.after(170 if talking else 230, lambda: self.animate_talk(i + 1))

    def build_welcome(self, parent):
        w = tk.Frame(parent, bg=EDITOR)
        inner = tk.Frame(w, bg=EDITOR)
        inner.place(relx=0.5, rely=0.45, anchor="center")
        if self.logo_hero:
            tk.Label(inner, image=self.logo_hero, bg=EDITOR).pack(pady=(0, 18))
        tk.Label(inner, text="Welcome to Profound", bg=EDITOR, fg=FG, font=(SANS_SEMI, 22)).pack()
        tk.Label(inner, text="Your offline AI coding buddy. Python, web, Rust, Java, C++ and more.", bg=EDITOR, fg=MUTED,
                 font=(SANS, 11)).pack(pady=(6, 26))
        row = tk.Frame(inner, bg=EDITOR)
        row.pack()
        RoundButton(row, "Open a folder", self.open_folder, icon="folder", icon_size=16, kind="accent", font=UI_B, padx=20, pady=11, radius=12).pack(side="left", padx=6)
        RoundButton(row, "New file", self.new_file, icon="file", icon_size=16, kind="soft", font=UI_B, padx=20, pady=11, radius=12).pack(side="left", padx=6)
        RoundButton(row, "Just chat", lambda: (self.set_mode("ask"), self.inp.focus_set()), icon="chat", icon_size=16, kind="soft",
                    font=UI_B, padx=20, pady=11, radius=12).pack(side="left", padx=6)
        tk.Label(inner, text="Ctrl+O open folder   \u00B7   Ctrl+S save   \u00B7   F5 run   \u00B7   Ctrl+W close tab",
                 bg=EDITOR, fg=DIM, font=UI_SM).pack(pady=(30, 0))
        return w

    def build_chat(self, p):
        head = tk.Frame(p, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(14, 2))
        seg = Card(head, fill=PANEL2, radius=12, padx=3, pady=3, fit_width=True)
        seg.pack(side="left")
        self.seg_ask = RoundButton(seg.inner, "Ask", lambda: self.set_mode("ask"), icon="chat", kind="seg", font=UI_B, padx=16, pady=6, radius=10)
        self.seg_edit = RoundButton(seg.inner, "Edit", lambda: self.set_mode("edit"), icon="pencil", kind="seg", font=UI_B, padx=16, pady=6, radius=10)
        self.seg_ask.pack(side="left")
        self.seg_edit.pack(side="left")
        RoundButton(head, "New", self.new_chat, kind="ghost", font=UI_SM, icon="plus", icon_size=12).pack(side="right")
        RoundButton(head, "Saved chats", self.show_history, kind="ghost", font=UI_SM, icon="history", icon_size=13).pack(side="right")
        self.mode_hint = tk.Label(p, text="", bg=PANEL, fg=MUTED, font=UI_SM, anchor="w", justify="left")
        self.mode_hint.pack(fill="x", padx=17, pady=(6, 4))

        self.chat_sf = ScrollFrame(p, PANEL)
        self.chat_sf.pack(fill="both", expand=True)

        bot = tk.Frame(p, bg=PANEL)
        bot.pack(fill="x", padx=14, pady=(6, 12))
        self.inbox = Card(bot, fill=PANEL2, radius=16, padx=12, pady=8)
        self.inbox.pack(fill="x")
        row = self.inbox.inner
        self.attach_row = tk.Frame(bot, bg=PANEL)
        RoundButton(row, "", self.attach_files, kind="ghost", padx=6, pady=7, radius=9, icon="clip", icon_size=17,
                    bg=PANEL2).pack(side="left", anchor="s", padx=(0, 6))
        self.inp = tk.Text(row, height=3, wrap="word", bg=PANEL2, fg=FG, insertbackground=FG, borderwidth=0,
                           padx=2, pady=4, font=(SANS, 10), highlightthickness=0, width=10)
        self.inp.pack(side="left", fill="both", expand=True)
        self.send_btn = RoundButton(row, "", self.send, kind="accent", padx=11, pady=9, radius=11, bg=PANEL2, icon="send", icon_size=16)
        self.send_btn.pack(side="right", anchor="s", padx=(8, 0))
        self.inp.bind("<Return>", lambda e: None if (e.state & 0x1) else (self.send(), "break")[1])
        self.inp.bind("<FocusIn>", lambda e: (self._placeholder(False), self.inbox.set_outline(THEME["accent"])))
        self.inp.bind("<FocusOut>", lambda e: (self._placeholder(True), self.inbox.set_outline(None)))
        foot = tk.Frame(bot, bg=PANEL)
        foot.pack(fill="x", pady=(8, 0))
        self.style_btn = RoundButton(foot, "", self.open_style_picker, kind="chip", font=UI_SM, padx=10, pady=4, radius=9)
        self.style_btn.pack(side="left")
        self.qb_btn = RoundButton(foot, "Quick build", self.open_quick_build, kind="accent", font=UI_SM, padx=10, pady=4,
                                  radius=9, icon="spark", icon_size=12)  # shown only when a small model is in use
        self.see_var = tk.BooleanVar(value=self.S["seeFile"])
        tk.Label(foot, text="AI sees open file", bg=PANEL, fg=MUTED, font=UI_SM).pack(side="right")
        Toggle(foot, self.see_var, lambda: (self.S.update(seeFile=self.see_var.get()), self.save_settings())).pack(side="right", padx=6)
        self.ph_on = False
        self._placeholder(True)
        self.update_style_btn()
        self.set_mode(self.S["mode"], save=False)
        self.chat_welcome()

    # ---- input helpers
    def _placeholder(self, show):
        if show and not self.inp.get("1.0", "end").strip():
            self.ph_on = True
            self.inp.configure(fg=DIM)
            self.inp.insert("1.0", "Ask a coding question..." if self.S["mode"] == "ask" else "Tell me what to build or change...")
        elif not show and self.ph_on:
            self.ph_on = False
            self.inp.delete("1.0", "end")
            self.inp.configure(fg=FG)

    def get_input(self):
        return "" if self.ph_on else self.inp.get("1.0", "end").strip()

    def set_input(self, text):
        self._placeholder(False)
        self.inp.delete("1.0", "end")
        self.inp.insert("1.0", text)

    def set_mode(self, m, save=True):
        self.S["mode"] = m
        self.seg_ask.set_selected(m == "ask")
        self.seg_edit.set_selected(m == "edit")
        self.mode_hint.configure(text="Just chatting. Code goes to the { } Code tab, your files stay untouched." if m == "ask"
                                 else "I'll write code straight into your open file. You review, then save.")
        if self.ph_on:
            self.ph_on = False
            self.inp.delete("1.0", "end")
            self._placeholder(True)
        if hasattr(self, "chat_sf"):
            self.root.after(50, self.show_latest)  # land on the latest exchange
        if save:
            self.save_settings()

    # ---- style presets
    def update_style_btn(self):
        s = self.S.get("style", "none")
        self.style_btn.set_text("Style: " + (STYLES[s][0] if s in STYLES else "Auto"), icon="palette")

    def open_style_picker(self):
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        pop.configure(bg=LINE)
        style_window(pop)
        body = tk.Frame(pop, bg=PANEL2)
        body.pack(padx=1, pady=1)
        tk.Label(body, text="Design style for UI code", bg=PANEL2, fg=FG, font=UI_B).pack(anchor="w", padx=14, pady=(12, 0))
        tk.Label(body, text="Used whenever you ask for web pages or apps.", bg=PANEL2, fg=MUTED, font=UI_XS).pack(anchor="w", padx=14, pady=(0, 8))

        def choose(k):
            self.S["style"] = k
            self.save_settings()
            self.update_style_btn()
            pop.destroy()
            self.say("Style: " + (STYLES[k][0] if k in STYLES else "Auto"))
        options = [("none", ("Auto", "Let the AI decide", [PANEL, MUTED, FG, DIM]))] + [(k, v[:3]) for k, v in STYLES.items()]
        for key, (name, tag, sw) in options:
            row = tk.Frame(body, bg=PANEL2, cursor="hand2")
            row.pack(fill="x", padx=6, pady=1)
            cv = tk.Canvas(row, width=70, height=26, bg=PANEL2, highlightthickness=0)
            cv.pack(side="left", padx=(8, 6), pady=6)
            for i, c in enumerate(sw):
                cv.create_oval(2 + i * 16, 5, 18 + i * 16, 21, fill=c, outline="#3a404b")
            txt = tk.Frame(row, bg=PANEL2)
            txt.pack(side="left", fill="x", expand=True)
            sel = self.S.get("style", "none") == key
            l1 = tk.Label(txt, text=name + ("   \u2713" if sel else ""), bg=PANEL2, fg=THEME["accent"] if sel else FG, font=UI_B, anchor="w")
            l1.pack(fill="x")
            l2 = tk.Label(txt, text=tag, bg=PANEL2, fg=MUTED, font=UI_XS, anchor="w")
            l2.pack(fill="x")
            widgets = (row, cv, txt, l1, l2)
            for wdg in widgets:
                wdg.bind("<Button-1>", lambda e, k=key: choose(k))
                wdg.bind("<Enter>", lambda e, ws=widgets: [x.configure(bg=HOVER) for x in ws])
                wdg.bind("<Leave>", lambda e, ws=widgets: [x.configure(bg=PANEL2) for x in ws])
        tk.Frame(body, bg=PANEL2, height=8).pack()
        pop.update_idletasks()
        x = self.style_btn.winfo_rootx()
        y = self.style_btn.winfo_rooty() - pop.winfo_reqheight() - 8
        pop.geometry(f"+{x}+{max(0, y)}")
        pop.bind("<Escape>", lambda e: pop.destroy())
        pop.bind("<FocusOut>", lambda e: pop.after(150, lambda: pop.winfo_exists() and pop.focus_get() is None and pop.destroy()))
        pop.focus_force()

    # ---- Quick build: guided page builder for small models
    def open_quick_build(self):
        w = tk.Toplevel(self.root)
        w.title("Quick build")
        w.configure(bg=PANEL)
        w.geometry(f"640x720+{self.root.winfo_x() + 200}+{self.root.winfo_y() + 40}")
        w.transient(self.root)
        style_window(w)
        body = tk.Frame(w, bg=PANEL)
        body.pack(fill="both", expand=True, padx=24, pady=18)
        tk.Label(body, text="Quick build", bg=PANEL, fg=FG, font=(SANS_SEMI, 16)).pack(anchor="w")
        tk.Label(body, text="Pick what you want. Profound starts from a ready-made template and styles it for you, "
                            "which small AI models handle much better than starting from nothing.",
                 bg=PANEL, fg=MUTED, font=UI_SM, wraplength=580, justify="left").pack(anchor="w", pady=(4, 12))
        sel = {"page": "landing", "style": self.S.get("style") if self.S.get("style") in STYLES else "darksaas",
               "color": QB_COLORS[0]}

        def heading(text):
            tk.Label(body, text=text.upper(), bg=PANEL, fg=THEME["accent"], font=(SANS_SEMI, 8)).pack(anchor="w", pady=(12, 6))

        def chips(options, key):
            box = tk.Frame(body, bg=PANEL)
            box.pack(anchor="w", fill="x")
            btns = {}
            for i, (val, label) in enumerate(options):
                b = RoundButton(box, label, None, kind="seg", font=UI_SM, padx=11, pady=5, radius=9, bg=PANEL)
                b.grid(row=i // 5, column=i % 5, padx=3, pady=3, sticky="w")
                btns[val] = b

            def pick(v):
                sel[key] = v
                for k2, b2 in btns.items():
                    b2.set_selected(k2 == v)
            for val, b in btns.items():
                b.command = lambda v=val: pick(v)
            pick(sel[key])
        heading("What are you making?")
        chips([(k, label) for k, label, _ in QB_PAGES], "page")
        heading("Style")
        chips([(k, v[0]) for k, v in STYLES.items()], "style")
        heading("Main colour")
        sw = tk.Frame(body, bg=PANEL)
        sw.pack(anchor="w")
        rings = []

        def pick_color(c):
            sel["color"] = c
            for cv, col in rings:
                cv.delete("ring")
                if col == c:
                    cv.create_oval(1, 1, 29, 29, outline=FG, width=2, tags="ring")
        for col in QB_COLORS:
            cv = tk.Canvas(sw, width=30, height=30, bg=PANEL, highlightthickness=0, cursor="hand2")
            cv.create_oval(5, 5, 25, 25, fill=col, outline=col)
            cv.pack(side="left", padx=2)
            cv.bind("<Button-1>", lambda e, c=col: pick_color(c))
            rings.append((cv, col))
        pick_color(sel["color"])
        heading("Sections (for landing pages and portfolios)")
        secs = tk.Frame(body, bg=PANEL)
        secs.pack(anchor="w", fill="x")
        sec_vars = {}
        for i, name in enumerate(QB_SECTIONS):
            f = tk.Frame(secs, bg=PANEL)
            f.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 18), pady=4)
            v = tk.BooleanVar(value=name in ("Navbar", "Hero", "Features", "Footer"))
            Toggle(f, v).pack(side="left")
            tk.Label(f, text=name, bg=PANEL, fg=FG, font=UI_SM).pack(side="left", padx=6)
            sec_vars[name] = v
        heading("What's it for?")
        desc_card = Card(body, fill=PANEL2, radius=12, padx=10, pady=8)
        desc_card.pack(fill="x")
        desc = tk.Entry(desc_card.inner, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat", font=UI)
        desc.pack(fill="x", ipady=4)
        desc.insert(0, "e.g. a cosy bakery in Lisbon")
        desc.bind("<FocusIn>", lambda e: desc.get().startswith("e.g.") and desc.delete(0, "end"))

        def build():
            what = desc.get().strip()
            w.destroy()
            self.quick_build_send(sel["page"], sel["style"], sel["color"], [n for n, v in sec_vars.items() if v.get()],
                                  "" if what.startswith("e.g.") else what)
        bt = tk.Frame(w, bg=PANEL)
        bt.pack(fill="x", padx=24, pady=(0, 18))
        RoundButton(bt, "Build it", build, kind="accent", font=UI_B, padx=22, pady=9, radius=11, icon="spark").pack(side="right")
        RoundButton(bt, "Cancel", w.destroy, kind="ghost", font=UI_SM).pack(side="right", padx=8)

    def quick_build_send(self, page_key, style_key, color, sections, what):
        """Quick build. Landing pages and portfolios: Profound assembles the page and the AI only writes the words
        (reliable on tiny models). Other page types: the AI adapts a matching template."""
        if page_key in ("landing", "portfolio") and page_builder is not None:
            return self.quick_build_assemble(page_key, style_key, color, sections, what)
        _, page_label, tpl_file = next(p for p in QB_PAGES if p[0] == page_key)
        tpl_rel = f"templates/landing-{style_key}.html" if page_key == "landing" else tpl_file
        try:
            with open(os.path.join(RES_DIR, "training_pack", *tpl_rel.split("/")), "r", encoding="utf-8") as f:
                tpl = f.read()
        except OSError:
            tpl = ""
        prompt = f"Build a {page_label.lower()} for {what or 'a modern website'}. Design style: {STYLES[style_key][0]}. Main colour: {color}."
        if page_key in ("landing", "portfolio") and sections:
            prompt += " Sections: " + ", ".join(sections) + "."
        ctx = ("Start from this template and adapt it to my request: rewrite all the text for my topic, apply the design "
               f"style ({STYLES[style_key][3]}) using {color} as the main colour, and add/remove sections as asked. "
               "Return ONE complete HTML file with all CSS at the top in a <style> block and the HTML below it. "
               "Then explain what you changed in 2-4 bullet points.")
        if self.workspace and self.S["mode"] == "edit":
            ctx += " Save it as index.html (use the fence ```html:index.html)."
        if tpl:
            ctx += "\n```html\n" + tpl + "\n```"
        self.qb_context, self.next_max_tokens = ctx, 6000
        self.S["style"] = style_key
        self.update_style_btn()
        self.set_input(prompt)
        self.send()

    def quick_build_assemble(self, page_key, style_key, color, sections, what):
        if self.busy:
            return self.say("Wait for the current reply to finish")
        if not self.ready:
            return self.say("The AI is still starting, try again in a moment")
        page_label = next(p[1] for p in QB_PAGES if p[0] == page_key)
        shown = f"Quick build: {page_label.lower()} for {what or 'a modern website'} ({STYLES[style_key][0]}, {color})"
        self.S["style"] = style_key
        self.update_style_btn()
        self.last_question = shown
        self.history.append({"role": "user", "content": shown})
        self.add_user_msg(shown)
        if self.chat_id is None:
            self.chat_id, self.chat_created = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], time.time()
        row = self.chat_row()
        self.cur_body = self.ai_header(row)
        self.think_lbl = tk.Label(self.cur_body, text="Writing the words for your page...", bg=PANEL, fg=MUTED, font=UI_SM)
        self.think_lbl.pack(anchor="w")
        self.chat_sf.wheel_tree(row)
        self.segs, self.code_opened, self.stream, self.used_examples = {}, False, "", []
        self.busy, self.stop_flag, self.thinking = True, False, False
        self.send_btn.set_text("", icon="stop")
        self.talk_avatar = self.last_avatar
        self.animate_talk(0)
        self.qb_job = (page_key, page_label, style_key, color, sections, what)
        self.gen += 1
        gid = self.gen
        body = {"messages": [{"role": "system", "content": "You write short, specific website copy. Reply with JSON only."},
                             {"role": "user", "content": page_builder.prompt_for(page_label, what)}],
                "temperature": 0.7, "max_tokens": 1500, "response_format": {"type": "json_object", "schema": page_builder.SCHEMA},
                "chat_template_kwargs": {"enable_thinking": False}}

        def work():
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{self.engine.port}/v1/chat/completions",
                                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    self._resp = r
                    txt = json.loads(r.read())["choices"][0]["message"].get("content") or ""
                self.q.put(("qb", gid, txt))
            except Exception as e:
                self.q.put(("qb", gid, "ERROR " + str(e)))
            finally:
                self._resp = None
        threading.Thread(target=work, daemon=True).start()

    def quick_build_finish(self, txt):
        page_key, page_label, style_key, color, sections, what = self.qb_job
        body = self.cur_body
        if getattr(self, "think_lbl", None) is not None and self.think_lbl.winfo_exists():
            self.think_lbl.destroy()
        content = page_builder.parse_content("" if txt.startswith("ERROR") else txt)
        secs = sections or ["Navbar", "Hero", "Features", "Footer"]
        html = page_builder.build_page(style_key, color, secs, content, page_label)
        fname = "index.html"
        heading = f"{page_label} - {content['brand']}"
        card = self.snippets.reuse_live("html", fname, heading)
        self.snippets.live_append(card, html)
        self.snippets.live_finish(card, self.S["mode"])
        self.snippets.focus_card(card)  # Code tab in front
        expl = (f"Built your **{page_label.lower()}** for {what or 'your site'}:\n"
                f"- Style **{STYLES[style_key][0]}** with **{color}** as the main colour\n"
                f"- Sections: {', '.join(secs)}\n"
                f"- I wrote the words (brand **{content['brand']}**, headline, features, and more); the layout and CSS come from "
                f"Profound's templates, all CSS at the top and the HTML below\n"
                "- Ask me to change anything: colours, wording, add a section...")
        if txt.startswith("ERROR"):
            expl += "\n\n(The AI didn't answer, so I used placeholder text.)"
        self.md_text(body, expl)
        chip = Card(body, fill=PANEL2, radius=12, padx=12, pady=8)
        chip.pack(fill="x", pady=5)
        tk.Label(chip.inner, text=f"</>   HTML page  \u00B7  {html.count(chr(10)) + 1} lines", bg=PANEL2, fg=FG, font=UI_SM).pack(side="left")
        RoundButton(chip.inner, "View code", lambda: self.snippets.focus_card(card), kind="accent", font=UI_XS, icon="arrow",
                    icon_size=11, padx=10, pady=3, radius=8, bg=PANEL2).pack(side="right")
        RoundButton(chip.inner, "Preview", lambda: self.show_preview(snippet=html), kind="code", font=UI_XS, icon="eye",
                    icon_size=11, padx=9, pady=3, radius=8, bg=PANEL2).pack(side="right", padx=4)
        self.chat_sf.wheel_tree(body)
        if self.S["mode"] == "edit" and self.workspace:
            t = self.apply_code(html, fname, focus=False)
            if t and self.S["autoSave"]:
                self.save_tab(t)
            self.show_preview(page=fname, focus=False)
        else:
            self.show_preview(snippet=html, focus=False)
        self.stream = expl + "\n\n```html:" + fname + "\n" + html + "\n```"
        self.history.append({"role": "assistant", "content": self.stream, "mode": self.S["mode"]})
        self.save_chat()
        self.busy = False
        self.send_btn.set_text("", icon="send")
        self.root.after(80, self.show_latest)
        self.selftest_hook("done")

    # ---- models / RAM
    def list_models(self):
        return [{"name": os.path.basename(p), "path": p, "size": os.path.getsize(p)}
                for p in sorted(glob.glob(os.path.join(MODELS, "*.gguf")))
                if not os.path.basename(p).lower().startswith(("mmproj", "mtp-", "dflash-"))]  # add-on files, not models

    def refresh_models(self):
        self.models = self.list_models()

    def pick_model(self):
        if not self.models:
            return None
        ram = float(self.ram_var.get())
        if self.S["model"] != "auto":
            for m in self.models:
                if m["name"] == self.S["model"]:
                    return m
        pool = [m for m in self.models if is_builtin(m["name"])] or self.models
        ok = sorted([m for m in pool if mplan(m, ram)[0]], key=lambda m: (model_rank(m["name"]), -m["size"]))
        if ok:  # the smartest model that fits
            return ok[0]
        # nothing from the preferred family fits (e.g. a 4 GB laptop): use the biggest model that does fit
        ok = sorted([m for m in self.models if mplan(m, ram)[0]], key=lambda m: -m["size"])
        return ok[0] if ok else min(self.models, key=lambda m: m["size"])

    def ensure_ram_for(self, m):
        """Raise RAM Usage (only as far as this PC can spare) so model m fits with a useful amount of memory."""
        need = mplan(m, 1)[2] + 0.8
        if float(self.ram_var.get()) < need and need <= self.total_gb - 2:
            v = min(self.total_gb - 2, math.ceil(need * 2) / 2 + 0.5)
            self.ram_var.set(v)
            self.S["ram"] = v
            self.save_settings()
            return True
        return False

    def open_model_menu(self):
        """Simple model picker under the header chip."""
        pop = tk.Toplevel(self.root)
        pop.overrideredirect(True)
        pop.configure(bg=LINE)
        style_window(pop)
        body = tk.Frame(pop, bg=PANEL2)
        body.pack(padx=1, pady=1)
        tk.Label(body, text="Choose your AI", bg=PANEL2, fg=FG, font=UI_B).pack(anchor="w", padx=14, pady=(12, 0))
        tk.Label(body, text="Bigger models are smarter but slower.", bg=PANEL2, fg=MUTED, font=UI_XS).pack(anchor="w", padx=14, pady=(0, 8))

        def choose(name):
            pop.destroy()
            self.S["model"] = name
            m = self.pick_model()
            if m and not mplan(m, float(self.ram_var.get()))[0] and self.ensure_ram_for(m):
                self.say(f"RAM Usage raised to {self.ram_var.get():g} GB for {model_label(m['name'])[0]}")
            self.save_settings()
            self.on_ram_move()
            self.start_engine()

        rows = [("auto", "Auto", "Best AI for you", None)]
        for m in sorted(self.models, key=lambda m: (model_rank(m["name"]), -m["size"])):
            title, tag = model_label(m["name"])
            rows.append((m["name"], title, tag, m))
        for key, title, tag, m in rows:
            need = mplan(m, 1)[2] + 0.8 if m else 0
            too_big = bool(m) and need > self.total_gb - 1
            sel = self.S["model"] == key
            row = tk.Frame(body, bg=PANEL2, cursor="arrow" if too_big else "hand2")
            row.pack(fill="x", padx=6, pady=1)
            dot = tk.Canvas(row, width=26, height=26, bg=PANEL2, highlightthickness=0)
            dot.pack(side="left", padx=(8, 4), pady=6)
            if sel:
                draw_icon(dot, "check", 5, 5, 16, THEME["accent"])
            txt = tk.Frame(row, bg=PANEL2)
            txt.pack(side="left", fill="x", expand=True, padx=(0, 14))
            l1 = tk.Label(txt, text=title, bg=PANEL2, fg=(DIM if too_big else (THEME["accent"] if sel else FG)), font=UI_B, anchor="w")
            l1.pack(fill="x")
            sub = tag if not m else (f"{tag}  ·  needs ~{need:.0f} GB RAM" if not too_big else "Too big for this PC")
            l2 = tk.Label(txt, text=sub, bg=PANEL2, fg=MUTED, font=UI_XS, anchor="w")
            l2.pack(fill="x")
            if too_big:
                continue
            ws = (row, dot, txt, l1, l2)
            for wdg in ws:
                wdg.bind("<Button-1>", lambda e, k=key: choose(k))
                wdg.bind("<Enter>", lambda e, ws=ws: [x.configure(bg=HOVER) for x in ws])
                wdg.bind("<Leave>", lambda e, ws=ws: [x.configure(bg=PANEL2) for x in ws])
        foot = tk.Frame(body, bg=PANEL2)
        foot.pack(fill="x", padx=10, pady=(6, 10))
        RoundButton(foot, "More model settings", lambda: (pop.destroy(), self.open_settings()), kind="ghost", font=UI_XS,
                    padx=8, pady=4, icon="gear", icon_size=11, bg=PANEL2).pack(side="left")
        pop.update_idletasks()
        x = self.model_chip.winfo_rootx() + self.model_chip.winfo_width() - pop.winfo_reqwidth()
        pop.geometry(f"+{max(0, x)}+{self.model_chip.winfo_rooty() + self.model_chip.winfo_height() + 6}")
        pop.bind("<Escape>", lambda e: pop.destroy())
        pop.bind("<FocusOut>", lambda e: pop.after(150, lambda: pop.winfo_exists() and pop.focus_get() is None and pop.destroy()))
        pop.focus_force()

    def ram_text(self):
        v = round(float(self.ram_var.get()) * 2) / 2
        m = self.pick_model()
        if not m:
            return v, "No AI model found in the 'models' folder."
        fits, ctx, need, used = mplan(m, v)
        if self.total_gb <= 5 and ctx > 8192:
            used -= (ctx - 8192) * (0.03 + m["size"] / 1e9 * 1.05 * 0.008) / 1024
            ctx = 8192
        if not fits:
            return v, f"{pretty_model(m['name'])} needs about {need:.1f} GB. Raise the slider or pick a smaller model."
        txt = f"{pretty_model(m['name'])}  \u00B7  remembers ~{ctx:,} tokens  \u00B7  uses about {used:.1f} GB"
        if self.S["model"] == "auto":
            bigger = [x for x in self.models if x["name"].lower().startswith(m["name"].lower()[:5]) and x["size"] > m["size"]]
            if bigger:
                b = max(bigger, key=lambda x: x["size"])
                txt += f"\nTip: raise to {math.ceil(plan(b['size'], 1)[2] * 2) / 2:g} GB to use {pretty_model(b['name'])} (smarter, slower)."
        return v, txt

    def is_small_model(self, m=None):
        m = m or self.pick_model()
        return bool(m) and m["size"] < 4.5e9

    def update_qb(self):
        if not hasattr(self, "qb_btn"):
            return
        if self.is_small_model():
            if not self.qb_btn.winfo_ismapped():
                self.qb_btn.pack(side="left", padx=6)
        else:
            self.qb_btn.pack_forget()

    def update_chip(self):
        if hasattr(self, "qb_btn"):
            self.root.after(0, self.update_qb)
        m = self.pick_model()
        v = round(float(self.ram_var.get()) * 2) / 2
        self.model_chip.set_text("{}  \u00B7  {}  \u25BE".format(*model_label(m["name"])) if m else "No model")

    def on_ram_move(self, _=None):
        v, info = self.ram_text()
        if self.settings_win and self.settings_win.winfo_exists():
            self.sw_ram_lbl.configure(text=f"{v:g} GB")
            self.sw_ram_info.configure(text=info)
        self.update_chip()

    def on_ram_release(self):
        self.S["ram"] = round(float(self.ram_var.get()) * 2) / 2
        self.save_settings()
        self.start_engine()

    def add_model(self):
        src = filedialog.askopenfilename(title="Choose a .gguf model", filetypes=[("GGUF models", "*.gguf")])
        if not src:
            return
        dst = os.path.join(MODELS, os.path.basename(src))
        if os.path.exists(dst):
            return self.say("That model is already installed")
        total = os.path.getsize(src)
        self.say("Copying model... 0%", 60000)

        def work():
            try:
                done = 0
                with open(src, "rb") as a, open(dst + ".part", "wb") as b:
                    while True:
                        buf = a.read(8 << 20)
                        if not buf:
                            break
                        b.write(buf)
                        done += len(buf)
                        self.q.put(("copy", int(done * 100 / max(1, total))))
                os.replace(dst + ".part", dst)
                self.q.put(("copied", os.path.basename(dst)))
            except OSError as e:
                self.q.put(("copyerr", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def remove_model(self, name):
        if is_builtin(name):
            return self.say("Built-in models can't be removed here")
        if not messagebox.askyesno("Remove model", f"Delete {name} from the models folder?\nThis can't be undone.", parent=self.settings_win):
            return
        if self.engine.model and os.path.basename(self.engine.model) == name:
            self.engine.stop()
        try:
            os.remove(os.path.join(MODELS, name))
        except OSError as e:
            return self.say(f"Couldn't remove: {e}")
        self.S["model"] = "auto"
        self.save_settings()
        self.refresh_models()
        self.reopen_settings()
        self.start_engine()

    # ---- engine lifecycle
    def set_pill(self, state):
        txt = {"loading": ("Loading AI...", WARN), "ready": ("AI ready", GOOD),
               "error": ("AI failed to start", BAD), "none": ("No AI model", BAD)}[state]
        self.pill.set(*txt)

    def start_engine(self):
        if not self.S.get("gemmaDefault") and not self.selftest:
            gem = sorted([m for m in self.models if m["name"].lower().startswith("gemma")], key=lambda m: -m["size"])
            fit = [m for m in gem if mplan(m, 1)[2] + 0.8 <= self.total_gb - 2]
            if fit:  # one-time switch to Gemma: Auto + enough RAM for the best Gemma this PC can run
                self.S["model"] = "auto"
                self.ensure_ram_for(fit[0])
                self.S["gemmaDefault"] = True
                self.save_settings()
        self.update_chip()
        if not os.path.exists(ENGINE):
            self.set_pill("none")
            return self.chat_note("The AI engine is missing (engine\\llama-server.exe).", BAD)
        m = self.pick_model()
        if not m:
            self.set_pill("none")
            return self.chat_note("No AI model found. Put a .gguf file in the 'models' folder next to Profound.exe.", BAD)
        ctx = mplan(m, float(self.ram_var.get()))[1]
        if self.total_gb <= 5:  # small-RAM PCs (e.g. 4 GB laptops): keep memory low, but room for a template + page
            ctx = min(ctx, 8192)
        if self.engine.alive() and self.engine.model == m["path"] and self.engine.ctx == ctx:
            return
        self.ready = False
        self.boot_id += 1
        bid = self.boot_id
        self.set_pill("loading")

        def boot():
            self.engine.start(m["path"], ctx)
            self.q.put(("ready", bid, self.engine.wait_ready()))
        threading.Thread(target=boot, daemon=True).start()

    # ---- explorer
    def open_folder(self):
        if any(t.dirty() for t in self.tabs) and not messagebox.askyesno("Profound", "You have unsaved changes. Open another folder anyway?"):
            return
        p = filedialog.askdirectory(title="Open a project folder")
        if p:
            self.set_workspace(os.path.normpath(p))

    def set_workspace(self, p):
        for t in [t for t in self.tabs if isinstance(t, EditorTab)]:
            self.tabs.remove(t)
            t.destroy()
        if self.active not in self.tabs:
            self.active = None
        self.workspace = p
        self.S["lastFolder"] = p
        self.save_settings()
        self.folder_lbl.configure(text="\U0001F4C2  " + p)
        self.side_title.configure(text=os.path.basename(p).upper() or p)
        if str(self.left) not in [str(x) for x in self.pw.panes()]:
            self.pw.add(self.left, before=self.mid, width=240, minsize=160)
        self.refresh_tabs()
        self.refresh_tree()

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.tree_map = {}
        if not self.workspace:
            return
        count = [0]

        def fill(parent, d, depth):
            try:
                ents = sorted(os.scandir(d), key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                return
            for e in ents:
                if e.name in SKIP or e.name.startswith(".") or count[0] > 3000:
                    continue
                count[0] += 1
                isdir = e.is_dir(follow_symlinks=False)
                img = self.tree_img("folder" if isdir else lang_color(e.name))
                iid = self.tree.insert(parent, "end", text="  " + e.name, image=img, open=False)
                self.tree_map[iid] = (os.path.relpath(e.path, self.workspace).replace("\\", "/"), isdir)
                if isdir and depth < 5:
                    fill(iid, e.path, depth + 1)
        fill("", self.workspace, 0)

    def tree_img(self, key):
        """Small drawn icons for the file tree: a folder, or a coloured dot per language."""
        cache = self.__dict__.setdefault("_tree_imgs", {})
        if key in cache:
            return cache[key]
        n = 18
        img = tk.PhotoImage(width=n, height=n)
        if key == "folder":
            col = "#d9a94e"
            img.put(col, to=(2, 4, 8, 6))
            img.put(col, to=(2, 6, 16, 15))
            img.put(shade(col, 0.25), to=(2, 7, 16, 8))
        else:
            cx = cy = (n - 1) / 2
            for yy in range(n):
                xs = [xx for xx in range(n) if (xx - cx) ** 2 + (yy - cy) ** 2 <= 4.2 ** 2]
                if xs:
                    img.put(key, to=(xs[0], yy, xs[-1] + 1, yy + 1))
        cache[key] = img
        return img

    def on_tree_select(self, _=None):
        sel = self.tree.selection()
        if sel and sel[0] in self.tree_map:
            rel, isdir = self.tree_map[sel[0]]
            if isdir:
                self.tree.item(sel[0], open=not self.tree.item(sel[0], "open"))
            else:
                self.open_file(rel)

    def new_file(self):
        if not self.workspace:
            self.say("First pick a folder to keep your files in")
            self.open_folder()
            if not self.workspace:
                return
        name = simpledialog.askstring("New file", "File name (for example  app.py,  index.html,  main.rs):", parent=self.root)
        rel = self.clean_rel(name or "")
        if rel:
            self.open_file(rel, is_new=True)

    # ---- files / tabs
    def clean_rel(self, p):
        p = re.sub(r"^\./", "", (p or "").strip().replace("\\", "/"))
        if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/"):
            return None
        return p

    def abs_path(self, rel):
        root = os.path.realpath(self.workspace)
        full = os.path.realpath(os.path.join(root, rel))
        if not self.workspace or os.path.commonpath([root, full]) != root:
            raise PermissionError("Path is outside the opened folder")
        return full

    def find_tab(self, rel):
        return next((t for t in self.tabs if isinstance(t, EditorTab) and t.path == rel), None)

    def open_file(self, rel, is_new=False, content=None, select=True):
        t = self.find_tab(rel)
        if not t:
            disk = None
            if not is_new:
                try:
                    p = self.abs_path(rel)
                    if os.path.getsize(p) > 2_000_000:
                        return self.say("That file is too large to open")
                    with open(p, "rb") as f:
                        raw = f.read()
                    if b"\0" in raw[:4096]:
                        return self.say("That looks like a binary file, it can't be edited here")
                    disk = raw.decode("utf-8", "replace")
                except (OSError, PermissionError) as e:
                    return self.say(f"Can't open: {e}")
            t = EditorTab(self, rel, content if content is not None else (disk or ""), disk)
            self.tabs.append(t)
        if select or self.active is None:
            self.select_tab(t)
        else:
            self.refresh_tabs()
        if self.S["autoPreview"] and os.path.splitext(rel)[1].lower() in (".html", ".htm") and not self.selftest:
            self.show_preview(page=rel, focus=False)
        return t

    def current_tab(self):
        return self.active if isinstance(self.active, EditorTab) else None

    def select_tab(self, t):
        if t not in self.tabs:
            self.tabs.append(t)
        if self.active is not t:
            if self.active is not None and self.active.winfo_exists():
                if isinstance(self.active, PreviewTab):
                    self.active.park()
                else:
                    self.active.pack_forget()
            self.active = t
            if isinstance(t, PreviewTab):
                t.unpark()
            t.pack(fill="both", expand=True)
        self.refresh_tabs()
        if isinstance(t, PreviewTab):
            t.ensure()
            t.after(50, t._resize)
        if isinstance(t, EditorTab):
            t.text.focus_set()
            ext = os.path.splitext(t.path)[1].lower()
            if ext in (".html", ".htm") and self.preview.page != t.path and self.preview_shown():
                self.preview.set_page(page=t.path)
                self.preview_tab.set_label()

    def close_tab(self, t):
        if t.dirty() and not messagebox.askyesno("Profound", f"Close {t.path} without saving?"):
            return
        i = self.tabs.index(t)
        self.tabs.remove(t)
        if isinstance(t, PreviewTab):
            t.park()
        else:
            t.pack_forget()
        if isinstance(t, EditorTab):
            t.destroy()
        if self.active is t:
            self.active = None
            if self.tabs:
                self.select_tab(self.tabs[max(0, i - 1)])
        self.refresh_tabs()

    def on_tab_changed(self, t):
        self.refresh_tabs()
        if getattr(self, "_pv_job", None):
            self.root.after_cancel(self._pv_job)
        self._pv_job = self.root.after(300, self.preview.sync)

    def refresh_tabs(self):
        sig = tuple((id(t), t.dirty(), t is self.active) for t in self.tabs)
        if sig != self._tab_sig:
            self._tab_sig = sig
            for w in self.tabbar.winfo_children():
                w.destroy()
            for t in self.tabs:
                TabPill(self.tabbar, self, t).pack(side="left", padx=(0, 3), pady=5)
        cur = self.current_tab()
        if self.tabs:
            self.welcome.place_forget()
        else:
            self.welcome.place(x=0, y=0, relwidth=1, relheight=1)
            self.welcome.lift()
        self.path_lbl.configure(text=(cur.path + ("   \u2022 unsaved" if cur.dirty() else "")) if cur else "")
        self.save_btn.set_enabled(bool(cur))
        ext = os.path.splitext(cur.path)[1].lower() if cur else ""
        self.run_btn.set_enabled(bool(cur) and ext in RUNNERS and ext not in WEB_EXT)
        if hasattr(self, "pv_btn"):
            self.pv_btn.set_enabled(self.preview_source() is not None)

    def save_tab(self, t):
        if not self.workspace:
            self.say("Open a folder first")
            return False
        try:
            p = self.abs_path(t.path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            c = t.content()
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(c)
            t.saved = c
            self.refresh_tabs()
            self.say("Saved " + t.path)
            if t.path not in [v[0] for v in self.tree_map.values()]:
                self.refresh_tree()
            return True
        except (OSError, PermissionError) as e:
            messagebox.showerror("Profound", f"Could not save: {e}")
            return False

    def save_current(self):
        t = self.current_tab()
        if t:
            self.save_tab(t)

    def save_snippet(self, code, lang, path=""):
        ext = os.path.splitext(path)[1] if path else EXT_FOR.get((lang or "").lower(), ".txt")
        if self.workspace:
            name = simpledialog.askstring("Save code", "File name:", initialvalue=os.path.basename(path) or ("snippet" + ext), parent=self.root)
            rel = self.clean_rel(name or "")
            if rel:
                t = self.open_file(rel, is_new=self.find_tab(rel) is None and not os.path.exists(os.path.join(self.workspace, rel)), content=code)
                if t:
                    t.set_content(code)
                    self.save_tab(t)
        else:
            f = filedialog.asksaveasfilename(defaultextension=ext, initialfile=os.path.basename(path) or ("snippet" + ext))
            if f:
                with open(f, "w", encoding="utf-8", newline="") as fh:
                    fh.write(code)
                self.say("Saved " + os.path.basename(f))

    def preview_source(self):
        """What the toolbar Preview button would show: the open web file, else the page written in chat."""
        cur = self.current_tab()
        if cur and os.path.splitext(cur.path)[1].lower() in WEB_EXT:
            return ("file", cur)
        wf = self.snippets.working("html") if hasattr(self, "snippets") else None
        if wf is not None and wf.lang in ("html", "htm"):
            return ("snippet", wf.code)
        if self.preview.page or self.preview.snippet is not None:
            return ("last", None)
        return None

    def toolbar_preview(self):
        src = self.preview_source()
        if src is None:
            return self.say("No web page yet. Ask for one and it will show here.")
        if src[0] == "file":
            return self.run_current()
        if src[0] == "snippet":
            return self.show_preview(snippet=src[1])
        if self.preview_tab not in self.tabs:
            self.tabs.append(self.preview_tab)
        self.select_tab(self.preview_tab)

    def preview_shown(self):
        return self.preview_tab in self.tabs

    def show_preview(self, page=None, snippet=None, focus=True):
        """Live preview as its own tab next to Code: focus=True switches to it, otherwise it just appears in the tab bar."""
        self.preview.set_page(page=page, snippet=snippet)
        if self.preview_tab not in self.tabs:
            self.tabs.append(self.preview_tab)
        self.preview_tab.set_label()
        if focus:
            self.select_tab(self.preview_tab)
        else:
            self.refresh_tabs()
            self.preview_tab.ensure()  # warm up the preview so it is instant when you click the tab

    def hide_preview(self):
        if self.preview_tab in self.tabs:
            self.close_tab(self.preview_tab)

    def run_current(self):
        t = self.current_tab()
        if not t:
            return
        ext = os.path.splitext(t.path)[1].lower()
        if ext in WEB_EXT:
            page = t.path if ext in (".html", ".htm") else (self.preview.page or next(
                (x.path for x in self.tabs if isinstance(x, EditorTab) and x.path.lower().endswith((".html", ".htm"))), None))
            if not page:
                return self.say("Open the HTML page that uses this file to preview it")
            return self.show_preview(page=page)
        if ext not in RUNNERS:
            return self.say("Run doesn't support this file type yet")
        if not self.save_tab(t):
            return
        p = self.abs_path(t.path)
        for prog, tpl in RUNNERS[ext]:
            exe = shutil.which(prog)
            if exe:
                out = os.path.join(tempfile.gettempdir(), "profound_run_" + os.path.splitext(os.path.basename(p))[0] + (".exe" if WIN else ""))
                cmd = tpl.format(exe=exe, f=p, o=out)
                if not open_terminal(cmd, os.path.dirname(p)):
                    self.say("Couldn't find a terminal app to run it in")
                return
        self.say(f"To run {LANG_INFO.get(ext, ('', ext))[1]} files, install {RUN_NAMES.get(ext, 'its tools')}")

    # ---- chat widgets
    def chat_row(self, padx=(14, 14), pady=(12, 2)):
        f = tk.Frame(self.chat_sf.inner, bg=PANEL)
        f.pack(fill="x", padx=padx, pady=pady)
        return f

    def ai_header(self, parent):
        hdr = tk.Frame(parent, bg=PANEL)
        hdr.pack(fill="x")
        if self.logo_tiny:
            self.last_avatar = tk.Label(hdr, image=self.logo_tiny, bg=PANEL)
            self.last_avatar.pack(side="left", padx=(0, 6))
        tk.Label(hdr, text="Profound", bg=PANEL, fg=FG, font=UI_B).pack(side="left")
        body = tk.Frame(parent, bg=PANEL)
        body.pack(fill="x", pady=(6, 0))
        return body

    def chat_note(self, text, color=GOOD, parent=None):
        lbl = tk.Label(parent or self.chat_row(pady=(4, 2)), text=text, bg=PANEL, fg=color, font=UI_SM, anchor="w",
                       justify="left", wraplength=400)
        lbl.pack(fill="x", pady=(4, 0))
        self.chat_sf.wheel(lbl)
        self.chat_sf.bottom()
        return lbl

    def add_user_msg(self, text, attachments=None, paths=None):
        row = self.chat_row(padx=(56, 14), pady=(14, 2))
        self.last_user_row = row
        card = Card(row, fill=USER_BG, radius=16, padx=14, pady=10)
        card.pack(fill="x")
        if text:
            t = auto_text(card.inner, bg=USER_BG)
            t.insert("1.0", text)
            t.configure(state="disabled")
            t.pack(fill="x")
            t.fit()
        if attachments:
            paths = paths or [self.asset_path(n) for n in attachments]
            pics = [(n, p) for n, p in zip(attachments, paths) if p and os.path.splitext(n)[1].lower() in IMG_EXT]
            if pics:
                gallery = tk.Frame(card.inner, bg=USER_BG)
                gallery.pack(fill="x", pady=(6 if text else 0, 0))
                for n, p in pics:
                    img = make_thumb(p, 200)
                    if img:
                        tk.Label(gallery, image=img, bg=USER_BG, borderwidth=0).pack(side="left", padx=(0, 8), anchor="w")
            chips = tk.Frame(card.inner, bg=USER_BG)
            chips.pack(fill="x", pady=(6, 0))
            for name in attachments:
                c = tk.Canvas(chips, width=16, height=16, bg=USER_BG, highlightthickness=0)
                c.pack(side="left")
                draw_icon(c, "image" if os.path.splitext(name)[1].lower() in IMG_EXT else "clip", 1, 1, 14, MUTED)
                tk.Label(chips, text=name, bg=USER_BG, fg=MUTED, font=UI_XS).pack(side="left", padx=(2, 10))
        self.chat_sf.wheel_tree(row)
        self.chat_sf.bottom()

    def asset_path(self, name):
        if self.workspace:
            p = os.path.join(self.workspace, "assets", name)
            if os.path.exists(p):
                return p
        return None

    # ---- attachments (images, audio, any file)
    def attach_files(self):
        self.add_attachment_paths(filedialog.askopenfilenames(title="Attach images or files"))

    def on_drop(self, paths):
        """Files dropped on the window: attach them. A single folder: open it as the project."""
        paths = [p for p in paths if p]
        if len(paths) == 1 and os.path.isdir(paths[0]):
            return self.set_workspace(os.path.normpath(paths[0]))
        files = [p for p in paths if os.path.isfile(p)]
        if files:
            self.add_attachment_paths(files)
            self.say(f"Attached {len(files)} file{'s' if len(files) != 1 else ''}")

    def add_attachment_paths(self, files):
        for p in files:
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            if size > 200 * 2 ** 20:
                self.say(f"{os.path.basename(p)} is too big (over 200 MB)")
                continue
            ext = os.path.splitext(p)[1].lower()
            kind = "image" if ext in IMG_EXT else ("text" if (ext in LANG_INFO or ext in TEXT_EXT) and size < 400_000 else "file")
            if not any(a["path"] == p for a in self.attachments):
                self.attachments.append({"path": p, "name": os.path.basename(p), "kind": kind, "size": size})
        self.refresh_attach_row()
        if files:
            self.inp.focus_set()

    def refresh_attach_row(self):
        for w in self.attach_row.winfo_children():
            w.destroy()
        if not self.attachments:
            self.attach_row.pack_forget()
            return
        self.attach_row.pack(fill="x", pady=(0, 6), before=self.inbox)
        for a in self.attachments:
            chip = Card(self.attach_row, fill=PANEL2, radius=10, padx=8, pady=4, fit_width=True)
            chip.pack(side="left", padx=(0, 6))
            thumb = make_thumb(a["path"], 36) if a["kind"] == "image" else None
            if thumb:
                tk.Label(chip.inner, image=thumb, bg=PANEL2).pack(side="left")
            else:
                c = tk.Canvas(chip.inner, width=16, height=16, bg=PANEL2, highlightthickness=0)
                c.pack(side="left")
                draw_icon(c, {"image": "image", "text": "code"}.get(a["kind"], "clip"), 1, 1, 14, THEME["accent"])
            nm = a["name"] if len(a["name"]) <= 22 else a["name"][:19] + "..."
            tk.Label(chip.inner, text=f"{nm}  {human_size(a['size'])}", bg=PANEL2, fg=FG, font=UI_XS).pack(side="left", padx=(4, 2))
            RoundButton(chip.inner, "", lambda a=a: (self.attachments.remove(a), self.refresh_attach_row()), kind="ghost",
                        padx=3, pady=3, radius=6, icon="x", icon_size=10, bg=PANEL2).pack(side="left")

    def prepare_attachments(self, atts):
        """Copy files into the project's assets folder and describe them for the AI.
        Returns (note for the AI, image data-URLs the model can look at, display names)."""
        import base64
        lines, images, names, copied = [], [], [], False
        dest_dir = None
        if self.workspace:
            try:
                dest_dir = self.abs_path("assets")
                os.makedirs(dest_dir, exist_ok=True)
            except (OSError, PermissionError):
                dest_dir = None
        for a in atts:
            p, name, ext = a["path"], a["name"], os.path.splitext(a["name"])[1].lower()
            rel = None
            if dest_dir:
                target, i = os.path.join(dest_dir, name), 1
                base_, ext_ = os.path.splitext(name)
                while os.path.exists(target) and os.path.getsize(target) != a["size"]:
                    target = os.path.join(dest_dir, f"{base_}-{i}{ext_}")
                    i += 1
                try:
                    if not os.path.exists(target):
                        shutil.copy2(p, target)
                    rel = "assets/" + os.path.basename(target)
                    copied = True
                except OSError:
                    rel = None
            where = rel or name
            names.append(os.path.basename(where))
            mime = mimetypes.guess_type(name)[0] or "file"
            if a["kind"] == "image":
                can_see = self.engine.vision and ext in VISION_EXT and a["size"] <= 10 * 2 ** 20
                if can_see:
                    with open(p, "rb") as f:
                        images.append(f"data:{mimetypes.guess_type(name)[0] or 'image/png'};base64," + base64.b64encode(f.read()).decode())
                lines.append(f"- {where} (image, {human_size(a['size'])})" + (" - attached below so you can see it." if can_see else
                             " - you can't see images with the current model, but you can use it in code by its path."))
            elif a["kind"] == "text":
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        body = f.read(12000)
                except OSError:
                    body = ""
                lines.append(f"- {where} (text file). Contents:\n```\n{body}\n```")
            else:
                lines.append(f"- {where} ({mime}, {human_size(a['size'])}) - use it in code by this path.")
        note = "I attached these files:\n" + "\n".join(lines)
        if copied:
            note += "\nThey are saved in my project's assets folder; reference them by the paths above (relative to the project root)."
            self.refresh_tree()
        elif atts and not self.workspace:
            note += "\n(No project folder is open, so they weren't copied into a project.)"
        return note, images, names

    def chat_welcome(self):
        body = self.ai_header(self.chat_row(pady=(10, 2)))
        t = auto_text(body, bg=PANEL)
        t.insert("1.0", "Hi! I'm your offline coding assistant. Ask me about any language, or try one of these:")
        t.configure(state="disabled")
        t.pack(fill="x")
        for s in SUGGESTIONS:
            RoundButton(body, s, lambda s=s: self.quick(s), kind="chip", font=UI_SM, padx=12, pady=6, radius=10, icon="spark", icon_size=12).pack(anchor="w", pady=(6, 0))
        self.chat_sf.wheel_tree(body.master)

    def quick(self, s):
        self.set_input(s)
        self.send()

    def new_chat(self):
        if self.busy:
            self.stop_reply()
        self.history = []
        self.chat_id, self.chat_title, self.chat_renamed = None, None, False
        self.last_user_row = None
        self.attachments = []
        self.refresh_attach_row()
        self.clear_chat_view()
        self.chat_welcome()
        self.chat_sf.canvas.yview_moveto(0)

    # ---- saved chats
    def clear_chat_view(self):
        for w in self.chat_sf.inner.winfo_children():
            w.destroy()
        self.cur_body = self.stream_t = None
        self.snippets.clear()
        if self.snippets in self.tabs:
            self.close_tab(self.snippets)

    def save_chat(self):
        if self.selftest or self.testing or not self.chat_id or not self.history:
            return
        first = next((m["content"] for m in self.history if m["role"] == "user"), "Chat")
        title = self.chat_title if self.chat_renamed and self.chat_title else first.strip().split("\n")[0][:80]
        data = {"id": self.chat_id, "title": title, "renamed": self.chat_renamed, "created": self.chat_created,
                "updated": time.time(), "messages": self.history}
        try:
            os.makedirs(CHATS_DIR, exist_ok=True)
            with open(os.path.join(CHATS_DIR, self.chat_id + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError as e:
            log_error(f"save chat: {e}")

    def list_chats(self):
        out = []
        for p in glob.glob(os.path.join(CHATS_DIR, "*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                out.append(d)
            except (OSError, ValueError):
                pass
        return sorted(out, key=lambda d: -d.get("updated", 0))

    def show_history(self):
        if getattr(self, "hist", None) is not None and self.hist.winfo_exists():
            self.hist.destroy()
            return
        h = self.hist = tk.Frame(self.right, bg=PANEL)
        h.place(x=0, y=0, relwidth=1, relheight=1)
        head = tk.Frame(h, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(16, 8))
        tk.Label(head, text="Saved chats", bg=PANEL, fg=FG, font=(SANS_SEMI, 14)).pack(side="left")
        RoundButton(head, "", h.destroy, kind="ghost", padx=6, pady=6, icon="x", icon_size=13).pack(side="right")
        RoundButton(head, "New chat", lambda: (h.destroy(), self.new_chat()), kind="accent", font=UI_SM, padx=12, pady=5,
                    icon="plus", icon_size=12).pack(side="right", padx=6)
        sf = ScrollFrame(h, PANEL)
        sf.pack(fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        chats = self.list_chats()
        if not chats:
            tk.Label(sf.inner, text="No saved chats yet. Chats save automatically after each reply.", bg=PANEL, fg=DIM,
                     font=UI_SM).pack(pady=40)
        for d in chats:
            card = Card(sf.inner, fill=CARD if d["id"] != self.chat_id else "#1e2d22", radius=12, padx=12, pady=9)
            card.pack(fill="x", padx=(0, 12), pady=4)
            row = card.inner
            n = sum(1 for m in d.get("messages", []) if m["role"] == "user")
            txt = tk.Frame(row, bg=row.cget("bg"), cursor="hand2")
            txt.pack(side="left", fill="x", expand=True)
            l1 = tk.Label(txt, text=d.get("title", "Chat"), bg=row.cget("bg"), fg=FG, font=UI_B, anchor="w", cursor="hand2")
            l1.pack(fill="x")
            l2 = tk.Label(txt, text=time.strftime("%d %b %Y, %H:%M", time.localtime(d.get("updated", 0))) +
                          f"  ·  {n} message{'s' if n != 1 else ''}", bg=row.cget("bg"), fg=MUTED, font=UI_XS, anchor="w", cursor="hand2")
            l2.pack(fill="x")
            for wdg in (txt, l1, l2):
                wdg.bind("<Button-1>", lambda e, cid=d["id"]: self.load_chat(cid))
            RoundButton(row, "", lambda cid=d["id"], t=d.get("title", ""): self.delete_chat(cid, t), kind="ghost",
                        padx=6, pady=5, radius=8, icon="trash", icon_size=13, bg=row.cget("bg")).pack(side="right")
            RoundButton(row, "", lambda cid=d["id"], t=d.get("title", ""): self.rename_chat(cid, t), kind="ghost",
                        padx=6, pady=5, radius=8, icon="pencil", icon_size=13, bg=row.cget("bg")).pack(side="right")
        sf.wheel_tree(sf.inner)

    def rename_chat(self, cid, title):
        new = simpledialog.askstring("Rename chat", "New name:", initialvalue=title, parent=self.root)
        if not new or not new.strip():
            return
        p = os.path.join(CHATS_DIR, cid + ".json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["title"], d["renamed"] = new.strip()[:80], True
            with open(p, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except (OSError, ValueError) as e:
            return self.say(f"Couldn't rename: {e}")
        if cid == self.chat_id:
            self.chat_title, self.chat_renamed = new.strip()[:80], True
        self.hist.destroy()
        self.show_history()

    def delete_chat(self, cid, title):
        if not messagebox.askyesno("Delete chat", f"Delete “{title[:60]}”? This can't be undone."):
            return
        try:
            os.remove(os.path.join(CHATS_DIR, cid + ".json"))
        except OSError:
            pass
        if cid == self.chat_id:
            self.chat_id = None
        self.hist.destroy()
        self.show_history()

    def load_chat(self, cid):
        if self.busy:
            return self.say("Wait for the current reply to finish")
        try:
            with open(os.path.join(CHATS_DIR, cid + ".json"), "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return self.say("Couldn't open that chat")
        if getattr(self, "hist", None) is not None and self.hist.winfo_exists():
            self.hist.destroy()
        self.clear_chat_view()
        self.history, self.chat_id, self.chat_created = d.get("messages", []), d["id"], d.get("created", time.time())
        self.chat_title, self.chat_renamed = d.get("title"), bool(d.get("renamed"))
        for m in self.history:
            if m["role"] == "user":
                shown = re.sub(r"\n\[Attached: [^\]]*\]$", "", m["content"])
                self.last_question = shown
                self.add_user_msg(shown, m.get("attachments"))
            else:
                body = self.ai_header(self.chat_row())
                self.render_ai(body, m["content"], mode=m.get("mode", "edit"))
        self.chat_sf.wheel_tree(self.chat_sf.inner)
        self.root.after(80, self.show_latest)

    def md_text(self, parent, text, before=None):
        t = auto_text(parent, bg=PANEL)
        t.tag_configure("b", font=CHAT_B)
        t.tag_configure("ic", font=(MONO, 10), background="#1f2a22", foreground="#d6e86b")
        t.tag_configure("h", font=UI_H, spacing1=6, spacing3=2)
        t.tag_configure("li", lmargin1=4, lmargin2=20)
        lines = text.strip("\n").split("\n")
        for i, line in enumerate(lines):
            tags = ()
            m = re.match(r"^\s{0,3}#{1,6}\s+(.*)", line)
            if m:
                line, tags = m.group(1), ("h",)
            else:
                m = re.match(r"^\s*[-*+]\s+(.*)", line) or None
                if m:
                    line, tags = "\u2022  " + m.group(1), ("li",)
                else:
                    m = re.match(r"^\s*(\d+)[.)]\s+(.*)", line)
                    if m:
                        line, tags = f"{m.group(1)}.  {m.group(2)}", ("li",)
            for part in re.split(r"(\*\*[^*\n]+\*\*|`[^`\n]+`)", line):
                if not part:
                    continue
                if part.startswith("**") and part.endswith("**") and len(part) > 4:
                    t.insert("end", part[2:-2].replace("`", ""), tags + ("b",))
                elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                    t.insert("end", part[1:-1], tags + ("ic",))
                else:
                    t.insert("end", part, tags)
            if i < len(lines) - 1:
                t.insert("end", "\n", tags)
        t.configure(state="disabled")
        if before is not None:
            t.pack(fill="x", pady=(0, 4), before=before)
        else:
            t.pack(fill="x", pady=(0, 4))
        t.fit()
        return t

    def code_card(self, parent, code, lang, path, actions, collapsed=True, heading=None, bg=None):
        card = Card(parent, fill=CODE_BG, radius=12, padx=12, pady=9, bg=bg or PANEL)
        card.pack(fill="x", pady=6)
        hdr = tk.Frame(card.inner, bg=CODE_BG)
        hdr.pack(fill="x")
        title = heading or (path or lang_label(lang, path))
        tk.Label(hdr, text=title, bg=CODE_BG, fg=MUTED, font=UI_SM).pack(side="left")
        if heading:
            tk.Label(hdr, text="  " + lang_label(lang, path), bg=CODE_BG, fg=DIM, font=UI_XS).pack(side="left")
        icons = {"Copy": "copy", "Preview": "eye", "Save": "save", "Put": "pencil"}
        for label, fn in reversed(actions):
            RoundButton(hdr, label, fn, kind="code", font=UI_XS, padx=9, pady=3, radius=7, bg=CODE_BG,
                        icon=icons.get(label.split()[0]), icon_size=11).pack(side="right", padx=(4, 0))
        tk.Frame(card.inner, bg="#1a221c", height=1).pack(fill="x", pady=(8, 8))
        t = auto_text(card.inner, bg=CODE_BG, fg="#d6dbe4", font=(MONO, 10), wrap="none")
        setup_hl(t, 10)
        t.insert("1.0", code)
        highlight(t, code, fam_for(lang, path))
        t.configure(state="disabled")
        n = code.count("\n") + 1
        if collapsed and n > 16:
            t._maxh = 14
        t.pack(fill="x")
        t.fit()
        t.bind("<Shift-MouseWheel>", lambda e: (t.xview_scroll(int(-e.delta / 120) * 6, "units"), "break")[1])
        if t._maxh:
            def toggle():
                t._maxh = None if t._maxh else 14
                more.set_text("Show less" if not t._maxh else f"Show all {n} lines")
                t.fit()
            more = RoundButton(card.inner, f"Show all {n} lines", toggle, kind="code", font=UI_XS, padx=9, pady=3, radius=7, bg=CODE_BG, icon="expand", icon_size=11)
            more.pack(anchor="w", pady=(8, 0))
        return card

    def snippet_chip(self, parent, code, lang, path, mode="ask"):
        heading = (self.last_question[:48] + "...") if len(self.last_question) > 48 else self.last_question
        card = self.snippets.add(code, lang, path, heading, mode)
        chip = Card(parent, fill=PANEL2, radius=12, padx=12, pady=8)
        chip.pack(fill="x", pady=5)
        n = code.count("\n") + 1
        ll = lang_label(lang, path)
        tk.Label(chip.inner, text=f"</>   {ll + ' code' if ll != 'Code' else 'Code'}  \u00B7  {n} line{'s' if n != 1 else ''}",
                 bg=PANEL2, fg=FG, font=UI_SM).pack(side="left")
        RoundButton(chip.inner, "View code", lambda: self.snippets.focus_card(card), kind="accent", font=UI_XS, icon="arrow", icon_size=11,
                    padx=10, pady=3, radius=8, bg=PANEL2).pack(side="right")
        RoundButton(chip.inner, "Copy", lambda: self.copy(code), kind="code", font=UI_XS, padx=9, pady=3, radius=8, icon="copy", icon_size=11,
                    bg=PANEL2).pack(side="right", padx=4)
        if self.snippets not in self.tabs:
            self.tabs.append(self.snippets)
            self.refresh_tabs()

    def render_ai(self, body, full, mode=None):
        mode = mode or self.S["mode"]
        for w in body.winfo_children():
            w.destroy()
        parts = full.split("```")
        for i, p in enumerate(parts):
            if i % 2 == 0:
                if p.strip():
                    self.md_text(body, p)
                continue
            nl = p.find("\n")
            info = p[:nl] if nl > -1 else p
            code = (p[nl + 1:] if nl > -1 else "").rstrip("\n")
            if not code.strip():
                continue
            lang, path = self.parse_fence(info)
            self.snippet_chip(body, code, lang, path, mode)  # code always lives in the Code tab, never in the chat
        self.chat_sf.wheel_tree(body)

    @staticmethod
    def parse_fence(info):
        info = info.strip()
        if not info:
            return "", ""
        m = re.match(r"^([\w+#-]*)\s*[:\s]\s*(\S.*)?$", info)
        if m and m.group(2):
            return m.group(1).lower(), m.group(2).strip()
        return info.split()[0].lower(), ""

    def extract_blocks(self, text):
        parts, out = text.split("```"), []
        for i, p in enumerate(parts):
            if i % 2 == 1 and i < len(parts) - 1:
                nl = p.find("\n")
                lang, path = self.parse_fence(p[:nl] if nl > -1 else p)
                out.append({"lang": lang, "path": path, "code": (p[nl + 1:] if nl > -1 else "").rstrip("\n")})
        return out

    def apply_code(self, code, path="", focus=True):
        """Put code into an editor tab (saved to disk only when you save, unless auto-save is on)."""
        if not self.workspace:
            self.say("Open a folder first so I can put code into files")
            return None
        if not path:
            cur = self.current_tab()
            path = cur.path if cur else (simpledialog.askstring("Profound", "File name for this code:", parent=self.root) or "")
        rel = self.clean_rel(path)
        if not rel:
            self.say("That file path isn't allowed")
            return None
        t = self.find_tab(rel)
        if t:
            t.set_content(code)
            if focus:
                self.select_tab(t)
            self.on_tab_changed(t)
        else:
            disk = None
            try:
                with open(self.abs_path(rel), "r", encoding="utf-8", errors="replace") as f:
                    disk = f.read()
            except (OSError, PermissionError):
                disk = None
            t = self.open_file(rel, is_new=disk is None, content=code, select=focus)
            if t:
                t.saved = disk
        self.refresh_tabs()
        self.say("Updated " + rel + " \u2014 review it, then Save")
        return t

    def auto_apply(self, text, body):
        bl = [b for b in self.extract_blocks(text) if b["code"].strip()]
        targets = [b for b in bl if re.match(r"^[\w./\\-]+\.\w+$", b["path"]) and self.clean_rel(b["path"])]
        if not targets and len(bl) == 1 and self.current_tab():
            targets = [bl[0]]
        done = []
        for b in targets:
            t = self.apply_code(b["code"], b["path"], focus=False)  # keep the Code tab in front
            if t:
                if self.S["autoSave"]:
                    self.save_tab(t)
                done.append(t.path)
        if done:
            self.chat_note(("\u2713  Saved " if self.S["autoSave"] else "\u2713  Updated ") + ", ".join(done) +
                           ("" if self.S["autoSave"] else "  \u2014 press Ctrl+S to save"), GOOD, body)

    # ---- chat send / stream
    def send(self):
        if self.busy:
            return self.stop_reply()
        text = self.get_input()
        if not text and not self.attachments:
            return
        self.inp.delete("1.0", "end")
        if self.root.focus_get() is not self.inp:
            self._placeholder(True)
        if not self.ready:
            self.pending = text
            self.add_user_msg(text, [a["name"] for a in self.attachments])
            self.wait_note = self.chat_note("I'm still waking up \u2014 I'll answer as soon as I'm ready.", MUTED)
            return
        self._send(text, echo=True)

    def extras(self, text, path=""):
        """Style preset, custom instructions and training examples (shared by the app and the VS Code bridge)."""
        out, used = "", []
        st = self.S.get("style", "none")
        if st in STYLES:
            out += ("\nDesign style: whenever you build a user interface (web page, app screen, component), use this look: "
                    + STYLES[st][3])
        if self.S["custom"].strip():
            out += "\nUser's standing instructions: " + self.S["custom"].strip()
        ex_txt = ""
        if self.S["useTrain"] and self.library.chunks:
            lang = LANG_INFO.get(os.path.splitext(path)[1].lower(), (None, None))[1] if path else None
            m = self.engine.model
            big = bool(m) and os.path.exists(m) and os.path.getsize(m) > 4e9   # big models read prompts slowly on CPU
            # small models lean much more on examples (more CSS + templates); big models need fewer and read slowly
            k, budget = (2, 3000) if big else (4, 4500 if self.total_gb <= 5 else 6500)
            ex = self.library.search(text + " " + path, lang=lang, k=k, budget=budget,
                                     langs=wanted_langs(text, path) or None, min_score=9.0)
            if ex:
                ex_txt = ("Examples from my own code that you were trained on. Follow their style, naming, structure "
                          "and APIs where relevant:")
                for it, chunk in ex:
                    ex_txt += f"\n### {it['name']}\n```\n{chunk}\n```"
                    if it["name"] not in used:
                        used.append(it["name"])
        return out, ex_txt, used

    def build_system(self, text):
        """Returns (system prompt, extra context for the user's message, training examples used).
        The system prompt stays the same between messages so the engine can reuse its cached work;
        things that change (examples, the open file) ride along with the message instead."""
        sysmsg = ASK_SYSTEM if self.S["mode"] == "ask" else EDIT_SYSTEM
        t = self.current_tab()
        wants_style = bool(STYLE_REQ.search(text))
        q = text
        if wants_style:  # vague style requests ("now style it") still find good CSS examples
            st = self.S.get("style", "none")
            q += " css style hero card list button hover " + (STYLES[st][0] if st in STYLES else "modern")
        sys_part, ex_txt, used = self.extras(q, t.path if t else "")
        sysmsg += sys_part
        if self.workspace:
            sysmsg += "\nThe user's open folder: " + self.workspace + "."
        ctx = []
        if self.see_var.get() and t:
            ctx.append(f"My currently open file ({t.path}):\n```\n{t.content()[:14000]}\n```")
        elif not (self.workspace and self.S["mode"] == "edit"):
            wf = self.snippets.working()
            if wf is not None:
                ctx.append("The file we are working on in this chat (current version). If I ask for any change to it "
                           "(styling, CSS, colours, layout, new parts), edit THIS file and reply with the COMPLETE updated file "
                           f"in one ```{wf.lang or 'html'} block, then explain the changes:\n```{wf.lang or 'html'}\n{wf.code[:14000]}\n```")
        if wants_style:
            ctx.append(STYLE_GUIDE)
        if ex_txt:
            ctx.append(ex_txt)
        return sysmsg, "\n\n".join(ctx), used

    def restyle_target(self, text):
        """Small models + a request to style the current page -> (path, html) to restyle, else None."""
        if restyle is None or self.attachments or not self.is_small_model() or not STYLE_REQ.search(text):
            return None
        if re.search(r"\b(make|create|build|write|generate|code)\s+(me\s+)?(a|an|another|new)\b", text, re.I):
            return None  # asking for a new thing, not restyling this one
        t = self.current_tab()
        if self.S["mode"] == "edit" and self.workspace and t and t.path.lower().endswith((".html", ".htm")):
            return t.path, t.content()
        wf = self.snippets.working("html")
        if wf is not None and wf.lang in ("html", "htm"):
            return (wf.path or "index.html"), wf.code
        return None

    def quick_restyle(self, text, echo, path, html):
        """Profound styles the page itself (reliable on small models); the reply explains what changed."""
        st = self.S.get("style", "none")
        style_key, color = restyle.pick(text, html, st if st in STYLES else None)
        new = restyle.apply(html, style_key, color)
        name, col = restyle.describe(style_key, color)
        self.last_question = text
        self.history.append({"role": "user", "content": text})
        if echo:
            self.add_user_msg(text)
        if self.chat_id is None:
            self.chat_id, self.chat_created = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], time.time()
        row = self.chat_row()
        body = self.cur_body = self.ai_header(row)
        self.segs, self.code_opened, self.used_examples = {}, False, []
        fname = os.path.basename(path) or "index.html"
        card = self.snippets.reuse_live("html", path, (text[:48] + "...") if len(text) > 48 else text)
        self.snippets.live_append(card, new)
        self.snippets.live_finish(card, self.S["mode"])
        self.snippets.focus_card(card)
        expl = (f"Styled your page in the **{name}** look with **{col}** as the main colour:\n"
                "- One `<style>` block at the top of the page with a full stylesheet; your HTML and text are unchanged\n"
                "- Header as a hero, sections as cards, lists as hover cards, plus buttons, links, forms, tables and a footer\n"
                "- Colour variables in `:root` (easy to tweak) and a phone-size layout\n"
                "- Want another look? Say \"make it glass\", \"neon\", \"pastel\", \"luxury\" or \"retro\", or add a colour, like \"make it blue\"")
        self.md_text(body, expl)
        chip = Card(body, fill=PANEL2, radius=12, padx=12, pady=8)
        chip.pack(fill="x", pady=5)
        tk.Label(chip.inner, text=f"</>   HTML page  \u00B7  {new.count(chr(10)) + 1} lines", bg=PANEL2, fg=FG, font=UI_SM).pack(side="left")
        RoundButton(chip.inner, "View code", lambda: self.snippets.focus_card(card), kind="accent", font=UI_XS, icon="arrow",
                    icon_size=11, padx=10, pady=3, radius=8, bg=PANEL2).pack(side="right")
        RoundButton(chip.inner, "Preview", lambda: self.show_preview(snippet=new), kind="code", font=UI_XS, icon="eye",
                    icon_size=11, padx=9, pady=3, radius=8, bg=PANEL2).pack(side="right", padx=4)
        self.chat_sf.wheel_tree(row)
        if self.S["mode"] == "edit" and self.workspace:
            t = self.apply_code(new, path, focus=False)
            if t and self.S["autoSave"]:
                self.save_tab(t)
            self.show_preview(page=path, focus=False)
        else:
            self.show_preview(snippet=new, focus=False)
        self.stream = expl + "\n\n```html:" + fname + "\n" + new + "\n```"
        self.history.append({"role": "assistant", "content": self.stream, "mode": self.S["mode"]})
        self.save_chat()
        self.refresh_tabs()
        self.root.after(80, self.show_latest)
        self.selftest_hook("done")

    def _send(self, text, echo):
        if getattr(self, "wait_note", None) is not None and self.wait_note.winfo_exists():
            self.wait_note.destroy()
        self.wait_note = None
        rt = self.restyle_target(text)
        if rt:
            return self.quick_restyle(text, echo, *rt)
        sysmsg, user_ctx, self.used_examples = self.build_system(text)
        qb, self.qb_context = getattr(self, "qb_context", None), None
        if qb:  # Quick build: the template replaces the usual examples (saves room for the full page)
            user_ctx, self.used_examples = qb, []
        atts, self.attachments = self.attachments, []
        self.refresh_attach_row()
        att_note, images, att_names = self.prepare_attachments(atts) if atts else ("", [], [])
        if att_names and not text:
            text = "Here are my files."
        self.last_question = text
        hist_text = text + (f"\n[Attached: {', '.join(att_names)}]" if att_names else "")
        self.history.append({"role": "user", "content": hist_text, "attachments": att_names})
        if echo:
            self.add_user_msg(text, att_names, [a["path"] for a in atts])
        if any(a["kind"] == "image" for a in atts) and not self.engine.vision:
            self.chat_note("This model can't see images. Pick Gemma 4 12B in the model menu to let the AI look at them.", MUTED)
        row = self.chat_row()
        self.cur_body = self.ai_header(row)
        self.think_lbl = tk.Label(self.cur_body, text="\u25CF \u25CB \u25CB", bg=PANEL, fg=MUTED, font=(SANS, 11))
        self.think_prefix = "Thinking deeply  " if self.S.get("deepThink") else ""
        self.think_lbl.pack(anchor="w")
        self.chat_sf.wheel_tree(row)
        self.chat_sf.bottom()
        self.stream_t = None
        self.segs, self.code_opened = {}, False
        self.busy, self.stop_flag, self.stream, self.thinking = True, False, "", True
        self.send_btn.set_text("", icon="stop")
        self.animate_think(0)
        self.talk_avatar = self.last_avatar
        self.animate_talk(0)
        if self.chat_id is None:
            self.chat_id, self.chat_created = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], time.time()
        msgs = [{"role": "system", "content": sysmsg}] + [{"role": m["role"], "content": m["content"]} for m in self.history[-self.S["mem"]:]]
        extra = "\n\n---\n".join(x for x in (att_note, user_ctx) if x)
        content = hist_text + ("\n\n---\n" + extra if extra else "")  # context for this message only (not stored)
        if images:  # the model can see these
            content = [{"type": "text", "text": content}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
        msgs[-1] = {"role": "user", "content": content}
        self.gen = getattr(self, "gen", 0) + 1
        threading.Thread(target=self.chat_worker, args=(msgs, self.gen), daemon=True).start()

    @staticmethod
    def find_loop(text):
        """Length of a chunk repeated 6+ times in a row at the end of text (0 = no loop)."""
        tail = text[-2400:]
        for p in range(8, 400):
            if len(tail) < p * 6:
                break
            chunk = tail[-p:]
            if chunk.strip() and tail[-p * 6:] == chunk * 6:
                return p
        return 0

    def cut_loop(self):
        """If the AI got stuck repeating itself, hang up, keep one copy of the repeated part and finish the reply."""
        p = self.find_loop(self.stream)
        if not p:
            return False
        s = self.stream
        while s.endswith(s[-p:] * 2):
            s = s[:-p]
        self.stream = s
        r = getattr(self, "_resp", None)
        if r is not None:
            try:
                sock = getattr(getattr(getattr(r, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    sock.shutdown(socket.SHUT_RDWR)
                r.close()
            except Exception:
                pass
        self.gen += 1
        self.looped = True
        self.finish_reply("done")
        return True

    def stop_reply(self):
        """Stop button: hang up on the engine right away and finish the message with what we have."""
        if not self.busy:
            return
        self.stop_flag = True
        r = getattr(self, "_resp", None)
        if r is not None:
            try:  # shutting the socket wakes the reader thread immediately and makes the engine stop generating
                sock = getattr(getattr(getattr(r, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    sock.shutdown(socket.SHUT_RDWR)
                r.close()
            except Exception:
                pass
        self.gen += 1  # ignore anything still in flight from the old request
        self.finish_reply("stopped")

    def animate_think(self, i):
        if not self.thinking or not self.think_lbl.winfo_exists():
            return
        self.think_lbl.configure(text=getattr(self, "think_prefix", "") + ["\u25CF \u25CB \u25CB", "\u25CB \u25CF \u25CB", "\u25CB \u25CB \u25CF"][i % 3])
        self.root.after(280, lambda: self.animate_think(i + 1))

    def chat_worker(self, msgs, gid):
        body = {"messages": msgs, "stream": True, "temperature": self.S["temp"],
                "chat_template_kwargs": {"enable_thinking": bool(self.S.get("deepThink"))}}
        if self.is_small_model():  # small models: gently discourage repeating themselves
            body.update({"dry_multiplier": 0.3, "dry_base": 1.75, "dry_allowed_length": 40, "dry_penalty_last_n": 2048})
        extra, self.next_max_tokens = getattr(self, "next_max_tokens", None), None
        if extra:
            body["max_tokens"] = extra  # e.g. Quick build needs room for a whole page
        elif self.S["maxTok"] > 0:
            body["max_tokens"] = self.S["maxTok"]
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{self.engine.port}/v1/chat/completions",
                                         data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=900) as r:
                self._resp = r
                for raw in r:
                    if self.stop_flag or gid != self.gen:
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if d == "[DONE]":
                        break
                    tok = json.loads(d)["choices"][0].get("delta", {}).get("content")
                    if tok:
                        self.q.put(("tok", gid, tok))
            self.q.put(("done", gid))
        except Exception as e:
            self.q.put(("err", gid, str(e)))
        finally:
            self._resp = None

    def route_stream(self, final=False):
        """Split what the AI has typed so far: explanation text goes to the chat, code goes to live cards in the Code tab."""
        body = self.cur_body
        if body is None or not body.winfo_exists():
            return []
        parts = self.stream.split("```")
        touched = []
        for idx, p in enumerate(parts):
            last = idx == len(parts) - 1
            seg = self.segs.get(idx)
            if idx % 2 == 0:  # explanation text
                txt = p.rstrip("`") if (last and not final) else p
                if seg is None:
                    if not txt.strip():
                        continue
                    w = auto_text(body, bg=PANEL)
                    w.pack(fill="x")
                    self.chat_sf.wheel(w)
                    lead = len(txt) - len(txt.lstrip("\n"))
                    seg = self.segs[idx] = types.SimpleNamespace(kind="text", widget=w, shown=lead, text="")
                new = txt[seg.shown:]
                if new:
                    seg.widget.configure(state="normal")
                    seg.widget.insert("end", new)
                    seg.widget.configure(state="disabled")
                    seg.shown = len(txt)
                    touched.append(seg.widget)
                seg.text = txt
            else:  # code block
                nl = p.find("\n")
                if nl == -1 and last and not final:
                    continue  # still typing the ```language line
                info = p[:nl] if nl > -1 else p
                code = p[nl + 1:] if nl > -1 else ""
                if last and not final:
                    code = code.rstrip("`")
                if seg is None:
                    lang, path = self.parse_fence(info)
                    heading = (self.last_question[:48] + "...") if len(self.last_question) > 48 else self.last_question
                    card = self.snippets.reuse_live(lang, path, heading)
                    chip = Card(body, fill=PANEL2, radius=12, padx=12, pady=8)
                    chip.pack(fill="x", pady=5)
                    lbl = tk.Label(chip.inner, text=f"</>   Writing {lang_label(lang, path)} code in the Code tab...", bg=PANEL2, fg=FG, font=UI_SM)
                    lbl.pack(side="left")
                    RoundButton(chip.inner, "View code", lambda c=card: self.snippets.focus_card(c), kind="accent", font=UI_XS,
                                icon="arrow", icon_size=11, padx=10, pady=3, radius=8, bg=PANEL2).pack(side="right")
                    self.chat_sf.wheel_tree(chip)
                    seg = self.segs[idx] = types.SimpleNamespace(kind="code", card=card, chip=chip, label=lbl, shown=0, lang=lang, path=path)
                    if not self.code_opened:  # first code of this reply: bring the Code tab to the front
                        self.code_opened = True
                        self.snippets.focus_card(card)
                new = code[seg.shown:]
                if new:
                    self.snippets.live_append(seg.card, new)
                    seg.card.text.fit()
                    seg.shown = len(code)
                    touched.append(seg.card.text)
                if (not last or final) and not seg.card.done:
                    seg.card.code = code
                    self.snippets.live_finish(seg.card, self.S["mode"])
                    n = seg.card.code.count("\n") + 1
                    ll = lang_label(seg.lang, seg.path)
                    seg.label.configure(text=f"</>   {ll + ' code' if ll != 'Code' else 'Code'}  \u00B7  {n} line{'s' if n != 1 else ''}")
                    RoundButton(seg.chip.inner, "Copy", lambda c=seg.card.code: self.copy(c), kind="code", font=UI_XS, padx=9, pady=3,
                                radius=8, icon="copy", icon_size=11, bg=PANEL2).pack(side="right", padx=4)
        return touched

    def follow_reply(self):
        """While the AI types: follow the reply, but stop once your question reaches the top of the chat."""
        sf = self.chat_sf
        row = getattr(self, "last_user_row", None)
        sf.update_idletasks()
        ih, ch = sf.inner.winfo_height(), sf.canvas.winfo_height()
        if ih <= ch:
            return
        if row is not None and row.winfo_exists() and ih - max(0, row.winfo_y() - 8) > ch:
            sf.stick = False
            sf.canvas.yview_moveto(max(0, row.winfo_y() - 8) / ih)
        else:
            sf.canvas.yview_moveto(1.0)

    def show_latest(self):
        """Show the start of the latest exchange (your message + the reply), not just the very bottom."""
        sf = self.chat_sf
        row = getattr(self, "last_user_row", None)
        sf.update_idletasks()
        ih, ch = sf.inner.winfo_height(), sf.canvas.winfo_height()
        if row is None or not row.winfo_exists() or ih <= ch:
            return sf.bottom()
        start = max(0, row.winfo_y() - 8)
        sf.stick = False
        if ih - start <= ch:
            sf.canvas.yview_moveto(1.0)
        else:
            sf.canvas.yview_moveto(start / ih)

    def finish_reply(self, kind, err=""):
        """End of a reply: 'done', 'err', or 'stopped' (Stop button)."""
        self.thinking = False
        body = self.cur_body
        if body is not None and body.winfo_exists():
            if kind == "err" or (kind == "stopped" and not self.stream.strip()):
                for w in body.winfo_children():
                    w.destroy()
                self.chat_note("Stopped." if kind == "stopped" else "Something went wrong: " + err,
                               MUTED if kind == "stopped" else BAD, body)
                if self.history and self.history[-1]["role"] == "user":
                    self.history.pop()
            else:
                self.stream_t = None
                if getattr(self, "think_lbl", None) is not None and self.think_lbl.winfo_exists():
                    self.think_lbl.destroy()
                self.route_stream(final=True)
                for seg in list(self.segs.values()):  # explanation text: swap plain streamed text for formatted text
                    if seg.kind == "text" and seg.widget.winfo_exists():
                        if seg.text.strip():
                            self.md_text(body, seg.text, before=seg.widget)
                        seg.widget.destroy()
                if not self.segs:
                    self.md_text(body, "(no reply)")
                self.chat_sf.wheel_tree(body)
                if getattr(self, "looped", False):
                    self.looped = False
                    self.chat_note("The AI started repeating itself, so I stopped it and removed the repeats. "
                                   "The code may be unfinished: ask me to continue, or try Quick build.", WARN, body)
                cards = [seg.card for seg in self.segs.values() if seg.kind == "code"]
                html = [c for c in cards if c.lang in ("html", "htm")]
                if kind == "done" and html and (self.S["mode"] == "ask" or not self.workspace):
                    self.show_preview(snippet=html[-1].code, focus=False)  # the Preview tab appears; Code stays in front
                self.history.append({"role": "assistant", "content": self.stream, "mode": self.S["mode"]})
                self.save_chat()
                self.refresh_tabs()
                if kind == "stopped":
                    self.chat_note("■  Stopped", MUTED, body)
                elif self.used_examples:
                    self.chat_note("✦  Learned from your examples: " + ", ".join(self.used_examples[:4]), MUTED, body)
                if kind == "done" and self.S["mode"] == "edit" and self.S["autoApply"] and self.workspace:
                    self.auto_apply(self.stream, body)  # never apply a half-finished (stopped) reply
                    page = next((t.path for t in self.tabs if isinstance(t, EditorTab) and t.path.lower().endswith((".html", ".htm"))), None)
                    if page and any(b["lang"] in ("html", "htm", "css", "js", "javascript") for b in self.extract_blocks(self.stream)):
                        self.show_preview(page=page, focus=False)  # the Preview tab is ready; Code stays in front
            self.root.after(80, self.show_latest)
        self.busy = False
        self.send_btn.set_text("", icon="send")
        self.selftest_hook(kind)

    def pump(self):
        got_tok = False
        try:
            while True:
                kind, *a = self.q.get_nowait()
                if kind == "ready":
                    if a[0] != self.boot_id:
                        continue
                    self.ready = a[1]
                    self.set_pill("ready" if a[1] else "error")
                    if not a[1]:
                        self.chat_note("The AI couldn't start. Try a smaller model or raise RAM Usage in Settings.", BAD)
                    elif self.pending:
                        p, self.pending = self.pending, None
                        self._send(p, echo=False)
                elif kind == "tok":
                    gid, a = a[0], a[1:]
                    if gid != self.gen or self.cur_body is None or not self.cur_body.winfo_exists():
                        continue
                    if self.thinking:
                        self.thinking = False
                        self.think_lbl.destroy()
                    self.stream += a[0]
                    got_tok = True
                elif kind in ("done", "err"):
                    if a[0] != self.gen or not self.busy:
                        continue  # a reply that was already stopped
                    self.finish_reply(kind, a[1] if kind == "err" else "")
                elif kind == "copy":
                    self.say(f"Copying model... {a[0]}%", 60000)
                elif kind == "copied":
                    self.say(f"Added {pretty_model(a[0])}")
                    self.refresh_models()
                    self.reopen_settings()
                elif kind == "copyerr":
                    self.say("Couldn't copy the model: " + a[0])
                elif kind == "drop":
                    self.on_drop(a[0])
                elif kind == "qb":
                    if a[0] == self.gen and self.busy:
                        self.quick_build_finish(a[1])
                elif kind == "pverr":
                    self.preview_tab.update_errors()
                elif kind == "bridge":
                    self.say("VS Code is asking Profound (" + a[0] + ")...", 3000)
                elif kind == "vsix":
                    name, ok, out = a
                    if ok:
                        messagebox.showinfo("Profound", f"Installed in {name}! Restart {name}, then look for the Profound icon in the sidebar.\n\nTip: select code and right-click for Explain, Fix or Edit.")
                    else:
                        messagebox.showerror("Profound", f"Couldn't install into {name}.\n\n{out}")
        except queue.Empty:
            pass
        if got_tok and self.busy and self.cut_loop():
            got_tok = False  # a repeating loop was cut off and the reply finished
        if got_tok and self.busy:
            for w in self.route_stream():
                w.fit()
            if self.code_opened and self.snippets.cards:
                self.snippets.sf.update_idletasks()
                self.snippets.sf.canvas.yview_moveto(1.0)  # follow the code as it is written
            self.follow_reply()
        self.root.after(30, self.pump)

    # ---- Train window
    def open_train(self):
        if self.train_win and self.train_win.winfo_exists():
            self.train_win.lift()
            return
        w = self.train_win = tk.Toplevel(self.root)
        w.title("Train Profound")
        w.configure(bg=PANEL)
        w.geometry(f"700x720+{self.root.winfo_x() + 160}+{self.root.winfo_y() + 50}")
        w.transient(self.root)
        style_window(w)
        top = tk.Frame(w, bg=PANEL)
        top.pack(fill="x", padx=24, pady=(20, 4))
        tk.Label(top, text="Train Profound", bg=PANEL, fg=FG, font=(SANS_SEMI, 16)).pack(anchor="w")
        tk.Label(top, text="Feed it your own code: HTML, Python, Rust, anything. Profound keeps it in a private library on this PC "
                           "and learns from it: every time you chat, it looks up the most relevant pieces and follows your style, "
                           "patterns and APIs.", bg=PANEL, fg=MUTED, font=UI_SM, wraplength=560, justify="left").pack(anchor="w", pady=(6, 0))
        btns = tk.Frame(w, bg=PANEL)
        btns.pack(fill="x", padx=24, pady=14)
        RoundButton(btns, "Add files", self.train_add_files, icon="plus", kind="accent", font=UI_B, padx=16, pady=8, radius=11).pack(side="left")
        RoundButton(btns, "Add folder", self.train_add_folder, icon="folder", kind="soft", font=UI_B, padx=16, pady=8, radius=11).pack(side="left", padx=8)
        RoundButton(btns, "Paste code", self.train_paste, icon="code", kind="soft", font=UI_B, padx=16, pady=8, radius=11).pack(side="left")
        RoundButton(btns, "Starter pack", self.train_starter, icon="spark", kind="soft", font=UI_B, padx=16, pady=8, radius=11).pack(side="left", padx=8)
        opt = tk.Frame(w, bg=PANEL)
        opt.pack(fill="x", padx=24)
        self.use_train_var = tk.BooleanVar(value=self.S["useTrain"])
        Toggle(opt, self.use_train_var, lambda: (self.S.update(useTrain=self.use_train_var.get()), self.save_settings())).pack(side="left")
        tk.Label(opt, text="Use my training library in chats", bg=PANEL, fg=FG, font=UI).pack(side="left", padx=8)
        self.train_stats = tk.Label(opt, text="", bg=PANEL, fg=MUTED, font=UI_SM)
        self.train_stats.pack(side="right")
        self.train_sf = ScrollFrame(w, PANEL)
        self.train_sf.pack(fill="both", expand=True, padx=(18, 4), pady=12)
        self.refresh_train()

    def refresh_train(self):
        if not (self.train_win and self.train_win.winfo_exists()):
            return
        for c in self.train_sf.inner.winfo_children():
            c.destroy()
        items = self.library.items
        kb = sum(i["chars"] for i in items) / 1024
        self.train_stats.configure(text=f"{len(items)} example{'s' if len(items) != 1 else ''}  \u00B7  {kb:,.0f} KB")
        if not items:
            tk.Label(self.train_sf.inner, text="Nothing here yet. Add some of your best code to teach Profound your style.",
                     bg=PANEL, fg=DIM, font=UI).pack(pady=40)
        for it in reversed(items):
            card = Card(self.train_sf.inner, fill=CARD, radius=12, padx=12, pady=8)
            card.pack(fill="x", padx=(0, 10), pady=4)
            row = card.inner
            var = tk.BooleanVar(value=it.get("enabled", True))
            Toggle(row, var, lambda i=it, v=var: (self.library.set_enabled(i["id"], v.get()))).pack(side="left", padx=(0, 10))
            txt = tk.Frame(row, bg=CARD)
            txt.pack(side="left", fill="x", expand=True)
            tk.Label(txt, text=it["name"], bg=CARD, fg=FG, font=UI_B, anchor="w").pack(fill="x")
            tk.Label(txt, text=f"{it['lang']}  \u00B7  {it['chars'] / 1024:,.1f} KB  \u00B7  added {it['added']}", bg=CARD,
                     fg=MUTED, font=UI_XS, anchor="w").pack(fill="x")
            RoundButton(row, "", lambda i=it: (self.library.remove(i["id"]), self.refresh_train()), kind="ghost", icon="trash",
                        font=UI_XS, padx=10, pady=4, radius=8, bg=CARD).pack(side="right")
        self.train_sf.wheel_tree(self.train_sf.inner)

    def train_add_path(self, p, root=None):
        ext = os.path.splitext(p)[1].lower()
        if ext not in LANG_INFO or os.path.getsize(p) > 1_000_000:
            return False
        try:
            with open(p, "rb") as f:
                raw = f.read()
            if b"\0" in raw[:4096]:
                return False
            text = raw.decode("utf-8", "replace")
        except OSError:
            return False
        if not text.strip():
            return False
        name = os.path.relpath(p, root).replace("\\", "/") if root else os.path.basename(p)
        self.library.add(name, text, LANG_INFO[ext][1], p)
        return True

    def train_add_files(self):
        exts = " ".join("*" + e for e in LANG_INFO)
        files = filedialog.askopenfilenames(parent=self.train_win, title="Pick code files to learn from",
                                            filetypes=[("Code files", exts), ("All files", "*.*")])
        n = sum(1 for f in files if self.train_add_path(f))
        self.library.reindex()
        self.refresh_train()
        if files:
            self.say(f"Learned from {n} file{'s' if n != 1 else ''}")

    def train_add_folder(self):
        d = filedialog.askdirectory(parent=self.train_win, title="Pick a folder of code to learn from")
        if not d:
            return
        n = 0
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x not in SKIP and not x.startswith(".")]
            for f in files:
                if n >= 400:
                    break
                if self.train_add_path(os.path.join(root, f), d):
                    n += 1
        self.library.reindex()
        self.refresh_train()
        self.say(f"Learned from {n} file{'s' if n != 1 else ''}")

    def train_starter(self):
        n = self.library.import_starter()
        self.refresh_train()
        self.say(f"Added {n} example page{'s' if n != 1 else ''} from the starter pack" if n else "The starter pack is already in your library")

    def train_paste(self):
        w = tk.Toplevel(self.train_win)
        w.title("Paste code")
        w.configure(bg=PANEL)
        w.geometry("560x480")
        w.transient(self.train_win)
        style_window(w)
        tk.Label(w, text="Name", bg=PANEL, fg=MUTED, font=UI_SM).pack(anchor="w", padx=20, pady=(16, 2))
        name = tk.Entry(w, bg=PANEL2, fg=FG, insertbackground=FG, relief="flat", font=UI)
        name.pack(fill="x", padx=20, ipady=6)
        name.insert(0, "my snippet.py")
        tk.Label(w, text="Code", bg=PANEL, fg=MUTED, font=UI_SM).pack(anchor="w", padx=20, pady=(12, 2))
        box = tk.Text(w, bg=CODE_BG, fg=FG, insertbackground=FG, relief="flat", font=(MONO, 10), padx=10, pady=8, highlightthickness=0)
        box.pack(fill="both", expand=True, padx=20)

        def add():
            code = box.get("1.0", "end").strip()
            if not code:
                return
            nm = name.get().strip() or "snippet"
            self.library.add(nm, code, LANG_INFO.get(os.path.splitext(nm)[1].lower(), (None, "Code"))[1], "pasted")
            self.library.reindex()
            self.refresh_train()
            w.destroy()
            self.say("Learned from " + nm)
        RoundButton(w, "Teach Profound", add, kind="accent", font=UI_B, padx=18, pady=8, radius=11, icon="spark").pack(anchor="e", padx=20, pady=14)

    # ---- VS Code / VSCodium
    def install_vsix(self, kind):
        cli = find_editor_cli(kind)
        name = "VS Code" if kind == "code" else "VSCodium"
        if not cli:
            return self.say(f"{name} isn't installed on this PC")
        self.say(f"Installing Profound into {name}...", 60000)

        def work():
            try:
                p = build_vsix(os.path.join(tempfile.gettempdir(), "profound-1.0.0.vsix"))
                r = subprocess.run([cli, "--install-extension", p, "--force"], capture_output=True, text=True,
                                   timeout=240, **BG_PROC)
                self.q.put(("vsix", name, r.returncode == 0, (r.stdout + r.stderr)[-400:]))
            except Exception as e:
                self.q.put(("vsix", name, False, str(e)))
        threading.Thread(target=work, daemon=True).start()

    def save_vsix(self):
        f = filedialog.asksaveasfilename(parent=self.settings_win, defaultextension=".vsix", initialfile="profound-1.0.0.vsix",
                                         filetypes=[("VS Code extension", "*.vsix")])
        if f:
            build_vsix(f)
            self.say("Saved. In VS Code or VSCodium: Extensions › ⋯ › Install from VSIX...", 6000)

    # ---- settings window
    def reopen_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.destroy()
            self.open_settings()

    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        w = self.settings_win = tk.Toplevel(self.root)
        w.title("Settings")
        w.configure(bg=PANEL)
        w.geometry(f"600x820+{self.root.winfo_x() + 120}+{self.root.winfo_y() + 30}")
        w.transient(self.root)
        style_window(w)
        S = self.S
        sf = ScrollFrame(w, PANEL)
        sf.pack(fill="both", expand=True, padx=(10, 2), pady=(10, 0))
        body = tk.Frame(sf.inner, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=8)
        body.columnconfigure(1, weight=1)
        rowi = [0]

        def section(title):
            tk.Label(body, text=title.upper(), bg=PANEL, fg=THEME["accent"], font=(SANS_SEMI, 8)).grid(
                row=rowi[0], column=0, columnspan=2, sticky="w", pady=(18 if rowi[0] else 0, 6))
            rowi[0] += 1

        def row(label, hint, widget, sticky="ew"):
            lf = tk.Frame(body, bg=PANEL)
            lf.grid(row=rowi[0], column=0, sticky="w", pady=7)
            tk.Label(lf, text=label, bg=PANEL, fg=FG, font=UI).pack(anchor="w")
            if hint:
                tk.Label(lf, text=hint, bg=PANEL, fg=MUTED, font=UI_XS).pack(anchor="w")
            widget.grid(row=rowi[0], column=1, sticky=sticky, padx=(18, 0))
            rowi[0] += 1

        v = {"temp": tk.DoubleVar(value=S["temp"]), "mem": tk.IntVar(value=S["mem"]), "font": tk.IntVar(value=S["font"]),
             "autoApply": tk.BooleanVar(value=S["autoApply"]), "autoSave": tk.BooleanVar(value=S["autoSave"]),
             "lineNums": tk.BooleanVar(value=S["lineNums"]), "autoPreview": tk.BooleanVar(value=S["autoPreview"]),
             "deepThink": tk.BooleanVar(value=S.get("deepThink", False)),
             "maxTok": tk.StringVar(value={256: "Short", 512: "Medium", 1024: "Long", 2048: "Very long", 4096: "Huge"}.get(S["maxTok"], "No limit"))}
        lens = {"Short": 256, "Medium": 512, "Long": 1024, "Very long": 2048, "Huge": 4096, "No limit": -1}
        vals = {}

        def commit(*_):
            S["temp"] = round(float(v["temp"].get()), 1)
            S["mem"] = int(round(float(v["mem"].get()) / 2) * 2)
            S["font"] = int(float(v["font"].get()))
            for k in ("autoApply", "autoSave", "lineNums", "autoPreview", "deepThink"):
                S[k] = v[k].get()
            S["maxTok"] = lens[v["maxTok"].get()]
            S["custom"] = custom.get("1.0", "end").strip()
            vals["temp"].configure(text=("Precise", "Balanced", "Creative")[min(2, int(S["temp"] / 0.5))] + f"  {S['temp']}")
            vals["mem"].configure(text=f"{S['mem']} messages")
            vals["font"].configure(text=f"{S['font']} pt")
            self.save_settings()
            for tab in self.tabs:
                if isinstance(tab, EditorTab):
                    tab.apply_view()

        def scale_row(label, hint, var, lo, hi, key):
            f = tk.Frame(body, bg=PANEL)
            ttk.Scale(f, from_=lo, to=hi, variable=var, command=commit).pack(side="left", fill="x", expand=True)
            vals[key] = tk.Label(f, text="", bg=PANEL, fg=MUTED, font=UI_SM, width=12, anchor="e")
            vals[key].pack(side="right")
            row(label, hint, f)

        def tog(var):
            return Toggle(body, var, commit)

        section("AI")
        rf = tk.Frame(body, bg=PANEL)
        self.sw_ram_lbl = tk.Label(rf, text="", bg=PANEL, fg=THEME["accent"], font=UI_B, width=7, anchor="e")
        self.sw_ram_lbl.pack(side="right")
        sc = ttk.Scale(rf, from_=2, to=self.total_gb, variable=self.ram_var, command=self.on_ram_move)
        sc.pack(side="left", fill="x", expand=True)
        sc.bind("<ButtonRelease-1>", lambda e: self.on_ram_release())
        row("RAM Usage", f"This PC has {self.total_gb} GB", rf)
        self.sw_ram_info = tk.Label(body, text="", bg=PANEL, fg=MUTED, font=UI_XS, anchor="w", justify="left", wraplength=520)
        self.sw_ram_info.grid(row=rowi[0], column=0, columnspan=2, sticky="w")
        rowi[0] += 1
        names = ["Auto (best AI for you)"] + ["{}  \u00B7  {}".format(*model_label(m["name"])) for m in self.models]
        cur = 0 if S["model"] == "auto" else next((i + 1 for i, m in enumerate(self.models) if m["name"] == S["model"]), 0)
        mv = tk.StringVar(value=names[cur])
        cb = ttk.Combobox(body, textvariable=mv, values=names, state="readonly")

        def model_pick(_=None):
            i = names.index(mv.get())
            S["model"] = "auto" if i == 0 else self.models[i - 1]["name"]
            self.save_settings()
            self.on_ram_move()
            self.start_engine()
        cb.bind("<<ComboboxSelected>>", model_pick)
        row("Model", "Auto picks the best AI for your PC", cb)
        mb = tk.Frame(body, bg=PANEL)
        mb.grid(row=rowi[0], column=1, sticky="w", padx=(18, 0), pady=(0, 4))
        rowi[0] += 1
        RoundButton(mb, "Add your model", self.add_model, kind="soft", font=UI_XS, padx=10, pady=4, radius=8, icon="plus", icon_size=11).pack(side="left")
        RoundButton(mb, "Open folder", lambda: open_path(MODELS), kind="soft", font=UI_XS, padx=10, pady=4, radius=8, icon="folder", icon_size=11).pack(side="left", padx=6)

        def remove_sel():
            i = names.index(mv.get())
            if i == 0:
                return self.say("Pick one of your own models to remove")
            self.remove_model(self.models[i - 1]["name"])
        RoundButton(mb, "Remove", remove_sel, kind="soft", font=UI_XS, padx=10, pady=4, radius=8, icon="trash", icon_size=11).pack(side="left")
        scale_row("Creativity", "How adventurous the answers are", v["temp"], 0, 1.5, "temp")
        lc = ttk.Combobox(body, textvariable=v["maxTok"], values=list(lens), state="readonly")
        lc.bind("<<ComboboxSelected>>", commit)
        row("Answer length", "Shorter answers are faster", lc)
        scale_row("Chat memory", "How much of the chat it remembers", v["mem"], 2, 30, "mem")
        row("Deep thinking", "Thinks before answering: smarter on hard problems, much slower", tog(v["deepThink"]), "w")

        section("Editing")
        row("Auto-update files", "In Edit mode, put AI code straight into the file", tog(v["autoApply"]), "w")
        row("Auto-save AI changes", "Save to disk without asking", tog(v["autoSave"]), "w")
        row("Live HTML preview tab", "Show a Preview tab when you open an HTML file", tog(v["autoPreview"]), "w")

        section("VS Code & VSCodium")
        vs = tk.Frame(body, bg=PANEL)
        vs.grid(row=rowi[0], column=0, columnspan=2, sticky="ew")
        rowi[0] += 1
        tk.Label(vs, text="Use Profound inside your editor: a chat sidebar, plus right-click Explain / Fix / Edit on any selection. "
                          "Keep the Profound app open while you code.", bg=PANEL, fg=MUTED, font=UI_XS, wraplength=520,
                 justify="left").pack(anchor="w", pady=(0, 8))
        vb = tk.Frame(vs, bg=PANEL)
        vb.pack(anchor="w")
        for kind, label in (("code", "VS Code"), ("codium", "VSCodium")):
            found = find_editor_cli(kind)
            b = RoundButton(vb, f"Install in {label}", lambda k=kind: self.install_vsix(k), kind="accent" if found else "soft",
                            font=UI_SM, padx=12, pady=6, radius=9, icon="vscode", icon_size=13)
            b.set_enabled(bool(found))
            b.pack(side="left", padx=(0, 8))
        RoundButton(vb, "Save .vsix file", self.save_vsix, kind="soft", font=UI_SM, padx=12, pady=6, radius=9,
                    icon="save", icon_size=12).pack(side="left")
        if not self.bridge.ok:
            tk.Label(vs, text="Note: another Profound window is already serving VS Code.", bg=PANEL, fg=WARN, font=UI_XS).pack(anchor="w", pady=(6, 0))

        section("Look")
        scale_row("Editor text size", "", v["font"], 9, 22, "font")
        row("Line numbers", "", tog(v["lineNums"]), "w")
        sw = tk.Frame(body, bg=PANEL)
        swatches = []

        def set_accent(col):
            S["accent"] = col
            THEME["accent"] = col
            self.save_settings()
            self.apply_accent()
            for cvs, c in swatches:
                cvs.delete("ring")
                if c == col:
                    cvs.create_oval(1, 1, 27, 27, outline=FG, width=2, tags="ring")
        for col in ACCENTS:
            cvs = tk.Canvas(sw, width=28, height=28, bg=PANEL, highlightthickness=0, cursor="hand2")
            cvs.create_oval(5, 5, 23, 23, fill=col, outline=col)
            if col == S["accent"]:
                cvs.create_oval(1, 1, 27, 27, outline=FG, width=2, tags="ring")
            cvs.pack(side="left", padx=2)
            cvs.bind("<Button-1>", lambda e, c=col: set_accent(c))
            swatches.append((cvs, col))
        RoundButton(sw, "Custom", lambda: (lambda c: c and set_accent(c))(colorchooser.askcolor(color=S["accent"], parent=w)[1]),
                    kind="soft", font=UI_XS, padx=9, pady=3, radius=8, icon="palette", icon_size=11).pack(side="left", padx=8)
        row("Accent colour", "", sw, "w")

        section("Your instructions")
        cc = Card(body, fill=PANEL2, radius=12, padx=10, pady=8)
        cc.grid(row=rowi[0], column=0, columnspan=2, sticky="ew")
        rowi[0] += 1
        custom = tk.Text(cc.inner, height=3, bg=PANEL2, fg=FG, insertbackground=FG, borderwidth=0, wrap="word",
                         highlightthickness=0, font=UI_SM, width=10)
        custom.pack(fill="x")
        tk.Label(body, text="Always sent to the AI, e.g. \u201cExplain like I'm a beginner\u201d or \u201cUse Flask\u201d.",
                 bg=PANEL, fg=MUTED, font=UI_XS).grid(row=rowi[0], column=0, columnspan=2, sticky="w", pady=(4, 0))
        custom.insert("1.0", S["custom"])
        custom.bind("<KeyRelease>", commit)

        bt = tk.Frame(w, bg=PANEL)
        bt.pack(fill="x", padx=26, pady=(8, 18))

        def reset():
            keep = {k: S[k] for k in ("ram", "model", "lastFolder", "style")}
            S.clear()
            S.update(DEF)
            S.update(keep)
            THEME["accent"] = S["accent"]
            self.save_settings()
            self.apply_accent()
            for tab in self.tabs:
                if isinstance(tab, EditorTab):
                    tab.apply_view()
            self.reopen_settings()
        RoundButton(bt, "Reset to defaults", reset, kind="ghost", font=UI_SM, icon="refresh", icon_size=12).pack(side="left")
        RoundButton(bt, "Done", lambda: (commit(), w.destroy()), kind="accent", font=UI_B, padx=22, pady=8, radius=11, icon="check").pack(side="right")
        sf.wheel_tree(body)
        commit()
        self.on_ram_move()

    def apply_accent(self):
        self.style_accent()
        RoundButton.repaint_all()
        Toggle.all = [t for t in Toggle.all if t.winfo_exists()]
        for t in Toggle.all:
            t.draw()
        for t in self.tabs:
            if isinstance(t, EditorTab):
                t.text.configure(insertbackground=THEME["accent"])
        self._tab_sig = None
        self.refresh_tabs()
        if self.settings_win and self.settings_win.winfo_exists():
            self.sw_ram_lbl.configure(fg=THEME["accent"])

    def stoptest(self):
        """1) stop while the AI is still reading  2) stop mid-reply  3) a normal message still works afterwards."""
        if not self.ready:
            return self.root.after(500, self.stoptest)
        res, long_q = {}, "Write a very long, detailed essay about the history of programming languages, at least 2000 words."

        def step1():
            self.quick(long_q)
            self.root.after(300, lambda: (res.update(t1=time.time()), self.stop_reply(), self.root.after(150, step1b)))

        def step1b():
            res["phase1_busy_after_stop"] = self.busy
            res["phase1_stop_ms"] = int((time.time() - res["t1"]) * 1000)
            self.root.after(800, step2)

        def step2():
            self.quick(long_q)
            wait_tokens()

        def wait_tokens():
            if len(self.stream) < 40:
                return self.root.after(100, wait_tokens)
            res["t2"] = time.time()
            n_before = len(self.stream)
            self.stop_reply()
            self.root.after(1500, lambda: (res.update(phase2_busy_after_stop=self.busy, phase2_chars_at_stop=n_before,
                                                      phase2_chars_after=len(self.stream)), step3()))

        def step3():
            res["t3"] = time.time()
            self.quick("Reply with just the word: hello")
            wait_done()

        def wait_done():
            if self.busy and time.time() - res["t3"] < 120:
                return self.root.after(200, wait_done)
            res["phase3_reply"] = self.stream[:80]
            res["phase3_seconds"] = round(time.time() - res["t3"], 1)
            for k in ("t1", "t2", "t3"):
                res.pop(k, None)
            with open(self.stoptest_out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)
        step1()

    def qbtest(self, out):
        if not self.ready:
            return self.root.after(500, lambda: self.qbtest(out))
        self.set_mode("ask", save=False)
        t0 = time.time()
        self.quick_build_send("landing", "darksaas", "#16a34a", ["Navbar", "Hero", "Features", "Footer"], "a cosy bakery in Lisbon")

        def wait():
            if self.busy and time.time() - t0 < 900:
                return self.root.after(500, wait)
            cards = self.snippets.cards
            code = cards[-1].code if cards else ""
            low = code.lower()
            chat = "".join(w.get("1.0", "end") for w in self.cur_body.winfo_children() if isinstance(w, tk.Text))
            res = {"model": pretty_model(os.path.basename(self.engine.model or "")), "seconds": round(time.time() - t0),
                   "code_lines": code.count("\n") + 1, "complete_html": "</html>" in low,
                   "style_before_body": 0 <= low.find("<style") < low.find("<body") if "<body" in low else False,
                   "mentions_bakery": "bak" in low or "bread" in low, "uses_green": "#16a34a" in low,
                   "chat_has_code": "```" in chat or "<style" in chat.lower(), "chat_explanation_chars": len(chat.strip()),
                   "preview_tab_ready": self.preview_tab in self.tabs}
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            try:
                with open(out + ".html", "w", encoding="utf-8") as f:
                    f.write(code)
            except OSError:
                pass
            self.on_close(force=True)
        self.root.after(500, wait)

    def readmetest(self, out_dir, t0=None):
        t0 = t0 or time.time()
        if not self.ready and time.time() - t0 < 90:
            return self.root.after(500, lambda: self.readmetest(out_dir, t0))
        self.root.geometry("1440x880+40+30")
        self.set_mode("ask", save=False)
        page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bean There Coffee</title>
</head>
<body>
<nav><a href="#">Home</a><a href="#menu">Menu</a><a href="#visit">Visit</a></nav>
<header>
  <h1>Bean There <span>Coffee</span></h1>
  <p>Small-batch roasts, flaky pastries and a cosy corner to stay a while.</p>
  <button>See the menu</button>
</header>
<main>
  <section id="menu">
    <h2>Today's menu</h2>
    <ul>
      <li>Espresso</li>
      <li>Oat flat white</li>
      <li>Cold brew</li>
      <li>Cardamom bun</li>
    </ul>
  </section>
  <section id="visit">
    <h2>Visit us</h2>
    <p>Open every day from 7am. Free Wi-Fi, comfy chairs and the best window seats in town.</p>
  </section>
</main>
<footer>Made with love and lots of coffee</footer>
</body>
</html>"""
        q1 = "Make a simple web page for my coffee shop"
        self.history.append({"role": "user", "content": q1})
        self.add_user_msg(q1)
        row = self.chat_row()
        body = self.ai_header(row)
        card = self.snippets.add_live("html", "index.html", q1)
        self.snippets.live_append(card, page)
        self.snippets.live_finish(card, "ask")
        self.md_text(body, "Here's a page for **Bean There Coffee**:\n- A header with your name, a short welcome and a button\n"
                           "- A menu section and a visit section\n- A footer, all in one HTML file")
        self.history.append({"role": "assistant", "content": "page\n```html\n" + page + "\n```"})
        self.chat_sf.wheel_tree(row)
        self.quick_restyle("now make it neon", True, "index.html", page)

        def grab(name):
            try:
                from PIL import ImageGrab
                self.root.attributes("-topmost", True)
                self.root.update()
                hwnd = U32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                r = RECT()
                try:
                    ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r))
                except Exception:
                    U32.GetWindowRect(hwnd, ctypes.byref(r))
                ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(out_dir + "-" + name)
            except Exception as e:
                log_error("readme shot: " + repr(e))

        steps = [(2500, lambda: (self.snippets.focus_card(self.snippets.cards[-1]), self.show_latest())),
                 (1500, lambda: grab("code.png")),
                 (300, lambda: self.select_tab(self.preview_tab)),
                 (5000, lambda: grab("preview.png")),
                 (300, lambda: self.on_close(force=True))]

        def run(i=0):
            if i < len(steps):
                ms, fn = steps[i]
                self.root.after(ms, lambda: (fn(), run(i + 1)))
        run()

    def smoketest(self, out):
        """Opens the main window, the Code tab, the Train library and a restyled page, then writes a JSON report."""
        res = {"ok": False, "platform": sys.platform, "frozen": FROZEN, "python": sys.version.split()[0]}
        try:
            self.root.update()
            res["window"] = [self.root.winfo_width(), self.root.winfo_height()]
            self.select_tab(self.snippets)
            card = self.snippets.add_live("html", "index.html", "smoke")
            self.snippets.live_append(card, "<!doctype html><html><head><title>t</title></head><body><h1>Hi</h1></body></html>")
            self.snippets.live_finish(card, "ask")
            res["code_tab"] = self.active is self.snippets
            res["starter_pack"] = len(glob.glob(os.path.join(RES_DIR, "training_pack", "**", "*.html"), recursive=True))
            res["restyle"] = bool(restyle) and "<style>" in restyle.apply(card.code, "glass")
            res["page_builder"] = bool(page_builder) and "</html>" in page_builder.build_page(
                "darksaas", "#16a34a", ["Navbar", "Hero", "Footer"], page_builder.DEFAULT)
            res["preview_server"] = urllib.request.urlopen(self.preview.url() + "__v", timeout=5).status == 200
            res["engine_found"] = os.path.exists(ENGINE)
            res["ok"] = all(res[k] for k in ("code_tab", "restyle", "page_builder", "preview_server")) and res["starter_pack"] > 300
        except Exception as e:
            res["error"] = repr(e)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=1)
        self.on_close(force=True)

    def styletest(self, out):
        if not self.ready:
            return self.root.after(500, lambda: self.styletest(out))
        self.set_mode("edit", save=False)
        res, t0 = {"model": pretty_model(os.path.basename(self.engine.model or ""))}, time.time()
        steps = ["Make a simple HTML page for a coffee shop with a heading, a short paragraph and a list of 3 drinks. No CSS yet.",
                 "now style it"]

        def snap(tag):
            wf = self.snippets.working()
            code = wf.code if wf else ""
            low = code.lower()
            res[tag] = {"seconds": round(time.time() - t0), "live_cards": sum(1 for c in self.snippets.cards if getattr(c, "status", None) is not None),
                        "lines": code.count("\n") + 1, "has_style": "<style" in low, "css_rules": low.count("{"),
                        "style_before_body": "<style" in low and "<body" in low and low.find("<style") < low.find("<body"),
                        "keeps_coffee": "coffee" in low, "preview_ready": self.preview_tab in self.tabs,
                        "toolbar_preview_enabled": self.preview_source() is not None}
            with open(out + "." + tag + ".html", "w", encoding="utf-8") as f:
                f.write(code)

        def run(i=0):
            if self.busy:
                return self.root.after(500, lambda: run(i))
            if i > 0:
                snap(f"after_{i}")
            if i < len(steps) and time.time() - t0 < 1200:
                self.quick(steps[i])
                return self.root.after(1000, lambda: run(i + 1))
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)
        run()

    def codetest(self, out):
        """Ask for a web page in Ask mode; check code streamed into the Code tab and none landed in the chat."""
        if not self.ready:
            return self.root.after(500, lambda: self.codetest(out))
        res = {"code_tab_opened_while_typing": False}
        self.set_mode("ask", save=False)
        self.quick("Make a tiny HTML page with a red rounded button that says Hi.")

        def watch():
            if self.code_opened and not res["code_tab_opened_while_typing"]:
                res["code_tab_opened_while_typing"] = self.busy and self.active is self.snippets
                live = [seg.card for seg in self.segs.values() if seg.kind == "code"]
                res["code_visible_in_code_tab_while_typing"] = bool(live and live[0].code)
            if self.busy:
                return self.root.after(150, watch)
            chat_text = ""
            for w in self.cur_body.winfo_children():
                if isinstance(w, tk.Text):
                    chat_text += w.get("1.0", "end")
            cards = [seg.card for seg in self.segs.values() if seg.kind == "code"]
            res.update({"chat_has_code_fence": "```" in chat_text or "<button" in chat_text.lower(),
                        "chat_explanation_chars": len(chat_text.strip()),
                        "code_cards": len(cards), "first_card_lines": cards[0].code.count("\n") + 1 if cards else 0,
                        "preview_tab_ready": self.preview_tab in self.tabs, "front_tab": getattr(self.active, "title", lambda: None)()})
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)
        self.root.after(300, watch)

    def previewtest(self, out):
        """Open the Preview tab, switch away and back, close and reopen: the page must stay embedded and visible."""
        res = {}
        d = tempfile.mkdtemp(prefix="pf_prev_")
        with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!doctype html><html><head><style>body{background:#2563eb;color:#fff;font:40px sans-serif}</style></head>"
                    "<body><h1>Preview OK</h1></body></html>")
        self.set_workspace(d)
        self.open_file("index.html")

        def state():
            pt = self.preview_tab
            h = pt.hwnd
            ok = bool(WIN and h and U32.IsWindow(h) and U32.GetParent(h) == pt.view.winfo_id())
            return {"embedded": ok, "visible": bool(ok and U32.IsWindowVisible(h)), "front": self.active is pt,
                    "pixel": self.grab_pixel(pt) if ok else None}

        steps = [lambda: self.show_preview(page="index.html"), lambda: res.update(opened=state()),
                 lambda: self.select_tab(self.find_tab("index.html")), lambda: res.update(after_switch_away=state()),
                 lambda: self.select_tab(self.preview_tab), lambda: res.update(after_switch_back=state()),
                 lambda: self.hide_preview(), lambda: self.show_preview(page="index.html"), lambda: res.update(after_close_reopen=state()),
                 lambda: self.select_tab(self.find_tab("index.html")),
                 lambda: self.show_preview(snippet="<!doctype html><html><head><style>body{background:#16a34a}</style></head>"
                                                   "<body><h1>Second</h1></body></html>"),
                 lambda: res.update(second_snippet=state()),
                 lambda: self.select_tab(self.find_tab("index.html")), lambda: self.toolbar_preview(),
                 lambda: res.update(toolbar_button=state())]
        delays = [0, 9000, 300, 800, 300, 1500, 300, 300, 2000, 300, 300, 2500, 300, 300, 2000]

        def run(i=0):
            if i < len(steps):
                steps[i]()
                return self.root.after(delays[i + 1] if i + 1 < len(delays) else 500, lambda: run(i + 1))
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)
        run()

    def grab_pixel(self, pt):
        """Colour in the middle of the embedded page, read off-screen (PrintWindow), as #rrggbb."""
        try:
            g = ctypes.windll.gdi32
            h = pt.hwnd
            r = RECT()
            U32.GetWindowRect(h, ctypes.byref(r))
            w, hh = r.right - r.left, r.bottom - r.top
            U32.GetDC.restype = ctypes.c_void_p
            U32.GetDC.argtypes = [wt.HWND]
            U32.ReleaseDC.argtypes = [wt.HWND, ctypes.c_void_p]
            U32.PrintWindow.argtypes = [wt.HWND, ctypes.c_void_p, ctypes.c_uint]
            for fn in ("CreateCompatibleDC", "CreateCompatibleBitmap", "SelectObject"):
                getattr(g, fn).restype = ctypes.c_void_p
            g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
            g.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            g.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            g.DeleteObject.argtypes = g.DeleteDC.argtypes = [ctypes.c_void_p]
            sdc = U32.GetDC(None)
            mdc = g.CreateCompatibleDC(sdc)
            bmp = g.CreateCompatibleBitmap(sdc, w, hh)
            g.SelectObject(mdc, bmp)
            U32.PrintWindow(h, mdc, 2)
            sx = pt.view.winfo_rootx() + pt.view.winfo_width() // 2
            sy = pt.view.winfo_rooty() + int(pt.view.winfo_height() * 0.7)
            c = g.GetPixel(sdc, sx, sy)  # what is really on screen
            g.DeleteObject(bmp)
            g.DeleteDC(mdc)
            U32.ReleaseDC(None, sdc)
            return "#%02x%02x%02x" % (c & 255, (c >> 8) & 255, (c >> 16) & 255)
        except Exception as e:
            return "err " + str(e)

    def droptest(self, out):
        """Post a real WM_DROPFILES (built like Explorer does) to our window, then check the attachments."""
        files = [os.path.join(RES_DIR, "buddy_idle.png"), os.path.join(RES_DIR, "README_LINUX_MAC.md")
                 if os.path.exists(os.path.join(RES_DIR, "README_LINUX_MAC.md")) else os.path.join(RES_DIR, "logo.png")]
        k = ctypes.windll.kernel32
        k.GlobalAlloc.restype, k.GlobalLock.restype = ctypes.c_void_p, ctypes.c_void_p
        k.GlobalLock.argtypes = k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        names = ("\0".join(files) + "\0\0").encode("utf-16-le")
        header = (20).to_bytes(4, "little") + (0).to_bytes(8, "little") + (0).to_bytes(4, "little") + (1).to_bytes(4, "little")
        h = k.GlobalAlloc(0x0042, len(header) + len(names))  # GHND
        ptr = k.GlobalLock(h)
        ctypes.memmove(ptr, header + names, len(header) + len(names))
        k.GlobalUnlock(h)
        hwnd = U32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        U32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
        U32.PostMessageW(hwnd, 0x0233, h, 0)

        def check():
            res = {"attachments": [a["name"] for a in self.attachments],
                   "kinds": [a["kind"] for a in self.attachments],
                   "image_thumbnail_ok": make_thumb(files[0], 36) is not None}
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)
        self.root.after(1500, check)

    def scrolltest(self, out):
        """Fill a chat with long messages + code, reopen it like a saved chat, and measure where the view lands."""
        global CHATS_DIR
        CHATS_DIR = tempfile.mkdtemp(prefix="pf_chats_")
        long_txt = "\n".join(f"Line {i}: some explanation text that wraps across the chat panel width nicely." for i in range(25))
        code = "\n".join(f"print('row {i}')" for i in range(40))
        msgs = []
        for i in range(4):
            msgs.append({"role": "user", "content": f"Question {i}"})
            msgs.append({"role": "assistant", "content": f"Answer {i}\n{long_txt}\n```python\n{code}\n```\nThe end of answer {i}.", "mode": "edit"})
        with open(os.path.join(CHATS_DIR, "t.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "t", "title": "scroll test", "messages": msgs, "updated": time.time()}, f)
        res = {}

        def measure(tag):
            ch, ih = self.chat_sf.canvas.winfo_height(), self.chat_sf.inner.winfo_height()
            res[tag] = {"empty_px_below_last_message": int(self.chat_sf.canvas.canvasy(ch) - ih),
                        "at_bottom": self.chat_sf.at_bottom(), "content_px": ih}
        self.load_chat("t")
        self.root.after(1500, lambda: (measure("after_open_saved_chat"), self.set_mode("edit", save=False),
                                       self.root.after(800, lambda: (measure("after_switch_to_edit"), finish()))))

        def finish():
            with open(out, "w", encoding="utf-8") as f:
                json.dump(res, f, indent=1)
            self.on_close(force=True)

    def demo_tick(self):
        if not self.ready:
            return self.root.after(500, self.demo_tick)
        self.set_mode("ask", save=False)
        self.quick("Show me a short Rust function that reverses a string")

        def show_code():
            if self.busy:
                return self.root.after(500, show_code)
            if self.snippets.cards:
                self.snippets.focus_card(self.snippets.cards[-1])
        self.root.after(1500, show_code)

    # ---- self test (used to verify builds: Profound.exe --selftest out.json)
    def run_selftest(self):
        self.result = {"ready": False}
        d = tempfile.mkdtemp(prefix="pf_selftest_")
        with open(os.path.join(d, "hello.py"), "w") as f:
            f.write("print('hi')\n")
        self.S.update(autoApply=True, autoSave=True, maxTok=300, ram=4.0, useTrain=False)
        self.ram_var.set(4.0)
        self.set_workspace(d)
        self.open_file("hello.py")
        self.set_mode("edit", save=False)
        self.selftest_dir, self.selftest_stage, self.selftest_t0 = d, 0, time.time()
        self.root.after(1000, self.selftest_tick)

    def selftest_tick(self):
        if self.ready and self.selftest_stage == 0:
            self.result["ready"] = True
            self.selftest_stage = 1
            self.quick("Write hello.py containing a function add(a, b) that returns a + b. Output the full file.")
        elif time.time() - self.selftest_t0 > 600:
            return self.selftest_finish("timeout")
        if self.selftest_stage < 2:
            self.root.after(1000, self.selftest_tick)

    def selftest_hook(self, kind):
        if self.selftest and getattr(self, "selftest_stage", 0) == 1:
            self.selftest_stage = 2
            self.result["reply"] = self.stream[:400]
            self.root.after(500, lambda: self.selftest_finish(kind))

    def selftest_finish(self, kind):
        try:
            with open(os.path.join(self.selftest_dir, "hello.py"), encoding="utf-8") as f:
                self.result["file_on_disk"] = f.read()[:400]
        except Exception as e:
            self.result["file_on_disk"] = f"ERR {e}"
        self.result["kind"] = kind
        with open(self.selftest, "w", encoding="utf-8") as f:
            json.dump(self.result, f, indent=1)
        self.on_close(force=True)

    def on_close(self, force=False):
        if not force and any(t.dirty() for t in self.tabs):
            if not messagebox.askyesno("Profound", "You have unsaved changes. Quit anyway?"):
                return
        self.engine.stop()
        self.preview_tab.close()
        self.root.destroy()
        os._exit(0)


def main():
    import traceback
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:  # own taskbar identity so Windows shows Profound's icon, not Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Profound.CodeAI.1")
    except Exception:
        pass
    selftest = sys.argv[sys.argv.index("--selftest") + 1] if "--selftest" in sys.argv else None
    try:
        root = None
        if not WIN:
            try:  # optional: enables drag & drop on Linux / macOS
                from tkinterdnd2 import TkinterDnD
                root = TkinterDnD.Tk()
            except Exception:
                root = None
        root = root or tk.Tk()
        try:
            if WIN:
                root.iconbitmap(default=os.path.join(RES_DIR, "icon.ico"))
            else:
                root._icon = tk.PhotoImage(file=os.path.join(RES_DIR, "logo.png"))
                root.iconphoto(True, root._icon)
        except tk.TclError:
            pass
        root.report_callback_exception = lambda *exc: log_error("".join(traceback.format_exception(*exc)))
        App(root, selftest)
        root.mainloop()
    except Exception:
        log_error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
