"""Generates Profound's CSS training pack: hundreds of real, styled components plus full page templates.
Every file is one HTML page with ALL the CSS at the top (in <style>) and the HTML at the bottom.
Run:  python make_css_pack.py   ->  training_pack/css/*.html  and  training_pack/templates/*.html"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "training_pack")

# ---- design tokens for the 10 style presets
S = {
    "minimal": dict(name="Clean Minimal", bg="#ffffff", surface="#ffffff", text="#111827", muted="#6b7280", primary="#2563eb",
                    on="#ffffff", accent="#0ea5e9", border="#e5e7eb", r="8px", shadow="0 1px 2px rgba(17,24,39,.06)",
                    font="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", head="inherit", fx=""),
    "darksaas": dict(name="Dark SaaS", bg="#0b0f19", surface="#111827", text="#e5e7eb", muted="#94a3b8", primary="#6366f1",
                     on="#ffffff", accent="#22d3ee", border="rgba(255,255,255,.08)", r="14px",
                     shadow="0 20px 40px -20px rgba(99,102,241,.45)", font="system-ui, -apple-system, 'Segoe UI', sans-serif",
                     head="inherit", fx="background-image: linear-gradient(180deg, rgba(255,255,255,.03), transparent);"),
    "glass": dict(name="Glassmorphism", bg="linear-gradient(135deg,#7c3aed,#db2777 55%,#f59e0b)", surface="rgba(255,255,255,.14)",
                  text="#ffffff", muted="rgba(255,255,255,.75)", primary="#ffffff", on="#7c3aed", accent="#fde68a",
                  border="rgba(255,255,255,.3)", r="20px", shadow="0 24px 48px -20px rgba(0,0,0,.35)",
                  font="system-ui, -apple-system, 'Segoe UI', sans-serif", head="inherit",
                  fx="backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);"),
    "neon": dict(name="Neon Cyberpunk", bg="#0a0014", surface="#14002a", text="#f5f3ff", muted="#c4b5fd", primary="#ff2bd6",
                 on="#0a0014", accent="#00f0ff", border="rgba(0,240,255,.45)", r="4px",
                 shadow="0 0 18px rgba(255,43,214,.45), inset 0 0 12px rgba(0,240,255,.15)",
                 font="ui-monospace, 'Cascadia Code', Consolas, monospace", head="inherit", fx=""),
    "pastel": dict(name="Soft Pastel", bg="#fdf6f0", surface="#ffffff", text="#3d3a4b", muted="#7a7590", primary="#f48fb1",
                   on="#3d3a4b", accent="#9be3d0", border="#f1e4ef", r="24px", shadow="0 14px 30px -18px rgba(61,58,75,.35)",
                   font="'Segoe UI Rounded', Nunito, system-ui, sans-serif", head="inherit", fx=""),
    "material": dict(name="Material", bg="#fffbfe", surface="#ffffff", text="#1c1b1f", muted="#625b71", primary="#6750a4",
                     on="#ffffff", accent="#e8def8", border="#e7e0ec", r="16px",
                     shadow="0 1px 3px rgba(0,0,0,.12), 0 4px 12px rgba(0,0,0,.08)", font="Roboto, system-ui, sans-serif",
                     head="inherit", fx=""),
    "brutal": dict(name="Neo-Brutalism", bg="#fffdf5", surface="#ffffff", text="#000000", muted="#333333", primary="#ffde59",
                   on="#000000", accent="#5ce1e6", border="#000000", r="0px", shadow="6px 6px 0 #000",
                   font="'Arial Black', 'Segoe UI Black', system-ui, sans-serif", head="inherit", fx="border-width: 3px !important;"),
    "retro": dict(name="Retro 90s", bg="#008080", surface="#c0c0c0", text="#000000", muted="#404040", primary="#000080",
                  on="#ffffff", accent="#ffff00", border="#808080", r="0px",
                  shadow="inset -2px -2px 0 #808080, inset 2px 2px 0 #ffffff", font="Tahoma, 'MS Sans Serif', sans-serif",
                  head="inherit", fx=""),
    "luxury": dict(name="Luxury", bg="#0c0c0c", surface="#141414", text="#f5f1e6", muted="#a89f8a", primary="#c9a227",
                   on="#0c0c0c", accent="#e8d48b", border="rgba(201,162,39,.35)", r="2px", shadow="0 20px 50px -25px rgba(201,162,39,.35)",
                   font="'Helvetica Neue', Arial, sans-serif", head="Georgia, 'Times New Roman', serif", fx=""),
    "earthy": dict(name="Nature", bg="#f4efe6", surface="#fffaf1", text="#2b2a26", muted="#6d6a5f", primary="#2f5d50",
                   on="#ffffff", accent="#c8663b", border="#e3d5b8", r="18px", shadow="0 16px 30px -22px rgba(47,93,80,.5)",
                   font="'Segoe UI', system-ui, sans-serif", head="Georgia, serif", fx=""),
}


def base(t):
    bg = t["bg"]
    bgdecl = f"background: {bg};" if bg.startswith("linear") else f"background: {bg};"
    return f""":root {{
  --bg: {bg if not bg.startswith('linear') else '#7c3aed'}; --surface: {t['surface']}; --text: {t['text']}; --muted: {t['muted']};
  --primary: {t['primary']}; --on-primary: {t['on']}; --accent: {t['accent']}; --border: {t['border']};
  --radius: {t['r']}; --shadow: {t['shadow']};
  --font: {t['font']}; --head: {t['head']};
}}
* {{ box-sizing: border-box; margin: 0; }}
body {{ font-family: var(--font); {bgdecl} color: var(--text); line-height: 1.6; min-height: 100vh;
       display: grid; place-items: center; padding: 40px 20px; }}
h1, h2, h3 {{ font-family: var(--head); line-height: 1.2; }}
.surface {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow); {t['fx']} }}
"""


# ---- component families: each returns (title, css, html)
def buttons(t):
    return "Buttons", """.row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 12px 22px; border-radius: var(--radius); border: 1px solid transparent;
       font: inherit; font-weight: 600; cursor: pointer; transition: transform .15s ease, box-shadow .2s ease, filter .2s ease; }
