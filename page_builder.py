"""Quick build page assembler: Profound builds the page (style, colour, sections, CSS at the top, HTML below)
from its own CSS components, and the AI only writes the words. Reliable even on very small models."""
import html as _html
import json
import re

import make_css_pack as P

# JSON shape the AI fills in (the engine is constrained to this schema, so the result is always valid)
SCHEMA = {
    "type": "object",
    "properties": {
        "brand": {"type": "string"}, "eyebrow": {"type": "string"}, "headline": {"type": "string"},
        "highlight": {"type": "string"}, "subtitle": {"type": "string"},
        "cta_primary": {"type": "string"}, "cta_secondary": {"type": "string"},
        "features": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "text": {"type": "string"}}, "required": ["title", "text"]}},
        "testimonials": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "object", "properties": {
            "quote": {"type": "string"}, "name": {"type": "string"}, "role": {"type": "string"}}, "required": ["quote", "name", "role"]}},
        "plans": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "price": {"type": "string"},
            "features": {"type": "array", "minItems": 2, "maxItems": 3, "items": {"type": "string"}}}, "required": ["name", "price", "features"]}},
        "faq": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "object", "properties": {
            "q": {"type": "string"}, "a": {"type": "string"}}, "required": ["q", "a"]}},
        "footer": {"type": "string"},
    },
    "required": ["brand", "eyebrow", "headline", "highlight", "subtitle", "cta_primary", "cta_secondary",
                 "features", "testimonials", "plans", "faq", "footer"],
}

DEFAULT = {"brand": "Brand", "eyebrow": "Welcome", "headline": "Something wonderful starts here", "highlight": "wonderful",
           "subtitle": "Everything you need, in one simple place.", "cta_primary": "Get started", "cta_secondary": "Learn more",
           "features": [{"title": "Simple", "text": "Easy to use from day one."}, {"title": "Fast", "text": "Quick and reliable."},
                        {"title": "Friendly", "text": "Real people ready to help."}],
           "testimonials": [{"quote": "Absolutely love it.", "name": "Sam Lee", "role": "Customer"},
                            {"quote": "Would recommend to anyone.", "name": "Ana Silva", "role": "Customer"}],
           "plans": [{"name": "Basic", "price": "$9", "features": ["Essentials", "Email support"]},
                     {"name": "Plus", "price": "$19", "features": ["Everything in Basic", "Priority help"]},
                     {"name": "Pro", "price": "$39", "features": ["Everything in Plus", "Extras"]}],
           "faq": [{"q": "How do I start?", "a": "Just sign up, it takes a minute."}, {"q": "Can I cancel?", "a": "Yes, anytime."},
                   {"q": "Do you offer support?", "a": "We're here every day."}],
           "footer": "Made with care."}


def prompt_for(page_label, what):
    return (f"Write the website text for a {page_label.lower()} for: {what or 'a modern small business'}. "
            "Be specific to that topic, warm and concise. Headline: max 8 words; highlight: 1-3 words copied from the "
            "headline; subtitle: one sentence; features, testimonials, plans and FAQ must fit the topic. "
            "Reply with JSON only.")


def parse_content(text):
    """Best effort: the engine normally returns valid JSON; fall back to defaults for anything missing."""
    try:
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
    except (ValueError, AttributeError):
        data = {}
    out = dict(DEFAULT)
    for k, v in data.items():
        if k in out and v:
            out[k] = v
    return out


def _on(color):
    c = color.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 165 else "#ffffff"


def e(s):
    return _html.escape(str(s))


