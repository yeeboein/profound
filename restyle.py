"""Restyle an existing HTML page with a complete, hand-tuned stylesheet (used for small AI models, which struggle to
write good CSS from scratch). Styles every common element, so it works on any page without changing its HTML.
The CSS goes in ONE <style> block at the top of <head>; the HTML stays below, untouched."""
import re

import make_css_pack as P

COLOR_WORDS = {"red": "#ef4444", "blue": "#2563eb", "green": "#16a34a", "purple": "#7c3aed", "violet": "#7c3aed",
               "pink": "#db2777", "orange": "#f97316", "yellow": "#eab308", "teal": "#0d9488", "cyan": "#0891b2",
               "black": "#111827", "gold": "#c99a2e", "brown": "#92400e", "indigo": "#4f46e5", "lime": "#65a30d"}
STYLE_WORDS = [("glass", r"glass\w*|frosted|blur"), ("neon", r"neon|cyber\w*|synthwave|glow\w*"),
               ("pastel", r"pastel|cute|soft|playful"), ("material", r"material|google"), ("brutal", r"brutal\w*|bold|raw"),
               ("retro", r"retro|vintage|80s|90s|pixel"), ("luxury", r"luxur\w*|elegant|premium|classy|fancy"),
               ("earthy", r"earth\w*|natur\w*|organic|warm|cosy|cozy|rustic"), ("minimal", r"minimal\w*|clean|simple|plain"),
               ("darksaas", r"dark|saas|tech\w*|sleek|modern")]
TOPIC_STYLES = [("earthy", r"coffee|cafe|bakery|bread|tea|garden|farm|food|restaurant|kitchen|plant"),
                ("darksaas", r"\bapp\b|software|startup|saas|dashboard|developer|\bai\b|tech"),
                ("pastel", r"kids|baby|candy|flower|cake|pet|art\b|craft"), ("luxury", r"hotel|jewel|wedding|wine|spa|fashion"),
                ("neon", r"game|gaming|music|club|party|esports"), ("minimal", r"portfolio|blog|resume|cv\b|photograph")]


def on_color(color):
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 165 else "#ffffff"


def pick(request, html, preset=None):
    """Choose (style key, colour or None) from the request words, then the user's Style preset, then the page topic."""
    req = request.lower()
    style = next((k for k, pat in STYLE_WORDS if re.search(r"\b(" + pat + r")\b", req)), None)
    if style is None and preset in P.S:
        style = preset
    if style is None:
        text = re.sub(r"<[^>]+>", " ", html).lower()
        style = next((k for k, pat in TOPIC_STYLES if re.search(pat, text)), "darksaas")
    color = next((v for k, v in COLOR_WORDS.items() if re.search(r"\b" + k + r"\b", req)), None)
    m = re.search(r"#[0-9a-fA-F]{6}\b", request)
    if m:
        color = m.group(0)
    return style, color