.btn:hover { transform: translateY(-2px); filter: brightness(1.05); }
.btn:active { transform: translateY(0); }
.btn:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
.btn-primary { background: var(--primary); color: var(--on-primary); box-shadow: var(--shadow); }
.btn-outline { background: transparent; color: var(--text); border-color: var(--border); }
.btn-ghost { background: transparent; color: var(--primary); }
.btn-pill { border-radius: 999px; }
.btn svg { width: 18px; height: 18px; }""", """<div class="row">
  <button class="btn btn-primary">Get started</button>
  <button class="btn btn-outline">Learn more</button>
  <button class="btn btn-ghost">Cancel</button>
  <button class="btn btn-primary btn-pill">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    Continue</button>
</div>"""


def cards(t):
    return "Feature cards", """.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; width: min(960px, 100%); }
.card { padding: 26px; transition: transform .25s ease, box-shadow .25s ease; }
.card:hover { transform: translateY(-6px); }
.icon { width: 44px; height: 44px; border-radius: calc(var(--radius) * .7); display: grid; place-items: center;
        background: var(--primary); color: var(--on-primary); margin-bottom: 16px; font-weight: 800; }
.card h3 { margin-bottom: 6px; font-size: 1.1rem; }
.card p { color: var(--muted); font-size: .95rem; }""", """<section class="grid">
  <article class="card surface"><div class="icon">1</div><h3>Fast setup</h3><p>Go from zero to live in minutes, not days.</p></article>
  <article class="card surface"><div class="icon">2</div><h3>Secure</h3><p>Encryption and backups switched on by default.</p></article>
  <article class="card surface"><div class="icon">3</div><h3>Scales with you</h3><p>From your first user to your millionth.</p></article>
</section>"""


def navbar(t):
    return "Navbar", """.nav { width: min(1000px, 100%); display: flex; align-items: center; justify-content: space-between; padding: 14px 22px; }
.brand { font-weight: 800; font-size: 1.15rem; display: flex; align-items: center; gap: 10px; }
.brand i { width: 26px; height: 26px; border-radius: calc(var(--radius) * .6); background: var(--primary); display: inline-block; }
.links { display: flex; gap: 24px; list-style: none; padding: 0; }
.links a { color: var(--muted); text-decoration: none; font-weight: 500; transition: color .2s; }
.links a:hover, .links a.active { color: var(--text); }
.signup { padding: 9px 18px; border-radius: var(--radius); background: var(--primary); color: var(--on-primary); text-decoration: none; font-weight: 600; }
@media (max-width: 700px) { .links { display: none; } }""", """<nav class="nav surface">
  <a class="brand"><i></i>Brand</a>
  <ul class="links"><li><a class="active" href="#">Home</a></li><li><a href="#">Features</a></li><li><a href="#">Pricing</a></li><li><a href="#">About</a></li></ul>
  <a class="signup" href="#">Sign up</a>
</nav>"""


def hero(t):
    return "Hero section", """.hero { text-align: center; max-width: 760px; }
.eyebrow { display: inline-block; padding: 6px 14px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); font-size: .85rem; margin-bottom: 20px; }
.hero h1 { font-size: clamp(2.4rem, 6vw, 4rem); letter-spacing: -.03em; margin-bottom: 18px; }
.hero h1 span { color: var(--primary); }
.hero p { color: var(--muted); font-size: 1.15rem; margin-bottom: 30px; }
.actions { display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }
.actions a { padding: 13px 26px; border-radius: var(--radius); font-weight: 600; text-decoration: none; transition: transform .15s; }
.actions a:hover { transform: translateY(-2px); }
.primary { background: var(--primary); color: var(--on-primary); box-shadow: var(--shadow); }
.secondary { border: 1px solid var(--border); color: var(--text); }""", """<header class="hero">
  <span class="eyebrow">New &middot; Version 2.0 is out</span>
  <h1>Build something <span>people love</span></h1>
  <p>Everything you need to design, launch and grow your next idea, in one simple place.</p>
  <div class="actions"><a class="primary" href="#">Start free</a><a class="secondary" href="#">Watch demo</a></div>
</header>"""


def pricing(t):
    return "Pricing cards", """.plans { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; width: min(980px, 100%); align-items: stretch; }
.plan { padding: 28px; display: flex; flex-direction: column; position: relative; }
.plan.best { border: 2px solid var(--primary); transform: scale(1.03); }
.tag { position: absolute; top: -12px; left: 50%; transform: translateX(-50%); background: var(--primary); color: var(--on-primary);
       font-size: .75rem; font-weight: 700; padding: 4px 12px; border-radius: 999px; }
.price { font-size: 2.4rem; font-weight: 800; margin: 10px 0; }
.price small { font-size: .9rem; color: var(--muted); font-weight: 500; }
.plan ul { list-style: none; padding: 0; margin: 16px 0 24px; display: grid; gap: 8px; flex: 1; color: var(--muted); }
.plan li::before { content: "\\2713"; color: var(--primary); margin-right: 8px; font-weight: 800; }
.plan a { text-align: center; padding: 12px; border-radius: var(--radius); border: 1px solid var(--border); color: var(--text); text-decoration: none; font-weight: 600; }
.plan.best a { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }""", """<section class="plans">
  <div class="plan surface"><h3>Starter</h3><div class="price">$0<small>/mo</small></div><ul><li>1 project</li><li>Community help</li></ul><a href="#">Choose</a></div>
  <div class="plan surface best"><span class="tag">Popular</span><h3>Pro</h3><div class="price">$19<small>/mo</small></div><ul><li>Unlimited projects</li><li>Priority support</li><li>Custom domain</li></ul><a href="#">Choose</a></div>
  <div class="plan surface"><h3>Team</h3><div class="price">$49<small>/mo</small></div><ul><li>Everything in Pro</li><li>5 seats</li><li>SSO</li></ul><a href="#">Choose</a></div>
</section>"""


def login(t):
    return "Login form", """.auth { width: min(380px, 100%); padding: 34px; }
.auth h2 { font-size: 1.6rem; margin-bottom: 6px; }
.auth p { color: var(--muted); margin-bottom: 22px; }
label { display: block; font-size: .85rem; font-weight: 600; margin: 14px 0 6px; }
input { width: 100%; padding: 12px 14px; border-radius: calc(var(--radius) * .7); border: 1px solid var(--border);
        background: transparent; color: var(--text); font: inherit; outline: none; transition: border-color .2s, box-shadow .2s; }
