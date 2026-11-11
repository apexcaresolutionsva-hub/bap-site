#!/usr/bin/env python3
"""Builds the buybap.com site into ./dist from live numbers in the BAP database.

Why this exists: the site used to keep hand-typed copies of facts the app already knows (lead counts, prices,
plan limits, which counties we cover). They went stale. Now every number comes from one public database function,
site_stats(), at build time, and the deploy workflow rebuilds the site every morning.

  python tools/build_site.py                      # fetch live numbers, write dist/
  python tools/build_site.py --stats-file f.json  # use a saved copy instead (for testing)

If the numbers can't be fetched, or any sanity check fails, the build exits non-zero and the deploy is skipped,
so the live site simply keeps yesterday's version.

Hand-edited content lives in: data/features.json (tools), data/counties.json (which county pages exist),
and the templates below. Nothing in dist/ is edited by hand.
"""
import argparse, html, json, re, shutil, sys, time, urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SITE = "https://www.buybap.com"
APP = "https://app.buybap.com"
SB_URL = "https://rpcdrgzcaarggupctede.supabase.co"
SB_KEY = "sb_publishable_qyI3EzhYghqCmRnhu41ucg_lhzhufqt"  # public anon key, already shipped in the site's JS
MIN_COUNTY_PROPERTIES = 300  # a county gets its own page only when it has this much data of its own
BOOK_A_CALL = "https://calendar.google.com/calendar/appointments/schedules/AcZssZ16HsxPcGoraMYWnF1kXXbE9RIOc8MFcIwc0UEP2MzVi6r4JVuyNByDFOE8LhCAnGYnszwY2fy8"
FORBIDDEN = ["757-535-2547", "(757) 535-2547", "214-477-7727", "(214) 477-7727"]
SKIP_TOP = {".git", ".github", "tools", "data", "dist", "leads", "features", "node_modules"}
SKIP_FILES = {"index.html", "sitemap.xml", "README.md", ".gitignore"}

STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
          "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
          "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
          "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
          "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
          "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
          "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
          "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
          "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}

esc = html.escape