def stylesheet(style_key, color=None):
    t = dict(P.S[style_key])
    if color:
        t["primary"], t["on"] = color, on_color(color)
    return f"""/* Style: {t['name']} (applied by Profound) */
:root {{
  --bg: {t['bg']}; --surface: {t['surface']}; --text: {t['text']}; --muted: {t['muted']};
  --primary: {t['primary']}; --on-primary: {t['on']}; --accent: {t['accent']}; --border: {t['border']};
  --radius: {t['r']}; --shadow: {t['shadow']};
}}
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0 auto; max-width: 1000px; padding: 32px 24px 64px;
  font-family: {t['font']}; font-size: 16px; line-height: 1.65;
  color: var(--text); background: var(--bg); {t['fx']}
  -webkit-font-smoothing: antialiased;
}}
::selection {{ background: var(--primary); color: var(--on-primary); }}
h1, h2, h3, h4 {{ font-family: {t['head']}; line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 .5em; }}
h1 {{ font-size: clamp(2.1rem, 5vw, 3.3rem); font-weight: 800; }}
h1 span, h1 em, h1 strong {{ color: var(--primary); font-style: normal; }}
h2 {{ font-size: clamp(1.45rem, 3vw, 1.9rem); margin-top: .2em; }}
h2::after {{ content: ""; display: block; width: 48px; height: 4px; margin-top: 10px; border-radius: 4px; background: var(--primary); }}
header h2::after, footer h2::after {{ display: none; }}
h3 {{ font-size: 1.2rem; }}
p {{ margin: 0 0 1em; }}
a {{ color: var(--primary); text-decoration: none; font-weight: 600; transition: opacity .2s ease; }}
a:hover {{ opacity: .8; text-decoration: underline; }}
header {{
  text-align: center; padding: 64px 28px; margin-bottom: 32px;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow);
}}
header p {{ color: var(--muted); font-size: 1.15rem; max-width: 60ch; margin: 0 auto 1em; }}
nav {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 6px 22px; margin: 0 0 24px; }}
nav ul {{ display: flex; flex-wrap: wrap; gap: 6px 22px; list-style: none; padding: 0; margin: 0; }}
nav li {{ background: none; border: 0; padding: 0; box-shadow: none; }}
nav li:hover {{ transform: none; }}
nav a {{ color: var(--text); font-weight: 600; }}
nav a:hover {{ color: var(--primary); text-decoration: none; }}
main {{ display: block; }}
section, article, aside {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 30px; margin: 0 0 24px; box-shadow: var(--shadow);
}}
section section, section article, article article {{ box-shadow: none; margin-bottom: 14px; }}
ul {{ list-style: none; padding: 0; margin: 0 0 1em; display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }}
ul li {{
  padding: 16px 18px; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
  font-weight: 600; transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
}}
ul li::before {{ content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 10px; border-radius: 50%; background: var(--primary); vertical-align: middle; }}
ul li:hover {{ transform: translateY(-3px); border-color: var(--primary); box-shadow: var(--shadow); }}
ol {{ padding-left: 1.3em; margin: 0 0 1em; }}
ol li {{ margin: .4em 0; padding-left: .3em; }}
ol li::marker {{ color: var(--primary); font-weight: 700; }}
button, .btn, .button, input[type="submit"], input[type="button"] {{
  display: inline-block; padding: .8em 1.5em; border: 0; border-radius: var(--radius);
  background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer;
  text-decoration: none; transition: transform .2s ease, box-shadow .2s ease, filter .2s ease;
}}
button:hover, .btn:hover, .button:hover, input[type="submit"]:hover {{ transform: translateY(-2px); box-shadow: var(--shadow); filter: brightness(1.08); text-decoration: none; opacity: 1; }}
button:active {{ transform: translateY(0); }}
img, video {{ max-width: 100%; height: auto; display: block; border-radius: var(--radius); }}
figure {{ margin: 0 0 1em; }}
figcaption {{ color: var(--muted); font-size: .9em; margin-top: 6px; }}
blockquote {{ margin: 0 0 1em; padding: 14px 20px; border-left: 4px solid var(--primary); background: var(--bg); border-radius: 0 var(--radius) var(--radius) 0; color: var(--muted); font-style: italic; }}
table {{ width: 100%; border-collapse: collapse; margin: 0 0 1em; }}
th, td {{ padding: .75em 1em; text-align: left; border-bottom: 1px solid var(--border); }}
th {{ color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; }}
tr:hover td {{ background: var(--bg); }}
form {{ display: grid; gap: 12px; }}
label {{ font-weight: 600; font-size: .95em; }}
input:not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]), textarea, select {{
  width: 100%; padding: .75em .9em; font: inherit; color: var(--text);
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); transition: border-color .2s, box-shadow .2s;
}}
input:focus, textarea:focus, select:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 30%, transparent); }}
code {{ font-family: Consolas, 'Cascadia Code', monospace; font-size: .9em; padding: .15em .4em; border-radius: 6px; background: var(--bg); border: 1px solid var(--border); }}
pre {{ padding: 16px; overflow-x: auto; border-radius: var(--radius); background: var(--bg); border: 1px solid var(--border); }}
pre code {{ padding: 0; border: 0; background: none; }}
hr {{ border: 0; height: 1px; background: var(--border); margin: 32px 0; }}
footer {{ text-align: center; color: var(--muted); font-size: .9rem; margin-top: 48px; padding: 24px 0; border-top: 1px solid var(--border); }}
footer a {{ color: var(--muted); }}
@media (max-width: 600px) {{
  body {{ padding: 16px 14px 40px; }}
  header {{ padding: 40px 18px; }}
  section, article, aside {{ padding: 20px; }}
}}"""


def apply(html, style_key, color=None):
    """Swap the page's CSS for the chosen style. Returns the new HTML (CSS in <style> at the top of <head>)."""
    css = stylesheet(style_key, color)
    body = re.sub(r"<style\b[^>]*>.*?</style>\s*", "", html, flags=re.S | re.I)
    # an unfinished <style> (cut-off reply): drop it up to </head>, <body> or the end
    body = re.sub(r"<style\b[^>]*>.*?(?=</head>|<body|\Z)", "", body, flags=re.S | re.I)
    block = "<style>\n" + css + "\n</style>\n"
    m = re.search(r"<head\b[^>]*>", body, re.I)
    if m:
        # after <meta>/<title> lines, still at the top of <head>
        end = re.search(r"</head>", body, re.I)
        if end:
            return body[:end.start()] + block + body[end.start():]
        return body[:m.end()] + "\n" + block + body[m.end():]
    m = re.search(r"<html\b[^>]*>", body, re.I)
    if m:
        return body[:m.end()] + "\n<head>\n<meta charset=\"utf-8\">\n" + block + "</head>\n" + body[m.end():]
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\">\n" + block + "</head>\n<body>\n" + body.strip() + "\n</body>\n</html>")


def describe(style_key, color):
    t = P.S[style_key]
    return t["name"], color or t["primary"]