input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary) 25%, transparent); }
.submit { width: 100%; margin-top: 22px; padding: 13px; border: 0; border-radius: calc(var(--radius) * .7);
          background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer; }
.alt { text-align: center; margin-top: 16px; font-size: .9rem; color: var(--muted); }
.alt a { color: var(--primary); }""", """<form class="auth surface" onsubmit="event.preventDefault()">
  <h2>Welcome back</h2><p>Sign in to your account.</p>
  <label for="e">Email</label><input id="e" type="email" placeholder="you@example.com" required>
  <label for="p">Password</label><input id="p" type="password" placeholder="Your password" required>
  <button class="submit">Sign in</button>
  <p class="alt">No account? <a href="#">Create one</a></p>
</form>"""


def inputs(t):
    return "Form fields", """.form { width: min(520px, 100%); padding: 28px; display: grid; gap: 16px; }
.field { display: grid; gap: 6px; }
.field label { font-weight: 600; font-size: .9rem; }
.field input, .field select, .field textarea { padding: 12px 14px; border: 1px solid var(--border); border-radius: calc(var(--radius) * .6);
    background: transparent; color: var(--text); font: inherit; outline: none; transition: border-color .2s; }
.field input:focus, .field select:focus, .field textarea:focus { border-color: var(--primary); }
.hint { font-size: .8rem; color: var(--muted); }
.field.error input { border-color: #ef4444; }
.field.error .hint { color: #ef4444; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }""", """<form class="form surface">
  <div class="two"><div class="field"><label>First name</label><input value="Ada"></div><div class="field"><label>Last name</label><input value="Lovelace"></div></div>
  <div class="field error"><label>Email</label><input value="ada@"><span class="hint">Please enter a valid email.</span></div>
  <div class="field"><label>Plan</label><select><option>Starter</option><option>Pro</option></select></div>
  <div class="field"><label>Message</label><textarea rows="4" placeholder="Tell us more..."></textarea></div>
</form>"""


def toggle(t):
    return "Toggle switches", """.list { width: min(420px, 100%); padding: 10px 22px; }
.item { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--border); }
.item:last-child { border: 0; }
.switch { position: relative; width: 48px; height: 28px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; inset: 0; border-radius: 999px; background: var(--border); cursor: pointer; transition: background .25s; }
.slider::after { content: ""; position: absolute; top: 3px; left: 3px; width: 22px; height: 22px; border-radius: 50%; background: #fff;
                 box-shadow: 0 1px 3px rgba(0,0,0,.3); transition: transform .25s; }
.switch input:checked + .slider { background: var(--primary); }
.switch input:checked + .slider::after { transform: translateX(20px); }
.switch input:focus-visible + .slider { outline: 3px solid var(--accent); }""", """<div class="list surface">
  <div class="item"><span>Notifications</span><label class="switch"><input type="checkbox" checked><span class="slider"></span></label></div>
  <div class="item"><span>Dark mode</span><label class="switch"><input type="checkbox"><span class="slider"></span></label></div>
  <div class="item"><span>Auto-save</span><label class="switch"><input type="checkbox" checked><span class="slider"></span></label></div>
</div>"""


def checks(t):
    return "Custom checkboxes and radios", """.box { width: min(420px, 100%); padding: 24px; display: grid; gap: 14px; }
.opt { display: flex; gap: 12px; align-items: center; cursor: pointer; }
.opt input { appearance: none; width: 22px; height: 22px; border: 2px solid var(--border); border-radius: calc(var(--radius) * .3);
             display: grid; place-items: center; transition: all .15s; cursor: pointer; }
.opt input[type=radio] { border-radius: 50%; }
.opt input:checked { background: var(--primary); border-color: var(--primary); }
.opt input[type=checkbox]:checked::after { content: ""; width: 6px; height: 11px; border: solid var(--on-primary); border-width: 0 3px 3px 0; transform: rotate(45deg) translate(-1px, -1px); }
.opt input[type=radio]:checked::after { content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--on-primary); }""", """<fieldset class="box surface" style="border-width:1px">
  <label class="opt"><input type="checkbox" checked> Send me updates</label>
  <label class="opt"><input type="checkbox"> Remember this device</label>
  <label class="opt"><input type="radio" name="p" checked> Monthly billing</label>
  <label class="opt"><input type="radio" name="p"> Yearly billing</label>
</fieldset>"""


def badges(t):
    return "Badges and chips", """.wrap { display: flex; flex-wrap: wrap; gap: 10px; max-width: 520px; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 999px; font-size: .82rem; font-weight: 700;
         background: color-mix(in srgb, var(--c, var(--primary)) 16%, transparent); color: var(--c, var(--primary)); }
.badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 8px 6px 14px; border-radius: 999px; border: 1px solid var(--border); }
.chip button { border: 0; width: 22px; height: 22px; border-radius: 50%; background: var(--border); color: var(--text); cursor: pointer; }""", """<div class="wrap">
  <span class="badge">New</span><span class="badge" style="--c:#16a34a">Active</span><span class="badge" style="--c:#d97706">Pending</span>
  <span class="badge" style="--c:#dc2626">Failed</span>
  <span class="chip">Design <button aria-label="Remove">&times;</button></span><span class="chip">CSS <button aria-label="Remove">&times;</button></span>
</div>"""


def alerts(t):
    return "Alerts", """.stack { width: min(560px, 100%); display: grid; gap: 12px; }
.alert { display: flex; gap: 14px; padding: 16px 18px; border-radius: var(--radius); border: 1px solid color-mix(in srgb, var(--c) 35%, transparent);
         background: color-mix(in srgb, var(--c) 10%, var(--surface)); }