def build_page(style_key, color, sections, c, page_label="Landing page"):
    """Assemble a full page: all CSS in <style> at the top, HTML below."""
    t = dict(P.S[style_key])
    t["primary"], t["on"] = color, _on(color)
    css, body = [], []

    def add(fn, html):
        css.append(fn(t)[1])
        body.append(html)

    if "Navbar" in sections:
        add(P.navbar, f'''<nav class="nav surface">
  <a class="brand" href="#"><i></i>{e(c["brand"])}</a>
  <ul class="links"><li><a class="active" href="#">Home</a></li><li><a href="#features">Features</a></li>{'<li><a href="#pricing">Pricing</a></li>' if "Pricing" in sections else ''}{'<li><a href="#faq">FAQ</a></li>' if "FAQ" in sections else ''}</ul>
  <a class="signup" href="#">{e(c["cta_primary"])}</a>
</nav>''')
    if "Hero" in sections:
        head = e(c["headline"])
        hl = e(c["highlight"])
        if hl and hl in head:
            head = head.replace(hl, f"<span>{hl}</span>", 1)
        add(P.hero, f'''<header class="hero">
  <span class="eyebrow">{e(c["eyebrow"])}</span>
  <h1>{head}</h1>
  <p>{e(c["subtitle"])}</p>
  <div class="actions"><a class="primary" href="#">{e(c["cta_primary"])}</a><a class="secondary" href="#">{e(c["cta_secondary"])}</a></div>
</header>''')
    if "Features" in sections:
        cards = "\n".join(f'  <article class="card surface"><div class="icon">{i + 1}</div><h3>{e(f["title"])}</h3><p>{e(f["text"])}</p></article>'
                          for i, f in enumerate(c["features"][:6]))
        add(P.cards, f'<section class="grid" id="features">\n{cards}\n</section>')
    if "Testimonials" in sections:
        quotes = "\n".join(f'''  <figure class="quote surface"><div class="stars">&#9733;&#9733;&#9733;&#9733;&#9733;</div><p>&ldquo;{e(q["quote"])}&rdquo;</p>
    <figcaption class="who"><span>{e("".join(w[0] for w in q["name"].split()[:2]).upper())}</span><div><b>{e(q["name"])}</b><small>{e(q["role"])}</small></div></figcaption></figure>'''
                           for q in c["testimonials"][:3])
        add(P.testimonial, f'<section class="quotes">\n{quotes}\n</section>')
    if "Pricing" in sections:
        plans = []
        for i, p in enumerate(c["plans"][:3]):
            best = i == 1
            items = "".join(f"<li>{e(x)}</li>" for x in p.get("features", [])[:4])
            price = e(p["price"])
            tag = '<span class="tag">Popular</span>' if best else ""
            cls = "plan surface best" if best else "plan surface"
            plans.append(f'  <div class="{cls}">{tag}<h3>{e(p["name"])}</h3><div class="price">{price}<small>/mo</small></div>'
                         f'<ul>{items}</ul><a href="#">Choose</a></div>')
        add(P.pricing, '<section class="plans" id="pricing">\n' + "\n".join(plans) + "\n</section>")
    if "FAQ" in sections:
        faq = "\n".join(f'  <details{" open" if i == 0 else ""}><summary>{e(q["q"])}</summary><p>{e(q["a"])}</p></details>'
                        for i, q in enumerate(c["faq"][:5]))
        add(P.accordion, f'<section class="faq surface" id="faq">\n{faq}\n</section>')
    if "Contact form" in sections:
        add(P.inputs, '''<form class="form surface" onsubmit="event.preventDefault(); this.querySelector('button').textContent = 'Thanks! We\\'ll be in touch';">
  <h2>Get in touch</h2>
  <div class="two"><div class="field"><label>Name</label><input required></div><div class="field"><label>Email</label><input type="email" required></div></div>
  <div class="field"><label>Message</label><textarea rows="4"></textarea></div>
  <button class="send">Send message</button>
</form>''')
        css.append(""".form h2 { margin-bottom: 4px; }
.send { padding: 13px; border: 0; border-radius: var(--radius); background: var(--primary); color: var(--on-primary); font: inherit; font-weight: 700; cursor: pointer; }""")
    if "Footer" in sections:
        add(P.footer, f'''<footer class="footer surface">
  <div><b>{e(c["brand"])}</b><p>{e(c["footer"])}</p></div>
  <div><h4>Explore</h4><a href="#">Home</a><a href="#features">Features</a></div>
  <div><h4>Company</h4><a href="#">About</a><a href="#">Contact</a></div>
  <div><h4>Legal</h4><a href="#">Privacy</a><a href="#">Terms</a></div>
  <div class="bottom">&copy; 2026 {e(c["brand"])}. All rights reserved.</div>
</footer>''')
    css.append("""body { display: block; padding: 0; }
.page { width: min(1080px, 92vw); margin: 0 auto; display: grid; gap: 80px; padding: 24px 0 60px; justify-items: center; }""")
    html = '<div class="page">\n' + "\n".join(body) + "\n</div>"
    return P.page(f'{c["brand"]} - {page_label}', t, "\n".join(css), html, f"{page_label} built by Profound Quick build")