def die(msg):
    print("BUILD FAILED:", msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- numbers

def fetch_stats():
    req = urllib.request.Request(SB_URL + "/rest/v1/rpc/site_stats", data=b"{}", method="POST",
                                 headers={"apikey": SB_KEY, "Content-Type": "application/json"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # network blip or a cold database: wait and retry
            last = e
            time.sleep(3 * (attempt + 1))
    die(f"could not fetch site_stats(): {last}")


def money(x):
    return f"${x:g}" if float(x).is_integer() else f"${x:.2f}"


def price(x):
    return f"{round(x * 100)}¢" if x < 1 else money(x)


def round_down(n, step):
    return (n // step) * step


def build_vars(stats):
    t = stats.get("totals") or {}
    svc = {s["key"]: s for s in stats["services"]}

    def member(key):
        if key not in svc:
            die(f"service '{key}' missing from site_stats()")
        return svc[key]["price_member"]

    postcards = [member(k) for k in ("mail_postcard_4x6", "mail_postcard_6x9")]
    return {
        "properties_fmt": f"{round_down(int(t['properties']), 10000):,}+",
        "counties": f"{int(t['counties']):,}",
        "states": f"{int(t['states'])}",
        "deals_for_sale_fmt": f"{round_down(int(t['deals_for_sale']), 100):,}+",
        "lenders_and_contractors_fmt": f"{round_down(int(t['lenders_and_contractors']), 500):,}+",
        "texas_contract_templates": f"{int(t['texas_contract_templates'])}",
        "price_national_lead": price(member("national_lead")),
        "price_skiptrace": price(member("skiptrace")),
        "price_valuation": money(member("valuation")),
        "price_ai": money(member("ai_analysis")),
        "price_postcard_low": money(min(postcards)),
    }


def fill(text, v):
    def sub(m):
        if m.group(1) not in v:
            die(f"unknown placeholder {{{{{m.group(1)}}}}}")
        return str(v[m.group(1)])
    return re.sub(r"\{\{(\w+)\}\}", sub, text)


# ---------------------------------------------------------------- shared pieces

CSS = """
:root{--bg:#fff;--soft:#f5f5f7;--fg:#1d1d1f;--muted:#5f6368;--line:#e3e5ea;--accent:#0a66d9;--accent-fg:#fff;--ok:#127a43;--err:#b42318;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#000;--soft:#111214;--fg:#f2f3f5;--muted:#a0a6b0;--line:#26282c;--accent:#4da3ff;--accent-fg:#00152e;--ok:#4cc38a;--err:#ff8a7a;color-scheme:dark}}
*{box-sizing:border-box} html{background:var(--bg);scroll-behavior:smooth} body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)} .wrap{max-width:1040px;margin:0 auto;padding:0 18px}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top,0px)}
header .wrap{display:flex;align-items:center;gap:16px;min-height:58px;flex-wrap:wrap} .logo{display:flex;align-items:center;gap:9px;font-weight:800;font-size:1.25rem;text-decoration:none;color:var(--fg);margin-right:auto}
.logo img{width:30px;height:30px;border-radius:7px;display:block}
header nav{display:flex;gap:14px;flex-wrap:wrap;align-items:center} header nav a{text-decoration:none;color:var(--fg);font-size:.95rem}
@media (max-width:760px){header .wrap{gap:6px 12px} header nav{order:3;flex:1 0 100%;flex-wrap:nowrap;overflow-x:auto;padding:2px 0 10px;scrollbar-width:none} header nav a{white-space:nowrap} .logo{margin-right:0} header .cta{margin-left:auto}}
.btn{display:inline-block;background:var(--accent);color:var(--accent-fg)!important;padding:10px 16px;border-radius:10px;font-weight:700;text-decoration:none;border:0;cursor:pointer;font-size:1rem}
.btn.ghost{background:transparent;color:var(--accent)!important;border:1.5px solid var(--accent)} header .btn{padding:7px 13px;font-size:.92rem}
.hero{padding:56px 0 36px} .hero h1{font-size:clamp(1.9rem,4.5vw,3rem);line-height:1.15;margin:0 0 12px} .hero p{font-size:1.15rem;color:var(--muted);max-width:660px}
.row{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px} section{padding:34px 0} section.soft{background:var(--soft)}
h2{font-size:1.6rem;margin:0 0 10px} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-top:16px}
.card{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:18px} .card h3{margin:0 0 6px;font-size:1.1rem} .card p{margin:0;color:var(--muted)}
.card ul{margin:8px 0 0;padding-left:18px;color:var(--muted)} .card .more{display:inline-block;margin-top:10px;font-weight:600;text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:26px}
.stat{background:var(--soft);border-radius:14px;padding:14px 16px} .stat b{display:block;font-size:1.6rem;line-height:1.2} .stat span{color:var(--muted);font-size:.9rem}
form{display:grid;gap:12px;max-width:620px} label{display:grid;gap:4px;font-weight:600;font-size:.95rem}
input,select,textarea{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--fg);width:100%;max-width:100%}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px} @media (max-width:560px){.two{grid-template-columns:1fr}}
.check{display:flex;gap:8px;align-items:flex-start;font-weight:400;font-size:.9rem;color:var(--muted)} .check input{width:auto;margin-top:4px}
.hp{position:absolute;left:-9999px} .msg{font-weight:600} .msg.ok{color:var(--ok)} .msg.err{color:var(--err)}
details{border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0;background:var(--bg)} summary{cursor:pointer;font-weight:700}
footer{border-top:1px solid var(--line);padding:26px 0 calc(26px + env(safe-area-inset-bottom,0px));color:var(--muted);font-size:.92rem} footer .wrap{display:flex;gap:16px;flex-wrap:wrap}
.small{font-size:.9rem;color:var(--muted)} .result{display:grid;gap:12px;margin-top:14px} .tag{display:inline-block;font-size:.78rem;font-weight:700;padding:2px 9px;border-radius:99px;background:var(--soft);border:1px solid var(--line);color:var(--fg);white-space:nowrap}
.tag.early,.tag.addon{border-color:var(--accent);color:var(--accent)} .tag.free,.tag.included{border-color:transparent}
.tool{display:flex;flex-direction:column;gap:6px} .tool .tag{align-self:flex-start;margin-bottom:2px} .tool a.more{margin-top:4px}
.jump{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px} .jump a{text-decoration:none;background:var(--soft);padding:6px 13px;border-radius:99px;color:var(--fg);font-size:.92rem}
.ql{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px} .ql a{text-decoration:none;background:var(--soft);padding:6px 13px;border-radius:99px;color:var(--fg);font-size:.92rem}
section[id]{scroll-margin-top:64px}
.herogrid{display:grid;grid-template-columns:1.15fr .85fr;gap:36px;align-items:center} @media (max-width:860px){.herogrid{grid-template-columns:1fr}}
.mock{margin:0;display:grid;gap:12px} .mock figcaption{font-size:.8rem;color:var(--muted)}
.mcard{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:0 6px 24px rgba(0,0,0,.07)}
.mhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
.mscore{background:var(--accent);color:var(--accent-fg);font-weight:700;font-size:.8rem;padding:2px 10px;border-radius:99px;white-space:nowrap}
.mtag{border:1px solid var(--accent);color:var(--accent);font-weight:700;font-size:.75rem;padding:1px 9px;border-radius:99px}
.mchips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px} .mchips span{background:var(--soft);border-radius:99px;font-size:.78rem;padding:2px 10px}
.mrows{display:grid;gap:5px} .mrows div{display:flex;justify-content:space-between;gap:10px;font-size:.92rem} .mrows span{color:var(--muted)}
.mtoday{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:.9rem} .mtoday span{color:var(--muted)}
.prose h2{margin-top:26px} .prose p,.prose li{font-size:1.04rem} .prose ul{padding-left:22px}
.statelist{columns:2 260px;column-gap:24px;margin:12px 0 0;padding:0;list-style:none} .statelist li{break-inside:avoid;padding:3px 0}
"""

FOOT_SCRIPT = """document.querySelectorAll('[data-ev]').forEach(a=>a.addEventListener('click',()=>{try{gtag('event',a.dataset.ev)}catch(e){}}));
// pass a post's or ad's utm_ tags through to the app so BAP knows which channel brought each signup
(function(){try{const u=[...new URLSearchParams(location.search)].filter(([k])=>/^utm_/.test(k));if(!u.length)return;document.querySelectorAll('a[href^="https://app.buybap.com/"]').forEach(l=>{if(/\\/(terms|privacy|refunds)\\//.test(l.href))return;const x=new URL(l.href);u.forEach(([k,v])=>x.searchParams.set(k,v));l.href=x.toString();});}catch(e){}})();"""

LEGAL = ("BAP is real estate software and data. BAP is not a real estate broker, agent, lender, appraiser, law firm or financial advisor, "
         "and nothing on this site or in the app is legal, tax or financial advice. Property and owner data comes from public records and "
         "third-party providers and may be incomplete or out of date; verify before you rely on it. Real estate investing involves risk: "
         "BAP does not guarantee that you will find or close deals or make money, and examples are not typical results. Wholesaling, "
         "licensing, telemarketing and texting laws vary by state; you are responsible for following them. Plans renew automatically "
         "until canceled; see the Terms.")


def head_tags(title, desc, path=None, jsonld=None, noindex=False):
    """Everything inside <head> except the CSS: title, description, canonical, social cards, icons, theme color, analytics."""
    url = SITE + path if path else None
    t, d = esc(title, quote=True), esc(desc, quote=True)
    out = [f'<meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           f"<title>{esc(title)}</title>", f'<meta name="description" content="{d}">']
    if noindex:
        out.append('<meta name="robots" content="noindex">')
    if url:
        out.append(f'<link rel="canonical" href="{url}">')
    out += ['<meta property="og:type" content="website">', '<meta property="og:site_name" content="BAP">',
            f'<meta property="og:title" content="{t}">', f'<meta property="og:description" content="{d}">']
    if url:
        out.append(f'<meta property="og:url" content="{url}">')
    out += [f'<meta property="og:image" content="{SITE}/og-image.png">', '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            '<meta property="og:image:alt" content="BAP: find distressed properties, run the numbers, close.">',
            '<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:title" content="{t}">',
            f'<meta name="twitter:description" content="{d}">', f'<meta name="twitter:image" content="{SITE}/og-image.png">',
            '<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">',
            '<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">',
            '<link rel="icon" type="image/png" href="/icon-192.png">', '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
            '<script async src="https://www.googletagmanager.com/gtag/js?id=G-NW1CM3V8C2"></script>',
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-NW1CM3V8C2',{anonymize_ip:true});</script>"]
    for block in (jsonld or []):
        out.append('<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    return "\n".join(out)


def crumbs(items):
    """items: [(name, path)] from the homepage down. Returns a BreadcrumbList for Google plus a visible trail."""
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + pth} for i, (n, pth) in enumerate(items)]}
    trail = " › ".join(f'<a href="{pth}">{esc(n)}</a>' for n, pth in items[:-1]) + f" › {esc(items[-1][0])}"
    return ld, f'<p class="small" style="margin:0 0 10px">{trail}</p>'


def header_html():
    return ('<header><div class="wrap"><a class="logo" href="/"><img src="/icon-192.png" alt="" width="30" height="30">BAP</a><nav>'
            '<a href="/features/">Features</a><a href="/leads/">Leads by county</a><a href="/#pricing">Pricing</a>'
            '<a href="/cash-offer/">Sell a house</a><a href="/funding/">Funding</a><a href="/post-a-deal/">Post a deal</a></nav>'
            f'<a class="btn ghost cta" href="{APP}/" data-ev="open_app">Sign in</a>'
            f'<a class="btn" href="{APP}/?utm_source=site&utm_medium=nav#demo" data-ev="try_demo">Try the demo</a></div></header>')


def footer_html():
    return ('<footer><div class="wrap"><span>© 2026 Apex Care Solutions VA LLC dba BAP</span>'
            f'<a href="{APP}/terms/">Terms</a><a href="{APP}/privacy/">Privacy</a><a href="{APP}/refunds/">Refunds</a>'
            '<a href="/features/">Features</a><a href="/leads/">Leads by county</a><a href="/guides/">Guides</a>'
            f'<a href="{BOOK_A_CALL}" target="_blank" rel="noopener">Book a call</a>'
            '<a href="mailto:support@buybap.com">support@buybap.com</a><span>469-224-1122</span>'
            '<span>5245 Cleveland St, Ste 204, Virginia Beach, VA 23462</span></div>'
            f'<div class="wrap"><p style="margin:12px 0 0;font-size:.8rem;line-height:1.5">{LEGAL}</p></div></footer>')


def page(title, desc, path, body, jsonld=None, extra_script=""):
    return (f'<!doctype html>\n<html lang="en"><head>\n{head_tags(title, desc, path, jsonld)}\n<style>{CSS}</style></head><body>\n'
            f'{header_html()}\n<main>\n{body}\n</main>\n{footer_html()}\n<script>\n{FOOT_SCRIPT}\n{extra_script}</script>\n</body></html>\n')


def demo_btns(utm="hero"):
    return (f'<a class="btn" href="{APP}/?utm_source=site&utm_medium={utm}#demo" data-ev="try_demo">Try the free demo</a>'
            f'<a class="btn ghost" href="{APP}/" data-ev="open_app">Open BAP</a>')


# ---------------------------------------------------------------- pricing

def plan_blurb(p, v):
    bits = [f"<b>Unlimited BAP leads</b>" + (f" for {p['seats']} users" if p["seats"] > 1 else ""),
            f"{p['national_lead']:,} on-demand nationwide leads", f"{p['skiptrace']:,} skip traces"]
    if p["ai_analysis"]:
        bits.append(f"{p['ai_analysis']} AI deal analyses")
    text = bits[0] + ", plus " + ", ".join(bits[1:-1]) + (" and " if len(bits) > 2 else "") + bits[-1] + " a month."
    if p["mail_discount"]:
        text = text[:-1] + f", and {round(p['mail_discount'] * 100)}% off mail."
    if p["key"] == "pro":
        text += f" Try it free for 7 days, then {money(p['monthly'])}/month unless you cancel before the trial ends."
    elif p["key"] == "starter":
        text += " Pipeline, list imports, contracts and e-signing included."
    return text


def pricing_cards(stats, v):
    cards = []
    for p in stats["plans"]:
        free_months = round(12 - p["yearly"] / p["monthly"])
        pop = ' <span class="small">· most popular</span>' if p["key"] == "pro" else ""
        yearly = f' Or {money(p["yearly"])}/year ({free_months} months free).' if free_months > 0 else ""
        cards.append(f'<div class="card"><h3>{esc(p["name"])}: {money(p["monthly"])}/month{pop}</h3><p>{plan_blurb(p, v)}{yearly}</p></div>')
    cards.append('<div class="card"><h3>Free</h3><p>Browse BAP\'s leads and unlock 10 a month. Pay as you go for anything else. Cancel paid plans anytime.</p></div>')
    return "".join(cards)


def pricing_note(v):
    return (f"Unlimited means no monthly cap on BAP's own leads (each user can open up to 300 new leads a day). On-demand nationwide leads cover "
            f"counties BAP doesn't collect yet; extra ones are {v['price_national_lead']} each from prepaid credits.")


# ---------------------------------------------------------------- features

def load_features(v):
    data = json.loads((ROOT / "data" / "features.json").read_text(encoding="utf-8"))
    labels = data["status_labels"]
    for g in data["groups"]:
        for tool in g["tools"]:
            if tool["status"] not in labels:
                die(f"features.json: unknown status {tool['status']!r} on {tool['name']!r}")
            tool["text"] = fill(tool["text"], v)
    return data


def tool_card(tool, labels):
    link = f'<a class="more" href="{esc(tool["href"])}">Open →</a>' if tool.get("href") else ""
    if tool.get("slug"):
        link = f'<a class="more" href="/features/{tool["slug"]}/">Learn more →</a>'
    tag = f'<span class="tag {tool["status"]}">{esc(labels[tool["status"]])}</span>'
    return f'<div class="card tool">{tag}<h3>{esc(tool["name"])}</h3><p>{esc(tool["text"])}</p>{link}</div>'


def features_page(feat, stats, v):
    labels = feat["status_labels"]
    jump = "".join(f'<a href="#{g["id"]}">{esc(g["title"])}</a>' for g in feat["groups"])
    secs = []
    for i, g in enumerate(feat["groups"]):
        cards = "".join(tool_card(t, labels) for t in g["tools"])
        cls = ' class="soft"' if i % 2 == 0 else ""
        secs.append(f'<section{cls} id="{g["id"]}"><div class="wrap"><h2>{esc(g["title"])}</h2><p class="small">{esc(g["blurb"])}</p><div class="grid">{cards}</div></div></section>')
    n = sum(len(g["tools"]) for g in feat["groups"])
    body = (f'<div class="wrap hero"><h1>Everything BAP does</h1><p>{n} tools for finding, reaching, analyzing and closing real estate deals, all in one app. '
            f'Each one is labeled with how it is included, so you know what is in your plan and what costs extra.</p>'
            f'<div class="jump">{jump}</div><div class="row">{demo_btns("features")}</div></div>' + "".join(secs) +
            f'<section class="soft"><div class="wrap"><p class="small">Features, allowances and availability may change, and some depend on your plan, location or third-party approval. Data comes from public records and third parties and may be incomplete or out of date. Estimates and AI output can be wrong. BAP does not guarantee results, deals or income. Add-ons and early-access features are offered subject to availability.</p></div></section>' +
            f'<section><div class="wrap"><h2>Ready to look around?</h2><p>The demo needs no account and nothing you do is saved or sent.</p>'
            f'<div class="row">{demo_btns("features_foot")}<a class="btn ghost" href="/#pricing">See pricing</a></div></div></section>')
    return page("Features: every tool in BAP for real estate investors",
                f"{n} tools in one app: distress leads from {v['counties']} counties, skip tracing, calling, mail, deal analysis, lenders, contracts, a pipeline and more.",
                "/features/", body)


def guide_pages(feat, rows):
    """Plain-English how-to guides. Each one links to the tool pages it relates to and to the county index."""
    data = json.loads((ROOT / "data" / "guides.json").read_text(encoding="utf-8"))["guides"]
    tools = {t["slug"]: t for g in feat["groups"] for t in g["tools"] if t.get("slug")}
    pages = {}
    for g in data:
        secs = []
        for s in g["sections"]:
            inner = "".join(f"<p>{esc(x)}</p>" for x in s.get("p", []))
            if s.get("ul"):
                inner += "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in s["ul"]) + "</ul>"
            secs.append(f"<h2>{esc(s['h'])}</h2>{inner}")
        rel = []
        for sl in g["tools"]:
            if sl not in tools:
                die(f"guides.json: unknown tool slug {sl!r} in {g['slug']}")
            rel.append(f'<a href="/features/{sl}/">{esc(tools[sl]["detail"]["h1"])}</a>')
        rel.append('<a href="/leads/">Leads by county</a>')
        bc_ld, bc_html = crumbs([("Home", "/"), ("Guides", "/guides/"), (g["title"], f"/guides/{g['slug']}/")])
        art = {"@context": "https://schema.org", "@type": "Article", "headline": g["title"], "datePublished": g["published"],
               "dateModified": g["published"], "author": {"@type": "Organization", "name": "BAP"},
               "publisher": {"@type": "Organization", "name": "BAP", "logo": {"@type": "ImageObject", "url": SITE + "/icon-192.png"}},
               "mainEntityOfPage": f"{SITE}/guides/{g['slug']}/", "image": SITE + "/og-image.png"}
        utm = f"{APP}/?utm_source=seo&utm_medium=organic&utm_campaign=guide&utm_content={g['slug']}"
        body = (f'<div class="wrap hero">{bc_html}<h1>{esc(g["title"])}</h1><p>{esc(g["intro"])}</p></div>'
                f'<section><div class="wrap" style="max-width:760px"><div class="prose">{"".join(secs)}</div>'
                f'<div class="row"><a class="btn" href="{utm}#demo" data-ev="try_demo">Try BAP free in the demo</a></div>'
                f'<p class="small" style="margin-top:14px">General information, not legal, tax or financial advice. Rules vary by state; check yours.</p></div></section>'
                f'<section class="soft"><div class="wrap"><h2>Related tools</h2><div class="ql">{"".join(rel)}</div></div></section>')
        pages[g["slug"]] = page(f'{g["title"]} · BAP', g["desc"], f"/guides/{g['slug']}/", body, [bc_ld, art])
    cards = "".join(f'<div class="card"><h3><a href="/guides/{g["slug"]}/" style="text-decoration:none">{esc(g["title"])}</a></h3><p>{esc(g["desc"])}</p></div>' for g in data)
    bc_ld, _ = crumbs([("Home", "/"), ("Guides", "/guides/")])
    index = page("Real estate investing guides · BAP", "Plain-English guides on finding distressed properties, skip tracing, deal math, direct mail and more.",
                 "/guides/", f'<div class="wrap hero"><h1>Real estate investing guides</h1><p>Plain-English how-tos on finding distressed properties, reaching owners and running the numbers.</p></div>'
                 f'<section class="soft"><div class="wrap"><div class="grid">{cards}</div></div></section>', [bc_ld])
    return pages, index, data


def get_page():
    """What the printed QR code opens: an instant hand-off to the app's own full-screen install screen. Phones only, no page to read.
    (Installing must happen on the app's own address, so this page only counts the scan and forwards.)"""
    dest = f"{APP}/?install=1&utm_source=qr&utm_medium=street&utm_campaign=get"
    d = esc(dest, quote=True)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>BAP</title><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="2;url={d}">'
            '<script async src="https://www.googletagmanager.com/gtag/js?id=G-NW1CM3V8C2"></script>'
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-NW1CM3V8C2',{anonymize_ip:true});"
            f"gtag('event','qr_scan',{{qr_code:'get'}});setTimeout(function(){{location.replace({json.dumps(dest)})}},350);</script>"
            '<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1D3557;color:#fff;font:17px system-ui,sans-serif;text-align:center}a{color:#F4A261}</style></head>'
            f'<body><p>Opening BAP…<br><a href="{d}">Tap here if nothing happens</a></p></body></html>')


def tool_pages(feat, v):
    """One page per major tool, so each part of the app can rank for what people search for it, not just the homepage."""
    labels = feat["status_labels"]
    pages, slugs = {}, []
    for g in feat["groups"]:
        siblings = [t for t in g["tools"] if t.get("slug")]
        for t in siblings:
            d = t["detail"]
            slug = t["slug"]
            slugs.append(slug)
            steps = "".join(f'<div class="card"><h3>{i}.</h3><p>{esc(s)}</p></div>' for i, s in enumerate(d["steps"], 1))
            good = "".join(f"<li>{esc(x)}</li>" for x in d["good"])
            keep = "".join(f"<li>{esc(x)}</li>" for x in d["keep"])
            related = "".join(f'<a href="/features/{o["slug"]}/">{esc(o["detail"]["h1"])}</a>' for o in siblings if o is not t)
            related += f'<a href="/features/#{g["id"]}">All {esc(g["title"]).lower()} tools</a>'
            bc_ld, bc_html = crumbs([("Home", "/"), ("Features", "/features/"), (d["h1"], f"/features/{slug}/")])
            utm = f"{APP}/?utm_source=seo&utm_medium=organic&utm_campaign=feature&utm_content={slug}"
            body = (f'<div class="wrap hero">{bc_html}<h1>{esc(d["h1"])}</h1><p>{esc(d["intro"])}</p>'
                    f'<p><span class="tag {t["status"]}">{esc(labels[t["status"]])}</span> <span class="small">{esc(t["text"])}</span></p>'
                    f'<div class="row"><a class="btn" href="{utm}#demo" data-ev="try_demo">Try it in the free demo</a>'
                    f'<a class="btn ghost" href="{utm}" data-ev="open_app">Open BAP</a></div></div>'
                    f'<section class="soft"><div class="wrap"><h2>How it works</h2><div class="grid">{steps}</div></div></section>'
                    f'<section><div class="wrap"><div class="grid"><div class="card"><h3>Good for</h3><ul>{good}</ul></div>'
                    f'<div class="card"><h3>Keep in mind</h3><ul>{keep}</ul></div></div></div></section>'
                    f'<section class="soft"><div class="wrap"><h2>More of what BAP does</h2><div class="ql">{related}'
                    f'<a href="/features/">Everything BAP does</a><a href="/leads/">Leads by county</a></div></div></section>')
            desc = d["intro"].split(". ")[0].rstrip(".") + ". Part of the BAP real estate investor app."
            pages[slug] = page(f'{d["h1"]} · BAP', desc[:300], f"/features/{slug}/", body, [bc_ld])
    return pages, slugs


# ---------------------------------------------------------------- homepage


# An illustration of the app with made-up sample data. It is deliberately NOT a screenshot: the demo shows real leads,
# and real owner names must never be published. Every value here is fictional.
PRODUCT_MOCK = (
    '<figure class="mock" aria-label="Illustration of a BAP lead and deal summary, using sample data">'
    '<div class="mcard"><div class="mhead"><b>1234 Example Ave</b><span class="mscore">Score 82</span></div>'
    '<div class="mchips"><span>Tax delinquent</span><span>Absentee owner</span><span>Vacant</span></div>'
    '<div class="mrows"><div><span>Taxes owed</span><b>$8,420</b></div><div><span>Years behind</span><b>3</b></div>'
    '<div><span>Est. value</span><b>$186,000</b></div></div></div>'
    '<div class="mcard"><div class="mhead"><b>Deal summary</b><span class="mtag">AI-assisted</span></div>'
    '<div class="mrows"><div><span>Est. repairs</span><b>$24,000</b></div><div><span>Suggested max offer</span><b>$106,000</b></div>'
    '<div><span>Key date</span><b>Tax sale in 45 days</b></div></div></div>'
    '<div class="mcard mtoday"><b>Today</b><span>3 follow-ups due</span><span>2 replies waiting</span></div>'
    '<figcaption>Illustration with sample data. Not a real property or person. Estimates only.</figcaption></figure>')

def homepage(feat, stats, v):
    cards = []
    for g in feat["groups"]:
        names = "".join((f"<li><a href=\"/features/{t['slug']}/\">{esc(t['name'])}</a></li>" if t.get("slug") else f"<li>{esc(t['name'])}</li>")
                        for t in g["tools"][:4])
        more = f"<li>and {len(g['tools']) - 4} more</li>" if len(g["tools"]) > 4 else ""
        cards.append(f'<div class="card"><h3>{esc(g["title"])}</h3><p>{esc(g["blurb"])}</p><ul>{names}{more}</ul>'
                     f'<a class="more" href="/features/#{g["id"]}">See these tools →</a></div>')
    t = stats["totals"]
    strip = "".join(f'<div class="stat"><b>{n}</b><span>{lbl}</span></div>' for n, lbl in [
        (v["properties_fmt"], "properties tracked"), (v["counties"], "counties"), (v["states"], "states"),
        (v["lenders_and_contractors_fmt"], "lenders and contractors"), (v["deals_for_sale_fmt"], "deals for sale")])
    updated = fmt_date(stats.get("updated_at"))
    jsonld = [
        {"@context": "https://schema.org", "@type": "Organization", "name": "BAP", "legalName": "Apex Care Solutions VA LLC",
         "url": SITE + "/", "logo": SITE + "/icon-192.png", "telephone": "+1-469-224-1122",
         "address": {"@type": "PostalAddress", "streetAddress": "5245 Cleveland St, Ste 204", "addressLocality": "Virginia Beach",
                     "addressRegion": "VA", "postalCode": "23462", "addressCountry": "US"}},
        {"@context": "https://schema.org", "@type": "SoftwareApplication", "name": "BAP", "applicationCategory": "BusinessApplication",
         "operatingSystem": "Web, iOS, Android", "url": APP + "/",
         "description": "Distress leads from public records, a CRM, deal analysis, contracts, lenders, contractors and buyers for real estate investors.",
         "offers": [{"@type": "Offer", "name": p["name"], "price": str(p["monthly"]), "priceCurrency": "USD",
                     "priceSpecification": {"@type": "UnitPriceSpecification", "price": str(p["monthly"]), "priceCurrency": "USD", "billingDuration": "P1M"}}
                    for p in stats["plans"]]}]
    body = f'''<div class="wrap hero"><div class="herogrid"><div><h1>Find distressed properties, run the numbers, and close.</h1>
<p>BAP is the all-in-one app for real estate investors: distress leads from county and city records, a CRM, deal analysis, contracts, and the lenders, contractors and buyers to finish the deal.</p>
<div class="row">{demo_btns("hero")}</div>
<p class="small" style="margin-top:14px">Selling a house? <a href="/cash-offer/">Get a cash offer</a>. See <a href="/features/">everything BAP does</a> or read the <a href="/guides/">investing guides</a>.</p></div>{PRODUCT_MOCK}</div>
<div class="stats">{strip}</div><p class="small" style="margin-top:8px">Counts as of {updated}.</p></div>
<section class="soft"><div class="wrap"><h2>What BAP does</h2><div class="grid">{"".join(cards)}</div><div class="row"><a class="btn ghost" href="/features/">See every tool</a></div></div></section>
<section><div class="wrap"><h2>How it works</h2><div class="grid">
<div class="card"><h3>1. Find</h3><p>Pick a market on the map and filter for the distress you want.</p></div>
<div class="card"><h3>2. Reach</h3><p>Skip trace the owner, then call, text and mail them, and track it all in your pipeline.</p></div>
<div class="card"><h3>3. Run the numbers</h3><p>Get estimated value, rent and repairs plus an AI analysis before you make an offer.</p></div>
<div class="card"><h3>4. Close</h3><p>Fill in a contract and e-sign it, line up funding and send the deal to buyers.</p></div>
</div></div></section>
<section class="soft" id="pricing"><div class="wrap"><h2>Pricing</h2><div id="ll" class="card" style="display:none;border:2px solid var(--accent);margin-top:12px" role="status"><h3>Launch Lock: <span id="ll-n">100</span> of 100 spots left</h3><p>The first 100 members to join any paid plan by Dec 2 keep that price for as long as they stay subscribed, plus a free $20 credit pack.</p></div><div class="grid">{pricing_cards(stats, v)}</div>
<p class="small" style="margin-top:10px">{pricing_note(v)}</p><div class="row"><a class="btn" href="{APP}/" data-ev="open_app">Start with BAP</a></div></div></section>
<section id="deal-desk"><div class="wrap"><h2>Deal desk</h2><p class="small">Have a property under contract or a deal to sell or fund? Send it over and we’ll reply within one business day.</p>
<form onsubmit="return submitLead(this,'deal')"><input class="hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<div class="two"><label>Your name<input name="name" autocomplete="name" required></label><label>Phone<input name="phone" type="tel" autocomplete="tel"></label></div>
<div class="two"><label>Email<input name="email" type="email" autocomplete="email"></label><label>I want to<select name="intent"><option>Sell this deal to buyers</option><option>Get funding</option><option>Get a second opinion</option></select></label></div>
<label>Property address<input name="address" autocomplete="street-address"></label>
<div class="two"><label>City<input name="city"></label><label>ZIP<input name="zip" inputmode="numeric" maxlength="5"></label></div>
<label>Notes (price, repairs, timeline)<textarea name="notes" rows="3"></textarea></label>
<label class="check"><input type="checkbox" name="consent" required> I agree that BAP may contact me by phone, text or email about this request. Consent is not a condition of any sale.</label><button class="btn" type="submit">Send to the deal desk</button><p class="msg" role="status"></p></form></div></section>
<section class="soft"><div class="wrap"><h2>Questions</h2>
<details><summary>Is there a free trial?</summary><p>Yes. Pro comes with a 7-day free trial, and the free plan lets you browse BAP's leads and unlock 10 a month. You can also explore the demo at app.buybap.com/#demo without an account.</p></details>
<details><summary>How many leads do I get?</summary><p>BAP's own leads are unlimited on every paid plan, subject to fair use: county records in {v["states"]} states, updated as each county publishes them. The monthly numbers on each plan are extra on-demand nationwide leads for counties BAP doesn't cover yet.</p></details>
<details><summary>Where does the lead data come from?</summary><p>Public county and city records (coverage varies by county): tax rolls, foreclosure notices, code enforcement and vacant-building lists. On-demand nationwide leads come from a national property-records provider. You can also bring your own lists and properties.</p></details>
<details><summary>Which states do the contracts cover?</summary><p>BAP has {v["texas_contract_templates"]} Texas-specific contract templates plus national forms, all with e-signing. More states are coming. Laws vary by state, so have your attorney review every contract before you use it.</p></details>
<details><summary>Can I cancel anytime?</summary><p>Yes, online in the app under Services → Manage billing. See the <a href="{APP}/refunds/">refund policy</a>.</p></details>
<details><summary>Is BAP on iPhone?</summary><p>Yes. Open app.buybap.com in Safari, tap Share, then Add to Home Screen, and BAP opens like an app.</p></details>
</div></section>'''
    script = f'''const SB_URL="{SB_URL}", SB_KEY="{SB_KEY}";
// Launch Lock counter: shows only while the offer is approved, open and has spots left
(async function(){{try{{const r=await fetch(SB_URL+'/rest/v1/rpc/launch_lock_status',{{method:'POST',headers:{{apikey:SB_KEY,'Content-Type':'application/json'}},body:'{{}}'}});if(!r.ok)return;const j=await r.json();if(!j||!j.live)return;document.getElementById('ll-n').textContent=j.spots_left;document.getElementById('ll').style.display='block';}}catch(e){{}}}})();
async function submitLead(form, kind, extra){{
  const msg=form.querySelector('.msg'); const fd=new FormData(form); const p={{form:kind, details:{{}}}};
  for(const [k,v] of fd.entries()){{ if(['name','phone','email','address','city','state','zip','website'].includes(k)) p[k]=String(v).trim(); else if(k==='consent') p.consent=true; else p.details[k]=String(v).trim(); }}
  Object.assign(p.details, extra||{{}}); p.details.page=location.pathname;
  if(!p.phone && !p.email){{ msg.className='msg err'; msg.textContent='Please add a phone number or email so we can reach you.'; return false; }}
  msg.className='msg'; msg.textContent='Sending…'; const b=form.querySelector('button[type=submit]'); if(b) b.disabled=true;
  try{{ const r=await fetch(SB_URL+'/rest/v1/rpc/submit_web_lead',{{method:'POST',headers:{{apikey:SB_KEY,'Content-Type':'application/json'}},body:JSON.stringify({{p}})}});
    if(!r.ok) throw new Error((await r.json().catch(()=>({{}}))).message||'HTTP '+r.status);
    msg.className='msg ok'; msg.textContent='Got it. We\\u2019ll reach out within one business day.'; form.reset();
    try{{gtag('event','generate_lead',{{form:kind}})}}catch(e){{}}
  }}catch(e){{ msg.className='msg err'; msg.textContent='Something went wrong: '+e.message+'. Please call 469-224-1122.'; }}
  if(b) b.disabled=false; return false;
}}
'''
    return page("BAP: real estate investor app for distress leads, deals and funding",
                f"BAP finds distressed properties from public records in {v['counties']} counties and helps investors analyze, fund and close deals. Try the free demo.",
                "/", body, jsonld, script)


# ---------------------------------------------------------------- county pages

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fmt_date(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%b %-d, %Y") if sys.platform != "win32" \
            else datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%b %d, %Y").replace(" 0", " ")
    except Exception:
        return date.today().strftime("%b %d, %Y")


SIGNALS = [("tax_delinquent", "tax-delinquent", "tax-delinquent properties"), ("pre_foreclosure", "pre-foreclosure", "in pre-foreclosure"),
           ("code_violation", "code violation", "with code violations"), ("vacant", "vacant", "flagged vacant"),
           ("tax_sale", "tax sale", "heading to a tax sale")]


def county_pages(conf, stats, feat, v):
    by_key = {(c["state"].strip(), c["county"]): c for c in stats["counties"]}
    rows = []
    for c in conf:
        s = by_key.get((c["state"], c["db_county"]))
        if s and s["properties"] >= MIN_COUNTY_PROPERTIES:
            rows.append({**c, **s})
    per_state = {}
    for r in rows:
        per_state.setdefault(r["state"], []).append(r)
    for lst in per_state.values():
        lst.sort(key=lambda r: -r["properties"])
    updated = fmt_date(stats.get("updated_at"))
    plans = stats["plans"]
    plan_line = ", ".join(f"{p['name']} {money(p['monthly'])}/month" + (" for 3 users" if p["seats"] > 1 else "") for p in plans)
    pages = {}
    for r in rows:
        sn = STATES.get(r["state"], r["state"])
        st_slug = slugify(sn)
        sig = [(label, r[k]) for k, label, _ in SIGNALS if r[k] > 0]
        phrases = [f"{n:,} {txt}" for (k, _, txt), n in ((x, r[x[0]]) for x in SIGNALS) if n > 0]
        top = sorted(((r[k], txt) for k, _, txt in SIGNALS if r[k] > 0), reverse=True)[:3]
        top_txt = ", ".join(f"{n:,} {t}" for n, t in top)
        rank = per_state[r["state"]].index(r) + 1
        metro = f" ({esc(r['metro'])} area)" if r.get("metro") else ""
        utm = f"{APP}/?utm_source=seo&utm_medium=organic&utm_campaign=county&utm_content={r['slug']}"
        stat_cards = [f'<div class="stat"><b>{r["properties"]:,}</b><span>properties tracked</span></div>']
        for k, label, txt in SIGNALS:
            if r[k] > 0:
                stat_cards.append(f'<div class="stat"><b>{r[k]:,}</b><span>{esc(txt)}</span></div>')
        if r["new_7d"] > 0:
            stat_cards.append(f'<div class="stat"><b>{r["new_7d"]:,}</b><span>added in the last 7 days</span></div>')
        others = [o for o in per_state[r["state"]] if o["slug"] != r["slug"]][:8]
        other_html = ""
        if others:
            links = "".join(f'<a href="/leads/{o["slug"]}/">{esc(o["name"])}</a>' for o in others)
            other_html = f'<section><div class="wrap"><h2>More {esc(sn)} counties</h2><div class="ql">{links}<a href="/leads/{st_slug}/">All {esc(sn)} counties</a></div></div></section>'
        n_st = len(per_state[r["state"]])
        rank_txt = (f"BAP tracks {n_st} {esc(sn)} counties with this much data; {esc(r['name'].split(',')[0])} ranks #{rank} by properties."
                    if n_st > 1 else f"It is the only {esc(sn)} county with its own page so far.")
        sig_sentence = (" That includes " + ", ".join(phrases[:4]) + "." if phrases else "")
        trail = [("Home", "/"), ("Leads by county", "/leads/")] + ([(sn, f"/leads/{st_slug}/")] if len(per_state[r["state"]]) > 1 else []) + [(r["name"], f"/leads/{r['slug']}/")]
        bc_ld, bc_html = crumbs(trail)
        body = f'''<div class="hero"><div class="wrap">{bc_html}<h1>Distressed property leads in {esc(r["name"])}</h1>
<p>BAP tracks up to {r["properties"]:,} properties in {esc(r["name"])}{metro} with distress signals from public county and city records.{esc(sig_sentence)} Each lead shows the signals behind it, so you can judge for yourself.</p>
<div class="row"><a class="btn" href="{utm}" data-ev="open_app">See {esc(r["name"].split(",")[0])} leads free</a><a class="btn ghost" href="{APP}/?utm_source=seo&utm_medium=county#demo" data-ev="try_demo">Try the demo</a></div>
<p class="small" style="margin-top:12px">Free plan, no card needed. Counts as of {updated}; records update as the county publishes them.</p></div></div>
<section class="soft"><div class="wrap"><h2>{esc(r["name"])} by the numbers</h2><div class="stats">{"".join(stat_cards)}</div>
<p class="small" style="margin-top:12px">{rank_txt} A property can carry more than one signal, so the counts above overlap.</p></div></section>
<section><div class="wrap"><h2>What you get for {esc(r["name"].split(",")[0])}</h2><div class="grid">
<div class="card"><h3>Ranked by motivation</h3><p>Scores are estimates that rise for signals like tax lawsuits, years behind on taxes, out-of-state owners, upcoming sale dates and long ownership, and fall for payment plans. Each lead shows its reasons. A high score doesn't mean an owner will sell.</p></div>
<div class="card"><h3>Reach the owner</h3><p>Owner names and mailing addresses are included where the county publishes them, and skip tracing can add owner phones and emails where available, with Do Not Call flags.</p></div>
<div class="card"><h3>Run the deal in one tap</h3><p>"Work this lead" pulls estimated value, rent and comps and writes a one-screen summary: estimated repairs, a suggested max offer and the key deadline. AI output can contain errors; decision support, not advice.</p></div>
<div class="card"><h3>Contracts and mail</h3><p>Fill-in contract templates with e-sign (have your attorney review), plus postcards from {v["price_postcard_low"]}.</p></div>
</div><p class="small" style="margin-top:14px">Want the whole toolkit? See <a href="/features/">everything BAP does</a>.</p></div></section>
<section class="soft"><div class="wrap"><h2>Plans</h2><p>Unlimited BAP leads on every paid plan: {esc(plan_line)}. Pro includes a 7-day free trial, then renews until you cancel. Unlimited means no monthly cap on BAP's own leads; each user can open up to 300 new leads a day.</p>
<div class="row"><a class="btn" href="{utm}" data-ev="open_app">Start free</a><a class="btn ghost" href="/leads/">Other counties</a></div>
<p class="small" style="margin-top:12px">Follow Do Not Call rules and your state's wholesaling and solicitation laws when you contact owners.</p></div></section>{other_html}'''
        title = f"{r['name']} distressed property leads · BAP"
        desc = (f"{r['properties']:,} properties tracked in {r['name']}" + (f": {top_txt}" if top_txt else "") + ". Free to browse. Start free.")
        pages[r["slug"]] = page(title, desc, f"/leads/{r['slug']}/", body, [bc_ld])
    # state hub pages: one per state that has 2+ county pages
    hub_slugs = []
    for st, lst in per_state.items():
        if len(lst) < 2:
            continue
        sn = STATES.get(st, st)
        slug = slugify(sn)
        hub_slugs.append(slug)
        tot = sum(r["properties"] for r in lst)
        sums = [(txt, sum(r[k] for r in lst)) for k, _, txt in SIGNALS]
        sums = [(t, n) for t, n in sums if n > 0]
        sig_line = ", ".join(f"{n:,} {t}" for t, n in sorted(sums, key=lambda x: -x[1])[:4])
        rows_html = "".join(
            f'<li><a href="/leads/{r["slug"]}/">{esc(r["name"])}</a> <span class="small">· {r["properties"]:,} properties'
            + (f", {r['new_7d']:,} new this week" if r["new_7d"] else "") + "</span></li>" for r in lst)
        bc_ld, bc_html = crumbs([("Home", "/"), ("Leads by county", "/leads/"), (sn, f"/leads/{slug}/")])
        hub_body = (f'<div class="hero"><div class="wrap">{bc_html}<h1>Distressed property leads in {esc(sn)}</h1>'
                    f'<p>BAP tracks up to {tot:,} properties across {len(lst)} {esc(sn)} counties from public county and city records. '
                    f'{esc("That includes " + sig_line + ".") if sig_line else ""} Counts as of {updated}.</p>'
                    f'<div class="row">{demo_btns("state")}</div></div></div>'
                    f'<section class="soft"><div class="wrap"><h2>{esc(sn)} counties on BAP</h2><ul class="statelist" style="columns:1">{rows_html}</ul>'
                    f'<p class="small" style="margin-top:14px">Signals vary by county, and a property can carry more than one. Other {esc(sn)} counties are covered by on-demand leads. <a href="/features/">See how</a>.</p></div></section>')
        pages[slug] = page(f"{sn} distressed property leads by county · BAP",
                           f"Distressed property leads in {len(lst)} {sn} counties: up to {tot:,} properties from public records. Free to browse.",
                           f"/leads/{slug}/", hub_body, [bc_ld])
    # index of counties
    by_state = {}
    for r in rows:
        by_state.setdefault(r["state"], []).append(r)
    items = []
    for st in sorted(by_state, key=lambda s: STATES.get(s, s)):
        lis = "".join(f'<li><a href="/leads/{r["slug"]}/">{esc(r["name"])}</a> <span class="small">· {r["properties"]:,} properties</span></li>'
                      for r in sorted(by_state[st], key=lambda r: r["name"]))
        hub = f'<a href="/leads/{slugify(STATES.get(st, st))}/">{esc(STATES.get(st, st))}</a>' if len(by_state[st]) > 1 else esc(STATES.get(st, st))
        items.append(f'<div class="card"><h3>{hub}</h3><ul class="statelist">{lis}</ul></div>')
    idx_body = (f'<div class="wrap hero"><h1>Distressed property leads by county</h1><p>BAP tracks {v["properties_fmt"]} properties in {v["counties"]} counties across {v["states"]} states. '
                f'These are the counties with the most data. Counts as of {updated}.</p><div class="row">{demo_btns("leads")}</div></div>'
                f'<section class="soft"><div class="wrap"><div class="grid">{"".join(items)}</div>'
                f'<p class="small" style="margin-top:14px">Don\'t see your county? BAP also finds on-demand pre-foreclosure, probate and tax-lien leads for any US county. <a href="/features/">See how</a>.</p></div></section>')
    bc_ld, _ = crumbs([("Home", "/"), ("Leads by county", "/leads/")])
    index = page("Distressed property leads by county · BAP",
                 f"Browse distressed property leads in {len(rows)} counties across {len({r['state'] for r in rows})} states, from public records. Free to browse.",
                 "/leads/", idx_body, [bc_ld])
    return pages, index, rows, hub_slugs


# ---------------------------------------------------------------- static pages

def patch_static(text, path):
    """Give the hand-written pages (cash-offer, funding, ...) the same head tags, blue accent and header as the generated ones."""
    if path == "404.html" and "<head>" not in text:
        return text  # a tiny redirect page: leave it alone
    # use the shared color tokens (same blue, grays and dark mode as the generated pages)
    shared = re.findall(r":root\{[^}]*\}", CSS)
    text = re.sub(r":root\{[^}]*\}", lambda _: shared[0], text, count=1)
    text = re.sub(r"@media \(prefers-color-scheme:dark\)\{:root\{[^}]*\}\}", lambda _: "@media (prefers-color-scheme:dark){" + shared[1] + "}", text, count=1)
    text = text.replace("#2f5bd3", "#0a66d9").replace("#7fa2ff", "#4da3ff")
    m = re.search(r"<title>(.*?)</title>", text, re.S)
    title = html.unescape(m.group(1)).strip() if m else "BAP"
    d = re.search(r'<meta name="description" content="(.*?)">', text, re.S)
    desc = html.unescape(d.group(1)) if d else "BAP: real estate investor app."
    is404 = path == "404.html"
    url_path = None if is404 else "/" + path.replace("index.html", "")
    # swap the head tags we own for the shared block, keep that page's own CSS and scripts
    css = re.search(r"<style>.*?</style>", text, re.S)
    css_html = css.group(0) if css else f"<style>{CSS}</style>"
    css_html = css_html.replace("#2f5bd3", "#0a66d9").replace("#7fa2ff", "#4da3ff")
    other_scripts = ""
    head = re.search(r"<head>(.*?)</head>", text, re.S)
    if head:
        for s in re.findall(r"<script(?![^>]*googletagmanager)[^>]*>.*?</script>", head.group(1), re.S):
            if "dataLayer" in s or "gtag('config'" in s:
                continue
            other_scripts += s
    new_head = head_tags(title, desc, url_path, noindex=is404) + "\n" + css_html + other_scripts
    text = re.sub(r"<head>.*?</head>", lambda _: "<head>\n" + new_head + "\n</head>", text, count=1, flags=re.S)
    if "<header>" in text:
        text = re.sub(r"<header>.*?</header>", lambda _: header_html(), text, count=1, flags=re.S)
    # bring the shared styles the new header needs (logo tile, mobile nav) into pages that carry their own CSS
    text = text.replace("</style>", CSS_HEADER_EXTRA + "</style>", 1)
    return text


CSS_HEADER_EXTRA = (".logo{display:flex;align-items:center;gap:9px}.logo img{width:30px;height:30px;border-radius:7px;display:block}"
                    "header .btn{padding:7px 13px;font-size:.92rem}"
                    "@media (max-width:760px){header nav{order:3;flex:1 0 100%;flex-wrap:nowrap;overflow-x:auto;padding:2px 0 10px;scrollbar-width:none}"
                    "header nav a{white-space:nowrap}.logo{margin-right:0}header .cta{margin-left:auto}}")


def copy_static():
    pages = []
    for p in ROOT.iterdir():
        if p.name in SKIP_TOP and not p.is_file():
            continue
        if p.is_file():
            if p.name in SKIP_FILES:
                continue
            shutil.copy2(p, DIST / p.name)
            if p.name.startswith("google") and p.suffix == ".html":
                continue  # Search Console ownership file: must stay byte-for-byte as Google issued it, and out of the sitemap
            if p.suffix == ".html":
                pages.append(p.name)
                (DIST / p.name).write_text(patch_static(p.read_text(encoding="utf-8"), p.name), encoding="utf-8")
        else:
            shutil.copytree(p, DIST / p.name)
            for f in (DIST / p.name).rglob("*.html"):
                rel = f.relative_to(DIST).as_posix()
                pages.append(rel)
                f.write_text(patch_static(f.read_text(encoding="utf-8"), rel), encoding="utf-8")
    return pages


# ---------------------------------------------------------------- main

def write(path, text):
    f = DIST / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def sanity(stats, v, rows):
    t = stats.get("totals") or {}
    if int(t.get("properties", 0)) < 500_000:
        die(f"properties total looks wrong: {t.get('properties')}")
    if int(t.get("counties", 0)) < 40:
        die(f"county total looks wrong: {t.get('counties')}")
    keys = {p["key"] for p in stats["plans"]}
    if not {"starter", "pro", "team"} <= keys:
        die(f"plans missing from site_stats(): have {sorted(keys)}")
    if len(rows) < 20:
        die(f"only {len(rows)} county pages qualified; expected 30+")
    for f in DIST.rglob("*"):
        if f.suffix in (".html", ".xml", ".txt"):
            s = f.read_text(encoding="utf-8")
            if re.search(r"\{\{\w+\}\}", s):
                die(f"unfilled placeholder in {f.relative_to(DIST)}")
            for bad in FORBIDDEN:
                if bad in s:
                    die(f"forbidden number {bad} in {f.relative_to(DIST)}")
    for name in ("index.html", "features/index.html", "leads/index.html", "og-image.png", "icon-192.png", "apple-touch-icon.png", "robots.txt", "sitemap.xml"):
        if not (DIST / name).exists():
            die(f"missing output {name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats-file", help="read numbers from this JSON file instead of the database")
    a = ap.parse_args()
    stats = json.loads(Path(a.stats_file).read_text(encoding="utf-8")) if a.stats_file else fetch_stats()
    if not stats.get("totals") or not stats.get("counties"):
        die("site_stats() returned no totals or counties (has refresh_site_stats() run?)")
    v = build_vars(stats)
    feat = load_features(v)
    conf = json.loads((ROOT / "data" / "counties.json").read_text(encoding="utf-8"))
    DIST.mkdir(exist_ok=True)
    for child in DIST.iterdir():  # empty it without removing the folder itself (a local preview server may be sitting in it)
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    static_pages = copy_static()
    write("index.html", homepage(feat, stats, v))
    write("features/index.html", features_page(feat, stats, v))
    cpages, cindex, rows, hubs = county_pages(conf, stats, feat, v)
    for slug, htm in cpages.items():
        write(f"leads/{slug}/index.html", htm)
    write("leads/index.html", cindex)
    # lastmod only where it is true: pages built from the database carry the date its numbers were last refreshed;
    # hand-written pages get none (a date that changes daily on every URL teaches Google to ignore lastmod entirely)
    data_date = str(stats.get("updated_at") or date.today().isoformat())[:10]
    generated = ["/", "/leads/"] + [f"/leads/{h}/" for h in hubs] + [f"/leads/{r['slug']}/" for r in rows]
    write("get/index.html", get_page())
    gpages, gindex, gdata = guide_pages(feat, rows)
    for slug, htm in gpages.items():
        write(f"guides/{slug}/index.html", htm)
    write("guides/index.html", gindex)
    tpages, tslugs = tool_pages(feat, v)
    for slug, htm in tpages.items():
        write(f"features/{slug}/index.html", htm)
    static = ["/features/", "/guides/"] + [f"/guides/{g['slug']}/" for g in gdata] + [f"/features/{s}/" for s in tslugs] + ["/" + p.replace("index.html", "") for p in static_pages if p != "404.html"]
    urls = generated + static
    lm = lambda u: f"<lastmod>{data_date}</lastmod>" if u in generated else ""
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
          "".join(f"<url><loc>{SITE}{u}</loc>{lm(u)}</url>\n" for u in dict.fromkeys(urls)) + "</urlset>\n")
    sanity(stats, v, rows)
    skipped = [c["slug"] for c in conf if c["slug"] not in {r["slug"] for r in rows}]
    print(f"OK: {len(rows)} county pages, {len(static_pages)} static pages, sitemap {len(set(urls))} urls")
    if skipped:
        print("no page (too little data or not in database yet):", ", ".join(skipped))


if __name__ == "__main__":
    main()