.alert b { color: var(--c); display: block; }
.alert p { color: var(--muted); font-size: .92rem; }
.dot { flex: none; width: 10px; height: 10px; margin-top: 7px; border-radius: 50%; background: var(--c); box-shadow: 0 0 0 4px color-mix(in srgb, var(--c) 25%, transparent); }""", """<div class="stack">
  <div class="alert" style="--c:#16a34a"><span class="dot"></span><div><b>Saved</b><p>Your changes are live.</p></div></div>
  <div class="alert" style="--c:#d97706"><span class="dot"></span><div><b>Heads up</b><p>Your trial ends in 3 days.</p></div></div>
  <div class="alert" style="--c:#dc2626"><span class="dot"></span><div><b>Error</b><p>We couldn't reach the server.</p></div></div>
</div>"""


def modal(t):
    return "Modal dialog", """.backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: grid; place-items: center; animation: fade .2s ease; }
.modal { width: min(420px, 92vw); padding: 28px; animation: pop .25s cubic-bezier(.2,.9,.3,1.2); }
.modal h3 { font-size: 1.3rem; margin-bottom: 8px; }
.modal p { color: var(--muted); margin-bottom: 24px; }
.modal .row { display: flex; justify-content: flex-end; gap: 10px; }
.modal button { padding: 10px 18px; border-radius: calc(var(--radius) * .7); border: 1px solid var(--border); background: transparent; color: var(--text); font: inherit; font-weight: 600; cursor: pointer; }
.modal .danger { background: #dc2626; color: #fff; border-color: #dc2626; }
@keyframes fade { from { opacity: 0; } }
@keyframes pop { from { transform: scale(.92); opacity: 0; } }""", """<div class="backdrop">
  <div class="modal surface" role="dialog" aria-modal="true">
    <h3>Delete project?</h3><p>This permanently removes the project and all its files.</p>
    <div class="row"><button>Cancel</button><button class="danger">Delete</button></div>
  </div>
</div>"""


def tooltip(t):
    return "Tooltips", """.row { display: flex; gap: 40px; padding: 60px; }
.tip { position: relative; padding: 10px 18px; border-radius: var(--radius); background: var(--primary); color: var(--on-primary); font-weight: 600; cursor: help; }
.tip::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 10px); left: 50%; transform: translate(-50%, 6px);
              background: var(--text); color: var(--surface); padding: 6px 10px; border-radius: 6px; font-size: .8rem; white-space: nowrap;
              opacity: 0; pointer-events: none; transition: all .18s ease; }
.tip::before { content: ""; position: absolute; bottom: calc(100% + 4px); left: 50%; transform: translateX(-50%); border: 6px solid transparent;
               border-top-color: var(--text); opacity: 0; transition: opacity .18s; }
.tip:hover::after { opacity: 1; transform: translate(-50%, 0); }
.tip:hover::before { opacity: 1; }""", """<div class="row">
  <span class="tip" data-tip="Saves your work">Save</span>
  <span class="tip" data-tip="Shares a link">Share</span>
</div>"""


def tabs(t):
    return "Tabs", """.tabs { width: min(560px, 100%); overflow: hidden; }
.tablist { display: flex; border-bottom: 1px solid var(--border); }
.tablist button { flex: 1; padding: 14px; border: 0; background: none; color: var(--muted); font: inherit; font-weight: 600; cursor: pointer; border-bottom: 3px solid transparent; transition: color .2s; }
.tablist button[aria-selected=true] { color: var(--primary); border-bottom-color: var(--primary); }
.panel { padding: 22px; color: var(--muted); }
.panel[hidden] { display: none; }""", """<div class="tabs surface">
  <div class="tablist" role="tablist">
    <button role="tab" aria-selected="true" data-t="a">Overview</button><button role="tab" aria-selected="false" data-t="b">Activity</button><button role="tab" aria-selected="false" data-t="c">Settings</button>
  </div>
  <div class="panel" id="a">Everything at a glance.</div><div class="panel" id="b" hidden>12 updates this week.</div><div class="panel" id="c" hidden>Manage your preferences.</div>
</div>
<script>
document.querySelectorAll('[role=tab]').forEach(b => b.onclick = () => document.querySelectorAll('[role=tab]').forEach(x => {
  const on = x === b; x.setAttribute('aria-selected', on); document.getElementById(x.dataset.t).hidden = !on; }));
</script>"""


def accordion(t):
    return "Accordion / FAQ", """.faq { width: min(620px, 100%); padding: 8px 24px; }
details { border-bottom: 1px solid var(--border); padding: 18px 0; }
details:last-child { border: 0; }
summary { cursor: pointer; list-style: none; display: flex; justify-content: space-between; font-weight: 700; }
summary::-webkit-details-marker { display: none; }
summary::after { content: "+"; color: var(--primary); font-size: 1.4rem; line-height: 1; transition: transform .25s; }
details[open] summary::after { transform: rotate(45deg); }
details p { color: var(--muted); margin-top: 10px; animation: open .25s ease; }
@keyframes open { from { opacity: 0; transform: translateY(-4px); } }""", """<section class="faq surface">
  <details open><summary>Can I cancel anytime?</summary><p>Yes, cancel in one click from your settings.</p></details>
  <details><summary>Is there a free trial?</summary><p>Every plan starts with 14 days free.</p></details>
  <details><summary>Do you offer refunds?</summary><p>Full refund within 30 days, no questions asked.</p></details>
</section>"""


def progress(t):
    return "Progress bars", """.box { width: min(460px, 100%); padding: 26px; display: grid; gap: 18px; }
.label { display: flex; justify-content: space-between; font-size: .9rem; font-weight: 600; margin-bottom: 6px; }
.bar { height: 10px; border-radius: 999px; background: var(--border); overflow: hidden; }
.fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--primary), var(--accent)); animation: grow 1.2s ease-out both; }
.striped .fill { background-image: repeating-linear-gradient(45deg, rgba(255,255,255,.25) 0 10px, transparent 10px 20px), linear-gradient(90deg, var(--primary), var(--accent)); }
@keyframes grow { from { width: 0; } }""", """<div class="box surface">
  <div><div class="label"><span>Uploading</span><span>72%</span></div><div class="bar"><div class="fill" style="width:72%"></div></div></div>
  <div class="striped"><div class="label"><span>Storage</span><span>45%</span></div><div class="bar"><div class="fill" style="width:45%"></div></div></div>
</div>"""


def loaders(t):
    return "Loading spinners", """.row { display: flex; gap: 48px; align-items: center; }
