#!/usr/bin/env python3
"""MVF Data Systems site tool. Plain HTML stays the source of truth.

  python3 tools/site.py build   Refresh shared blocks (header, footer, forms,
                                breadcrumbs, head tags) in every page, bump
                                asset versions, regenerate sitemap.xml.
  python3 tools/site.py check   Validate pages: links, titles, descriptions,
                                canonicals, H1s, alt text, JSON-LD, includes.
  python3 tools/site.py serve   Preview at http://localhost:8000

Shared blocks live in _partials/ and are placed in pages with markers:
  <!-- include:header -->...<!-- /include:header -->
  <!-- include:form practice=healthcare id=hc -->...<!-- /include:form -->
  <!-- include:breadcrumb -->...<!-- /include:breadcrumb -->
Edit the partial, run `build`, and every page is updated.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PARTIALS = ROOT / "_partials"
SITE = "https://www.mvfdatasystems.com"
SKIP_DIRS = {"_partials", "tools", "ads", "flyer-assets", ".venv", ".git", "node_modules", ".claude"}

# Breadcrumb labels by URL path.
CRUMBS = {
    "/": "Home",
    "/business-consulting/": "Business Consulting",
    "/business-consulting/operations-diagnostic/": "Business Systems Diagnostic",
    "/business-consulting/reporting-dashboards/": "Reporting & Business Intelligence",
    "/business-consulting/data-integration/": "Data Reconciliation & Integration",
    "/healthcare-consulting/": "Healthcare Consulting",
    "/healthcare-consulting/interoperability/": "Interoperability & Data Integration",
    "/healthcare-consulting/workflow-optimization/": "Clinical Workflow Optimization",
    "/about/": "About Marc Fertout",
    "/case-studies/": "Selected Projects",
    "/contact/": "Contact",
    "/privacy/": "Privacy Notice",
}

PHI_NOTE = (
    '<p class="phi-note"><strong>Please do not include patient information.</strong> '
    "This form is not a secure channel for protected health information (PHI). "
    "Describe the organizational or technical problem only.</p>"
)

FORM_PRESETS = {
    "business": dict(
        form_title="Request a free consultation",
        subject="Website inquiry: Business consulting",
        company_label="Company",
        placeholder="For example: our inventory system and accounting reports don't agree, and month-end reporting takes two weeks.",
        button="Send request",
        phi_note="",
    ),
    "healthcare": dict(
        form_title="Request a free consultation",
        subject="Website inquiry: Healthcare IT consulting",
        company_label="Organization",
        placeholder="For example: we need to plan an integration between our EHR and a care-coordination platform.",
        button="Send request",
        phi_note=PHI_NOTE,
    ),
    "general": dict(
        form_title="Describe your problem",
        subject="Website inquiry: General",
        company_label="Company or organization",
        placeholder="A few sentences about the systems, data, reporting or workflow problem you're dealing with.",
        button="Send request",
        phi_note=PHI_NOTE,
    ),
}

INCLUDE_RE = re.compile(
    r"(?P<open><!-- include:(?P<name>[\w-]+)(?P<attrs>[^>]*?) -->)(?P<body>.*?)(?P<close><!-- /include:(?P=name) -->)",
    re.S,
)


def pages() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*.html")):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in SKIP_DIRS:
            continue
        out.append(p)
    return out


def url_path(p: Path) -> str:
    rel = p.relative_to(ROOT).as_posix()
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def short_hash(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()[:8]


def parse_attrs(s: str) -> dict:
    return dict(re.findall(r"([\w-]+)=([^\s]+)", s))


def render(template: str, vars: dict) -> str:
    def sub(m):
        k = m.group(1)
        if k not in vars:
            raise KeyError(f"missing template var {k!r}")
        return vars[k]
    return re.sub(r"\{\{(\w+)\}\}", sub, template)


def breadcrumb_html(path: str) -> str:
    parts = [p for p in path.strip("/").split("/") if p]
    trail = ["/"]
    acc = "/"
    for part in parts:
        acc += part + "/"
        trail.append(acc)
    items_html = []
    ld_items = []
    for i, t in enumerate(trail, 1):
        name = CRUMBS.get(t)
        if name is None:
            raise KeyError(f"no breadcrumb label for {t}")
        esc = html.escape(name)
        if t == path:
            items_html.append(f'<li><span aria-current="page">{esc}</span></li>')
        else:
            items_html.append(f'<li><a href="{t}">{esc}</a></li>')
        ld_items.append({"@type": "ListItem", "position": i, "name": name, "item": SITE + t})
    ld = json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": ld_items}, ensure_ascii=False)
    return (
        '<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>' + "".join(items_html) + "</ol></nav>\n"
        f'      <script type="application/ld+json">{ld}</script>\n      '
    )


def build() -> int:
    versions = {
        "v_css": short_hash(ROOT / "css/style.css"),
        "v_js": short_hash(ROOT / "js/main.js"),
        "v_config": short_hash(ROOT / "js/site-config.js"),
    }
    partials = {p.stem: p.read_text() for p in PARTIALS.glob("*.html")}
    changed = 0
    for page in pages():
        src = page.read_text()
        path = url_path(page)
        section = path.strip("/").split("/")[0] if path != "/" else ""

        def repl(m):
            name = m.group("name")
            attrs = parse_attrs(m.group("attrs"))
            if name == "breadcrumb":
                body = breadcrumb_html(path)
            elif name == "form":
                practice = attrs.get("practice", "general")
                vars = dict(FORM_PRESETS[practice], practice=practice, id=attrs.get("id", practice + "-form"))
                body = render(partials["form"], vars)
            else:
                if name not in partials:
                    raise KeyError(f"{page}: unknown include {name!r}")
                body = render(partials[name], versions)
                if name == "header" and section:
                    body = body.replace(f'data-nav="{section}"', f'data-nav="{section}" aria-current="page"')
            return m.group("open") + "\n  " + body.rstrip() + "\n  " + m.group("close")

        out = INCLUDE_RE.sub(repl, src)
        if out != src:
            page.write_text(out)
            changed += 1
    write_sitemap()
    print(f"build: {changed} page(s) updated, sitemap.xml written")
    return 0


def write_sitemap():
    entries = []
    for page in pages():
        txt = page.read_text()
        if 'name="robots" content="noindex' in txt:
            continue
        m = re.search(r'<link rel="canonical" href="([^"]+)"', txt)
        if not m:
            continue
        entries.append(m.group(1))
    order = {p: i for i, p in enumerate(CRUMBS)}
    entries.sort(key=lambda u: order.get(u.replace(SITE, ""), 999))
    body = "\n".join(f"  <url>\n    <loc>{html.escape(u)}</loc>\n  </url>" for u in entries)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n"
    )


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta = {}
        self.links = []  # (tag, attr, value)
        self.canonical = None
        self.h = []
        self.imgs_missing_alt = []
        self.jsonld = []
        self._in_ld = False
        self._ld_buf = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and "name" in a:
            self.meta[a["name"]] = a.get("content", "")
        elif tag == "meta" and "property" in a:
            self.meta[a["property"]] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag in ("a", "link") and "href" in a:
            self.links.append((tag, a["href"]))
        elif tag in ("script", "img") and "src" in a:
            self.links.append((tag, a["src"]))
        if tag == "img" and "alt" not in a:
            self.imgs_missing_alt.append(a.get("src"))
        if tag in ("h1", "h2", "h3", "h4"):
            self.h.append(int(tag[1]))
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self._ld_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.jsonld.append("".join(self._ld_buf))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_ld:
            self._ld_buf.append(data)


def resolve_local(href: str, page: Path) -> Path | None:
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        if parts.netloc.endswith("mvfdatasystems.com"):
            href = parts.path or "/"
        else:
            return None
    else:
        href = parts.path
    if not href:
        return None
    if href.startswith("/"):
        target = ROOT / href.lstrip("/")
    else:
        target = (page.parent / href).resolve()
    if href.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def check() -> int:
    errors, warns = [], []
    titles, descs = {}, {}
    for page in pages():
        rel = page.relative_to(ROOT).as_posix()
        txt = page.read_text()
        p = PageParser()
        p.feed(txt)
        is_redirect = 'http-equiv="refresh"' in txt
        noindex = p.meta.get("robots", "").startswith("noindex")
        if "{{" in txt:
            errors.append(f"{rel}: unrendered template variable")
        for m in INCLUDE_RE.finditer(txt):
            if not m.group("body").strip():
                errors.append(f"{rel}: empty include {m.group('name')} (run build)")
        for tag, href in p.links:
            if href.startswith(("mailto:", "tel:", "#", "javascript:")):
                continue
            t = resolve_local(href, page)
            if t is not None and not t.exists():
                errors.append(f"{rel}: broken link {href}")
        for i in set(x for x in p.ids if p.ids.count(x) > 1):
            errors.append(f"{rel}: duplicate id {i}")
        for raw in p.jsonld:
            try:
                json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"{rel}: invalid JSON-LD ({e})")
        if is_redirect:
            continue
        title = p.title.strip()
        desc = p.meta.get("description", "")
        if not title:
            errors.append(f"{rel}: missing <title>")
        elif len(title) > 65:
            warns.append(f"{rel}: title is {len(title)} chars (may be truncated)")
        if not desc:
            errors.append(f"{rel}: missing meta description")
        elif not 70 <= len(desc) <= 165:
            warns.append(f"{rel}: meta description is {len(desc)} chars")
        titles.setdefault(title, []).append(rel)
        descs.setdefault(desc, []).append(rel)
        if p.h.count(1) != 1:
            errors.append(f"{rel}: expected exactly one <h1>, found {p.h.count(1)}")
        prev = 0
        for lvl in p.h:
            if prev and lvl > prev + 1:
                warns.append(f"{rel}: heading jumps from h{prev} to h{lvl}")
                break
            prev = lvl
        for src in p.imgs_missing_alt:
            errors.append(f"{rel}: <img src={src}> has no alt attribute")
        if not noindex:
            want = SITE + url_path(page)
            if p.canonical != want:
                errors.append(f"{rel}: canonical {p.canonical!r} != {want!r}")
            for k in ("og:title", "og:description", "og:url"):
                if k not in p.meta:
                    errors.append(f"{rel}: missing {k}")
    for t, ps in titles.items():
        if len(ps) > 1:
            errors.append(f"duplicate title {t!r}: {', '.join(ps)}")
    for d, ps in descs.items():
        if len(ps) > 1:
            errors.append(f"duplicate description on {', '.join(ps)}")
    for w in warns:
        print("warn: " + w)
    for e in errors:
        print("ERROR: " + e)
    print(f"check: {len(pages())} pages, {len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


def serve():
    import functools
    import http.server
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    print("Serving http://localhost:8000 (Ctrl+C to stop)")
    http.server.ThreadingHTTPServer(("127.0.0.1", 8000), handler).serve_forever()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "build":
        sys.exit(build())
    if cmd == "check":
        sys.exit(check())
    if cmd == "serve":
        serve()
    else:
        print(__doc__)