.spinner { width: 44px; height: 44px; border-radius: 50%; border: 4px solid var(--border); border-top-color: var(--primary); animation: spin .8s linear infinite; }
.dots { display: flex; gap: 8px; }
.dots span { width: 12px; height: 12px; border-radius: 50%; background: var(--primary); animation: bounce 1s ease-in-out infinite; }
.dots span:nth-child(2) { animation-delay: .15s; } .dots span:nth-child(3) { animation-delay: .3s; }
.pulse { width: 40px; height: 40px; border-radius: 50%; background: var(--primary); animation: pulse 1.4s ease-out infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes bounce { 50% { transform: translateY(-12px); opacity: .5; } }
@keyframes pulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--primary) 60%, transparent); } 100% { box-shadow: 0 0 0 24px transparent; } }
@media (prefers-reduced-motion: reduce) { * { animation-duration: 3s !important; } }""", """<div class="row" role="status" aria-label="Loading">
  <div class="spinner"></div><div class="dots"><span></span><span></span><span></span></div><div class="pulse"></div>
</div>"""


def skeleton(t):
    return "Skeleton loading cards", """.card { width: min(360px, 100%); padding: 22px; }
.sk { border-radius: calc(var(--radius) * .5); background: linear-gradient(90deg, var(--border) 25%, color-mix(in srgb, var(--border) 40%, var(--surface)) 50%, var(--border) 75%);
      background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }
.avatar { width: 52px; height: 52px; border-radius: 50%; }
.line { height: 12px; margin-top: 12px; }
.w60 { width: 60%; } .w90 { width: 90%; } .w40 { width: 40%; }
.media { height: 150px; margin-top: 16px; }
@keyframes shimmer { to { background-position: -200% 0; } }""", """<div class="card surface" aria-busy="true">
  <div style="display:flex;gap:14px;align-items:center"><div class="sk avatar"></div><div style="flex:1"><div class="sk line w60"></div><div class="sk line w40"></div></div></div>
  <div class="sk media"></div><div class="sk line w90"></div><div class="sk line w60"></div>
</div>"""


def avatars(t):
    return "Avatar group", """.team { padding: 26px 30px; display: flex; align-items: center; gap: 18px; }
.stack { display: flex; }
.av { width: 46px; height: 46px; border-radius: 50%; border: 3px solid var(--surface); margin-left: -12px; display: grid; place-items: center;
      color: #fff; font-weight: 800; font-size: .9rem; transition: transform .2s; }
.av:first-child { margin-left: 0; }
.av:hover { transform: translateY(-4px); z-index: 1; }
.more { background: var(--border); color: var(--text); }
.team p { color: var(--muted); font-size: .9rem; }""", """<div class="team surface">
  <div class="stack">
    <span class="av" style="background:#f97316">AJ</span><span class="av" style="background:#8b5cf6">LC</span>
    <span class="av" style="background:#06b6d4">MG</span><span class="av" style="background:#22c55e">NP</span><span class="av more">+8</span>
  </div>
  <p><b>12 people</b> are working on this</p>
</div>"""


def table(t):
    return "Data table", """.wrap { width: min(760px, 100%); overflow-x: auto; padding: 6px; }
table { width: 100%; border-collapse: collapse; font-size: .92rem; }
th { text-align: left; font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); padding: 12px 14px; border-bottom: 1px solid var(--border); }
td { padding: 14px; border-bottom: 1px solid var(--border); }
tr:last-child td { border: 0; }
tbody tr { transition: background .15s; }
tbody tr:hover { background: color-mix(in srgb, var(--primary) 6%, transparent); }
.status { padding: 3px 10px; border-radius: 999px; font-size: .78rem; font-weight: 700; }
.paid { background: #dcfce7; color: #166534; } .due { background: #fef3c7; color: #92400e; }""", """<div class="wrap surface">
<table>
  <thead><tr><th>Invoice</th><th>Customer</th><th>Amount</th><th>Status</th></tr></thead>
  <tbody>
    <tr><td>#1042</td><td>Ava Johnson</td><td>$240.00</td><td><span class="status paid">Paid</span></td></tr>
    <tr><td>#1041</td><td>Liam Chen</td><td>$89.50</td><td><span class="status due">Due</span></td></tr>
    <tr><td>#1040</td><td>Mia Garcia</td><td>$1,200.00</td><td><span class="status paid">Paid</span></td></tr>
  </tbody>
</table></div>"""


def footer(t):
    return "Footer", """.footer { width: min(1000px, 100%); padding: 36px; display: grid; grid-template-columns: 2fr repeat(3, 1fr); gap: 24px; }
.footer h4 { font-size: .85rem; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 12px; }
.footer a { display: block; color: var(--muted); text-decoration: none; margin: 6px 0; transition: color .2s; }
.footer a:hover { color: var(--primary); }
.footer p { color: var(--muted); font-size: .92rem; margin-top: 8px; max-width: 32ch; }
.bottom { grid-column: 1 / -1; border-top: 1px solid var(--border); padding-top: 18px; color: var(--muted); font-size: .85rem; }
@media (max-width: 700px) { .footer { grid-template-columns: 1fr 1fr; } }""", """<footer class="footer surface">
  <div><b>Brand</b><p>Tools that help small teams do big things.</p></div>
  <div><h4>Product</h4><a href="#">Features</a><a href="#">Pricing</a><a href="#">Changelog</a></div>
  <div><h4>Company</h4><a href="#">About</a><a href="#">Careers</a><a href="#">Blog</a></div>
  <div><h4>Legal</h4><a href="#">Privacy</a><a href="#">Terms</a></div>
  <div class="bottom">&copy; 2026 Brand Inc. All rights reserved.</div>
</footer>"""


def testimonial(t):
    return "Testimonial cards", """.quotes { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 20px; width: min(900px, 100%); }
.quote { padding: 26px; display: flex; flex-direction: column; gap: 18px; }
.stars { color: #f59e0b; letter-spacing: 2px; }
.quote p { font-size: 1.02rem; }
.who { display: flex; align-items: center; gap: 12px; }
.who span { width: 40px; height: 40px; border-radius: 50%; background: var(--primary); color: var(--on-primary); display: grid; place-items: center; font-weight: 800; }
.who small { display: block; color: var(--muted); }""", """<section class="quotes">
  <figure class="quote surface"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><p>"We shipped our redesign in a week. Our customers noticed immediately."</p>
    <figcaption class="who"><span>SK</span><div><b>Sara Kim</b><small>Head of Product, Lumen</small></div></figcaption></figure>
  <figure class="quote surface"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><p>"The cleanest tool I've used in years. It just gets out of the way."</p>
    <figcaption class="who"><span>DR</span><div><b>Diego Ruiz</b><small>Founder, Orbit</small></div></figcaption></figure>
</section>"""


def features(t):
    return "Feature list with image", """.split { width: min(980px, 100%); display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: center; }
.split h2 { font-size: clamp(1.8rem, 4vw, 2.6rem); margin-bottom: 14px; }
.split p { color: var(--muted); margin-bottom: 20px; }
.split ul { list-style: none; padding: 0; display: grid; gap: 12px; }
.split li { display: flex; gap: 12px; }
.split li b { flex: none; width: 26px; height: 26px; border-radius: 50%; background: var(--primary); color: var(--on-primary); display: grid; place-items: center; font-size: .8rem; }
.art { aspect-ratio: 4 / 3; border-radius: var(--radius); background: radial-gradient(circle at 30% 30%, var(--accent), transparent 55%), radial-gradient(circle at 70% 70%, var(--primary), transparent 55%), var(--surface); box-shadow: var(--shadow); }
@media (max-width: 760px) { .split { grid-template-columns: 1fr; } }""", """<section class="split">
  <div><h2>Work smarter, not harder</h2><p>Automate the boring parts and focus on what matters.</p>
    <ul><li><b>&#10003;</b>Smart templates for every project</li><li><b>&#10003;</b>Real-time collaboration</li><li><b>&#10003;</b>Works offline</li></ul></div>
  <div class="art" role="img" aria-label="Abstract illustration"></div>
</section>"""


def timeline(t):
    return "Timeline", """.timeline { width: min(560px, 100%); padding: 28px 28px 28px 50px; position: relative; }
.timeline::before { content: ""; position: absolute; left: 30px; top: 34px; bottom: 34px; width: 2px; background: var(--border); }
.step { position: relative; padding-bottom: 26px; }
.step:last-child { padding-bottom: 0; }
.step::before { content: ""; position: absolute; left: -26px; top: 6px; width: 14px; height: 14px; border-radius: 50%; background: var(--surface); border: 3px solid var(--primary); }
.step.done::before { background: var(--primary); }
.step time { font-size: .8rem; color: var(--muted); }
.step h4 { margin: 2px 0 4px; }
.step p { color: var(--muted); font-size: .92rem; }""", """<ol class="timeline surface" style="list-style:none">
  <li class="step done"><time>Jan 2026</time><h4>Idea</h4><p>Sketched the first version on a napkin.</p></li>
  <li class="step done"><time>Mar 2026</time><h4>Beta</h4><p>100 early users joined the waitlist.</p></li>
  <li class="step"><time>Jun 2026</time><h4>Launch</h4><p>Public release and first paying customers.</p></li>
</ol>"""


def breadcrumb(t):
    return "Breadcrumbs and pagination", """.box { padding: 22px 26px; display: grid; gap: 22px; }
.crumbs { display: flex; gap: 8px; list-style: none; padding: 0; font-size: .92rem; }
.crumbs a { color: var(--muted); text-decoration: none; }
.crumbs a:hover { color: var(--primary); }
.crumbs li + li::before { content: "/"; margin-right: 8px; color: var(--border); }
.crumbs [aria-current] { font-weight: 700; }
.pages { display: flex; gap: 6px; }
.pages a { min-width: 38px; height: 38px; display: grid; place-items: center; border-radius: calc(var(--radius) * .6); border: 1px solid var(--border); color: var(--text); text-decoration: none; transition: all .15s; }
.pages a:hover { border-color: var(--primary); }
.pages a.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }""", """<nav class="box surface" aria-label="Navigation">
  <ol class="crumbs"><li><a href="#">Home</a></li><li><a href="#">Shop</a></li><li aria-current="page">Shoes</li></ol>
  <div class="pages"><a href="#">&lsaquo;</a><a href="#">1</a><a class="on" href="#">2</a><a href="#">3</a><a href="#">&rsaquo;</a></div>
</nav>"""


def dropdown(t):
    return "Dropdown menu", """.menu-wrap { position: relative; padding-bottom: 180px; }
.trigger { padding: 11px 18px; border-radius: var(--radius); border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-weight: 600; cursor: pointer; }
.menu { position: absolute; top: calc(100% - 170px); left: 0; min-width: 210px; padding: 6px; display: grid; animation: drop .18s ease; }
.menu a { padding: 10px 12px; border-radius: calc(var(--radius) * .6); color: var(--text); text-decoration: none; display: flex; justify-content: space-between; }
.menu a:hover { background: color-mix(in srgb, var(--primary) 10%, transparent); color: var(--primary); }
.menu kbd { font-family: inherit; color: var(--muted); font-size: .8rem; }
.menu hr { border: 0; border-top: 1px solid var(--border); margin: 6px 0; }
@keyframes drop { from { opacity: 0; transform: translateY(-6px); } }""", """<div class="menu-wrap">
  <button class="trigger" aria-haspopup="menu" aria-expanded="true">Options &#9662;</button>
  <div class="menu surface" role="menu"><a href="#">Edit <kbd>Ctrl+E</kbd></a><a href="#">Duplicate <kbd>Ctrl+D</kbd></a><hr><a href="#" style="color:#dc2626">Delete</a></div>
</div>"""


def sidebar(t):
    return "Sidebar navigation", """.app { width: min(860px, 100%); height: 420px; display: grid; grid-template-columns: 220px 1fr; overflow: hidden; }
.side { padding: 18px 12px; border-right: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.side b { padding: 6px 12px 16px; font-size: 1.1rem; }
.side a { padding: 10px 12px; border-radius: calc(var(--radius) * .6); color: var(--muted); text-decoration: none; transition: all .15s; }
.side a:hover { color: var(--text); background: color-mix(in srgb, var(--primary) 8%, transparent); }
.side a.on { color: var(--primary); background: color-mix(in srgb, var(--primary) 14%, transparent); font-weight: 700; }
.main { padding: 26px; color: var(--muted); }
.main h2 { color: var(--text); margin-bottom: 8px; }""", """<div class="app surface">
  <aside class="side"><b>Workspace</b><a class="on" href="#">Dashboard</a><a href="#">Projects</a><a href="#">Team</a><a href="#">Settings</a></aside>
  <main class="main"><h2>Dashboard</h2><p>Welcome back. Pick a project to continue.</p></main>
</div>"""


def gradient_text(t):
    return "Gradient headline", """.title { text-align: center; }
.title h1 { font-size: clamp(2.6rem, 8vw, 5.5rem); letter-spacing: -.04em; font-weight: 900;
            background: linear-gradient(120deg, var(--primary), var(--accent), var(--primary)); background-size: 200% auto;
            -webkit-background-clip: text; background-clip: text; color: transparent; animation: shine 6s linear infinite; }
.title p { color: var(--muted); font-size: 1.1rem; margin-top: 12px; }
@keyframes shine { to { background-position: 200% center; } }""", """<header class="title"><h1>Make it pop.</h1><p>An animated gradient headline in pure CSS.</p></header>"""


def gallery(t):
    return "Image gallery grid", """.gallery { width: min(900px, 100%); display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); grid-auto-rows: 160px; gap: 12px; }
.tile { border-radius: var(--radius); overflow: hidden; position: relative; cursor: pointer; }
.tile:nth-child(1) { grid-column: span 2; grid-row: span 2; }
.tile div { width: 100%; height: 100%; transition: transform .4s ease; }
.tile:hover div { transform: scale(1.08); }
.tile span { position: absolute; left: 12px; bottom: 10px; color: #fff; font-weight: 700; text-shadow: 0 2px 8px rgba(0,0,0,.5); opacity: 0; transition: opacity .25s; }
.tile:hover span { opacity: 1; }""", """<section class="gallery">
  <a class="tile"><div style="background:linear-gradient(135deg,#f97316,#ec4899)"></div><span>Sunset</span></a>
  <a class="tile"><div style="background:linear-gradient(135deg,#06b6d4,#3b82f6)"></div><span>Ocean</span></a>
  <a class="tile"><div style="background:linear-gradient(135deg,#22c55e,#14b8a6)"></div><span>Forest</span></a>
  <a class="tile"><div style="background:linear-gradient(135deg,#8b5cf6,#6366f1)"></div><span>Dusk</span></a>
  <a class="tile"><div style="background:linear-gradient(135deg,#eab308,#f97316)"></div><span>Desert</span></a>
</section>"""


def stats(t):
    return "Stat cards", """.stats { width: min(900px, 100%); display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 16px; }
.stat { padding: 22px; }
.stat small { color: var(--muted); font-weight: 600; }
.stat strong { display: block; font-size: 2rem; margin: 6px 0; letter-spacing: -.02em; }
.up { color: #16a34a; font-weight: 700; font-size: .85rem; }
.down { color: #dc2626; font-weight: 700; font-size: .85rem; }
.spark { height: 34px; margin-top: 10px; background: linear-gradient(180deg, color-mix(in srgb, var(--primary) 30%, transparent), transparent);
         clip-path: polygon(0 80%, 15% 60%, 30% 70%, 45% 40%, 60% 50%, 75% 25%, 90% 35%, 100% 10%, 100% 100%, 0 100%); }""", """<section class="stats">
  <div class="stat surface"><small>Revenue</small><strong>$48.2k</strong><span class="up">&uarr; 12.4%</span><div class="spark"></div></div>
  <div class="stat surface"><small>Users</small><strong>9,731</strong><span class="up">&uarr; 4.9%</span><div class="spark"></div></div>
  <div class="stat surface"><small>Churn</small><strong>1.8%</strong><span class="down">&darr; 0.3%</span><div class="spark"></div></div>
</section>"""


def notfound(t):
    return "404 page", """.nf { text-align: center; }
.nf h1 { font-size: clamp(5rem, 20vw, 10rem); line-height: 1; font-weight: 900; color: var(--primary); text-shadow: var(--shadow); }
.nf h2 { margin: 10px 0 8px; }
.nf p { color: var(--muted); margin-bottom: 26px; }
.nf a { padding: 12px 24px; border-radius: var(--radius); background: var(--primary); color: var(--on-primary); text-decoration: none; font-weight: 700; display: inline-block; transition: transform .15s; }
.nf a:hover { transform: translateY(-2px); }""", """<main class="nf"><h1>404</h1><h2>Page not found</h2><p>The page you're looking for wandered off.</p><a href="/">Take me home</a></main>"""


def cta(t):
    return "Call-to-action banner", """.cta { width: min(900px, 100%); padding: 44px; text-align: center; position: relative; overflow: hidden; }
.cta::before { content: ""; position: absolute; inset: -40%; background: radial-gradient(circle, color-mix(in srgb, var(--primary) 25%, transparent), transparent 60%); z-index: -1; }
.cta h2 { font-size: clamp(1.6rem, 4vw, 2.4rem); margin-bottom: 10px; }
.cta p { color: var(--muted); margin-bottom: 24px; }
.cta form { display: flex; gap: 10px; max-width: 440px; margin: 0 auto; }
.cta input { flex: 1; padding: 13px 16px; border-radius: var(--radius); border: 1px solid var(--border); background: transparent; color: var(--text); font: inherit; }
.cta button { padding: 13px 22px; border: 0; border-radius: var(--radius); background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer; }
@media (max-width: 520px) { .cta form { flex-direction: column; } }""", """<section class="cta surface" style="isolation:isolate">
  <h2>Ready to get started?</h2><p>Join 10,000+ makers. Free forever for personal projects.</p>
  <form onsubmit="event.preventDefault()"><input type="email" placeholder="Your email" aria-label="Email"><button>Get early access</button></form>
</section>"""


def toast(t):
    return "Toast notifications", """.toasts { position: fixed; right: 20px; bottom: 20px; display: grid; gap: 10px; }
.toast { display: flex; align-items: center; gap: 12px; padding: 14px 16px; min-width: 280px; animation: slide .35s cubic-bezier(.2,.9,.3,1.2); }
.toast i { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-style: normal; font-weight: 800; }
.toast small { display: block; color: var(--muted); }
.toast button { margin-left: auto; border: 0; background: none; color: var(--muted); font-size: 1.2rem; cursor: pointer; }
@keyframes slide { from { transform: translateX(120%); opacity: 0; } }""", """<div class="toasts" aria-live="polite">
  <div class="toast surface"><i style="background:#16a34a">&#10003;</i><div><b>Saved</b><small>Your changes were saved.</small></div><button aria-label="Close">&times;</button></div>
  <div class="toast surface"><i style="background:#2563eb">i</i><div><b>New message</b><small>Ava sent you a file.</small></div><button aria-label="Close">&times;</button></div>
</div>"""


def stepper(t):
    return "Step progress (stepper)", """.stepper { width: min(640px, 100%); padding: 28px; display: flex; justify-content: space-between; position: relative; }
.stepper::before { content: ""; position: absolute; top: 47px; left: 60px; right: 60px; height: 3px; background: var(--border); }
.s { text-align: center; position: relative; flex: 1; }
.s b { width: 40px; height: 40px; margin: 0 auto 8px; border-radius: 50%; display: grid; place-items: center; background: var(--surface); border: 3px solid var(--border); color: var(--muted); }
.s.done b { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.s.now b { border-color: var(--primary); color: var(--primary); }
.s span { font-size: .85rem; color: var(--muted); }""", """<div class="stepper surface">
  <div class="s done"><b>&#10003;</b><span>Account</span></div><div class="s done"><b>&#10003;</b><span>Details</span></div>
  <div class="s now"><b>3</b><span>Payment</span></div><div class="s"><b>4</b><span>Done</span></div>
</div>"""


def profile(t):
    return "Profile card", """.profile { width: min(340px, 100%); text-align: center; padding: 0 0 26px; overflow: hidden; }
.cover { height: 110px; background: linear-gradient(135deg, var(--primary), var(--accent)); }
.pic { width: 96px; height: 96px; border-radius: 50%; margin: -48px auto 10px; border: 5px solid var(--surface); background: #f59e0b; display: grid; place-items: center; font-size: 2rem; font-weight: 800; color: #fff; }
.profile h3 { font-size: 1.2rem; }
.profile p { color: var(--muted); font-size: .92rem; margin: 4px 22px 18px; }
.nums { display: flex; justify-content: center; gap: 26px; margin-bottom: 20px; }
.nums b { display: block; font-size: 1.15rem; }
.nums span { color: var(--muted); font-size: .8rem; }
.follow { padding: 10px 26px; border-radius: 999px; border: 0; background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer; }""", """<article class="profile surface">
  <div class="cover"></div><div class="pic">MK</div><h3>Maya Kim</h3><p>Product designer making calm, friendly interfaces.</p>
  <div class="nums"><div><b>128</b><span>Posts</span></div><div><b>4.2k</b><span>Followers</span></div><div><b>312</b><span>Following</span></div></div>
  <button class="follow">Follow</button>
</article>"""


def search(t):
    return "Search bar", """.search { width: min(560px, 100%); display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 18px; border-radius: 999px; transition: box-shadow .2s; }
.search:focus-within { box-shadow: 0 0 0 4px color-mix(in srgb, var(--primary) 25%, transparent), var(--shadow); }
.search svg { width: 20px; height: 20px; color: var(--muted); flex: none; }
.search input { flex: 1; border: 0; background: transparent; color: var(--text); font: inherit; font-size: 1rem; outline: none; padding: 8px 0; }
.search kbd { font-family: inherit; font-size: .78rem; color: var(--muted); border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; }
.search button { border: 0; border-radius: 999px; padding: 10px 20px; background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer; }""", """<form class="search surface" role="search" onsubmit="event.preventDefault()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
  <input placeholder="Search anything..." aria-label="Search"><kbd>Ctrl K</kbd><button>Search</button>
</form>"""


FAMILIES = [buttons, cards, navbar, hero, pricing, login, inputs, toggle, checks, badges, alerts, modal, tooltip, tabs, accordion,
            progress, loaders, skeleton, avatars, table, footer, testimonial, features, timeline, breadcrumb, dropdown, sidebar,
            gradient_text, gallery, stats, notfound, cta, toast, stepper, profile, search]


def page(title, t, css, html, note):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - {t['name']}</title>
<style>
/* {title} | style: {t['name']} | {note}
   Layout rule: all CSS here at the top, the HTML below. */
{base(t)}
{css}
</style>
</head>
<body>
{html}
</body>
</html>
"""


def landing(key, t):
    """A full landing page template in this style, assembled from the components."""
    parts = [navbar(t), hero(t), cards(t), testimonial(t), pricing(t), cta(t), footer(t)]
    css = "\n".join(p[1] for p in parts) + """
body { display: block; padding: 0; }
.page { width: min(1080px, 92vw); margin: 0 auto; display: grid; gap: 90px; padding: 24px 0 60px; justify-items: center; }"""
    html = '<div class="page">\n' + "\n".join(p[2] for p in parts) + "\n</div>"
    return page("Landing page template", t, css, html, "full page template: navbar, hero, features, testimonials, pricing, CTA, footer")


def main():
    css_dir, tpl_dir = os.path.join(OUT, "css"), os.path.join(OUT, "templates")
    os.makedirs(css_dir, exist_ok=True)
    os.makedirs(tpl_dir, exist_ok=True)
    n = 0
    for key, t in S.items():
        for fam in FAMILIES:
            title, css, html = fam(t)
            slug = fam.__name__.replace("_", "-")
            with open(os.path.join(css_dir, f"{slug}-{key}.html"), "w", encoding="utf-8") as f:
                f.write(page(title, t, css, html, f"CSS component: {title.lower()}"))
            n += 1
        with open(os.path.join(tpl_dir, f"landing-{key}.html"), "w", encoding="utf-8") as f:
            f.write(landing(key, t))
    print(f"wrote {n} CSS components ({len(FAMILIES)} kinds x {len(S)} styles) and {len(S)} landing page templates")


if __name__ == "__main__":
    main()
