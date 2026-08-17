#!/usr/bin/env python3
"""
prerender.py  --  Make the BASH Lab site readable by LLM agents, chatbots and crawlers.

The site fills its pages in the browser with JavaScript (fetching news.json,
team.json, the GitHub publications.bib, etc.).  Tools that do NOT run JavaScript
-- most LLM agents, chatbots and crawlers -- therefore see empty pages.

This script reads the same JSON / BibTeX data at build time and *bakes* the
rendered content straight into the static HTML, so the content is present in the
raw HTML before any JavaScript runs.  It also writes llms.txt, sitemap.xml and
robots.txt, and injects meta descriptions + schema.org JSON-LD into each page.

It is idempotent: every injected region is wrapped in
<!--PRERENDER:name--> ... <!--/PRERENDER:name--> markers and replaced on re-run.
Run it whenever the JSON data changes:   python3 prerender.py

Standard library only -- no dependencies, no Node required.
"""

import html
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://bashlab.github.io"
BIB_URL = "https://raw.githubusercontent.com/BASHLab/publications/main/publications.bib"

OFFLINE = "--offline" in sys.argv  # use the local publications.bib instead of fetching


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def esc(s):
    """HTML-escape a value coming from JSON."""
    return html.escape("" if s is None else str(s), quote=True)


def red(s):
    """Escape text, then turn [red]...[/red] markers into red spans (as the site does)."""
    s = html.escape("" if s is None else str(s), quote=False)
    return re.sub(r"\[red\](.*?)\[/red\]", r'<span class="red-text">\1</span>', s)


def plain(s):
    """Strip [red] markers, for plain-text output (llms.txt, JSON-LD)."""
    return re.sub(r"\[/?red\]", "", "" if s is None else str(s)).strip()


def read_json(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def read_file(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def write_file(name, content):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        f.write(content)


def watch_url(u):
    """Turn a youtube embed URL into a normal watch URL."""
    m = re.search(r"youtube\.com/embed/([\w-]+)", u or "")
    return "https://www.youtube.com/watch?v=" + m.group(1) if m else (u or "")


# --------------------------------------------------------------------------- #
# HTML injection (idempotent, marker-delimited)
# --------------------------------------------------------------------------- #
def inject_into(html_text, element_id, name, block):
    """Insert `block` right after the opening tag of the element with id=element_id."""
    wrapped = "\n<!--PRERENDER:%s-->\n%s\n<!--/PRERENDER:%s-->" % (name, block, name)
    # remove any previously injected block for this name (directly after the open tag)
    open_re = r'(<[a-zA-Z][^>]*\bid="%s"[^>]*>)' % re.escape(element_id)
    strip_re = re.compile(
        open_re + r"\s*<!--PRERENDER:%s-->.*?<!--/PRERENDER:%s-->" % (re.escape(name), re.escape(name)),
        re.DOTALL,
    )
    html_text = strip_re.sub(r"\1", html_text)
    new_text, n = re.subn(re.compile(open_re), lambda m: m.group(1) + wrapped, html_text, count=1)
    if n == 0:
        raise RuntimeError("could not find element id=%r" % element_id)
    return new_text


def inject_before(html_text, anchor, name, block):
    """Insert `block` immediately before the first occurrence of the literal `anchor`."""
    wrapped = "<!--PRERENDER:%s-->\n%s\n<!--/PRERENDER:%s-->\n" % (name, block, name)
    strip_re = re.compile(r"<!--PRERENDER:%s-->.*?<!--/PRERENDER:%s-->\s*" % (re.escape(name), re.escape(name)), re.DOTALL)
    html_text = strip_re.sub("", html_text)
    idx = html_text.find(anchor)
    if idx == -1:
        raise RuntimeError("could not find anchor %r" % anchor[:40])
    return html_text[:idx] + wrapped + html_text[idx:]


def inject_head(html_text, name, block):
    """Insert `block` just before </head>."""
    return inject_before(html_text, "</head>", name, block)


# --------------------------------------------------------------------------- #
# per-page content renderers  (mirror the client-side JS, using real links)
# --------------------------------------------------------------------------- #
def render_news(items):
    cards = []
    for it in items:
        img = esc(it.get("image", "./img/research_clusters/sensor.png"))
        inner = (
            '<div class="simple-card">'
            '<div class="card-image"><img src="%s" alt="%s"></div>'
            '<div class="card-body">'
            '<h3 class="card-title">%s</h3>'
            '<p class="card-description">%s</p>'
            '<div class="card-date">%s</div>'
            "</div></div>"
        ) % (img, esc(plain(it.get("title"))), red(it.get("title")), red(it.get("content")), esc(it.get("date")))
        url = it.get("url")
        if url and url != "#":
            inner = '<a href="%s" style="text-decoration:none;color:inherit;">%s</a>' % (esc(url), inner)
        cards.append('<div class="col-xs-12 col-sm-6 col-md-3">%s</div>' % inner)
    return '<div class="pr-fallback"><div class="row">%s</div></div>' % "".join(cards)


def render_research(areas):
    cols = []
    for a in areas:
        papers = "".join(
            '<li><a href="%s" target="_blank">%s</a></li>' % (esc(p.get("url")), esc(p.get("venue") or p.get("title")))
            for p in a.get("papers", [])
        )
        parts = [
            '<img src="%s" alt="%s" class="research-image">' % (esc(a.get("image")), esc(a.get("title"))),
            "<h3>%s</h3>" % esc(a.get("title")),
            "<p>%s</p>" % esc(a.get("description")),
        ]
        if a.get("funding"):
            parts.append("<p><strong>Funding:</strong> %s</p>" % esc(a["funding"]))
        parts.append("<p><strong>Papers:</strong></p><ul>%s</ul>" % papers)
        if a.get("datasets"):
            ds = "".join('<li><a href="%s" target="_blank">%s</a></li>' % (esc(d.get("url")), esc(d.get("name"))) for d in a["datasets"])
            parts.append("<p><strong>Datasets:</strong></p><ul>%s</ul>" % ds)
        if a.get("models"):
            ms = "".join('<li><a href="%s" target="_blank">%s</a></li>' % (esc(m.get("url")), esc(m.get("name"))) for m in a["models"])
            parts.append("<p><strong>Models:</strong></p><ul>%s</ul>" % ms)
        if a.get("learnMoreUrl"):
            parts.append('<p><a href="%s" target="_blank">Learn more</a></p>' % esc(a["learnMoreUrl"]))
        cols.append('<div class="col-xs-12 col-sm-12 col-md-4"><div class="research-area">%s</div></div>' % "".join(parts))
    return '<div class="pr-fallback"><div class="row">%s</div></div>' % "".join(cols)


def render_cards(items):
    """datasets / models: paired simple-cards."""
    cells = []
    for it in items:
        inner = (
            '<div class="simple-card"><div class="card-body">'
            '<h3 class="card-title">%s</h3><p class="card-description">%s</p>'
            "</div></div>"
        ) % (esc(it.get("title")), esc(it.get("description")))
        if it.get("url"):
            inner = '<a href="%s" target="_blank" style="text-decoration:none;color:inherit;">%s</a>' % (esc(it["url"]), inner)
        cells.append('<div class="col-xs-12 col-md-6">%s</div>' % inner)
    return '<div class="pr-fallback"><div class="row">%s</div></div>' % "".join(cells)


def render_videos(videos):
    cells = []
    for v in videos:
        inner = (
            '<div class="video-card"><div class="video-info">'
            '<h3 class="video-title"><a href="%s" target="_blank">%s</a></h3>'
            '<div class="video-meta"><span class="video-category">%s</span><span class="video-date">%s</span></div>'
            "</div></div>"
        ) % (esc(watch_url(v.get("url"))), esc(v.get("title")), esc(v.get("category")), esc(v.get("date")))
        cells.append('<div class="col-xs-12 col-md-6 col-lg-4">%s</div>' % inner)
    return '<div class="pr-fallback">%s</div>' % "".join(cells)


def render_members(members):
    cells = []
    for m in members:
        url = m.get("url") or "#"
        cells.append(
            '<div class="col-xs-12 col-md-3"><div id="profile">'
            '<a href="%s"><div class="portrait" style="background-image:url(\'img/portraits/%s\');"></div></a>'
            '<div class="portrait-title"><h4><a href="%s">%s</a></h4><h5>%s</h5></div>'
            "</div></div>" % (esc(url), esc(m.get("image")), esc(url), esc(m.get("name")), esc(m.get("title")))
        )
    return '<div class="pr-fallback"><div class="row">%s</div></div>' % "".join(cells)


def render_alumni(data):
    def section(title, alumni):
        if not alumni:
            return ""
        rows = "<br>".join(
            "%s, %s, %s &rarr; %s" % (esc(a.get("name")), esc(a.get("degree")), esc(a.get("graduationYear")), esc(a.get("currentPosition")))
            for a in alumni
        )
        return (
            '<div class="col-xs-12 col-md-12"><h2 class="section-heading">%s</h2></div>'
            '<div class="col-xs-12" style="font-size:1.1em;line-height:1.8;color:#444;margin-bottom:30px;">%s</div>'
        ) % (esc(title), rows)

    body = section("Undergraduate & Masters Alumni", data.get("undergraduateAlumni")) + section("Masters Alumni", data.get("mastersAlumni"))
    return '<div class="pr-fallback">%s</div>' % body if body else ""


def render_collaborators(collabs):
    cells = "".join(
        '<div class="col-xs-6 col-md-2"><img src="img/%s" alt="%s" class="collaborator-logo"></div>' % (esc(c.get("logo")), esc(c.get("name")))
        for c in collabs
    )
    return '<div class="pr-fallback">%s</div>' % cells


def render_grants(data):
    grants = data.get("grants", [])
    cells = []
    for g in grants:
        amount = g.get("amount") or ""
        total = ""
        mt = re.search(r"\(Total:\s*\$([\d.]+M?K?)\)", amount)
        if mt:
            total = '<div class="grant-total">Total: $%s</div>' % esc(mt.group(1))
            amount = re.sub(r"\s*\(Total:[^)]+\)", "", amount)
        role = '<div class="grant-role"><strong>Role:</strong> %s</div>' % esc(g["role"]) if g.get("role") else ""
        typ = '<div class="grant-agency"><strong>Type:</strong> %s</div>' % esc(g["type"]) if g.get("type") else ""
        desc = ""
        if g.get("description"):
            desc = '<p class="card-description">%s%s</p>' % (
                esc(g["description"]),
                "<br><br><strong>Lead PIs:</strong> " + esc(g["leadPIs"]) if g.get("leadPIs") else "",
            )
        elif g.get("leadPIs"):
            desc = '<p class="card-description"><strong>Lead PIs:</strong> %s</p>' % esc(g["leadPIs"])
        body = (
            '<div class="card-body">'
            '<div class="card-title"><span>%s</span><span class="grant-amount">%s</span></div>'
            "%s%s%s%s"
            '<div class="grant-duration">%s</div></div>'
        ) % (esc(g.get("title")), esc(amount), total, role, typ, desc, esc(g.get("duration")))
        cells.append('<div class="col-md-6" style="padding:8px;"><div class="simple-card" style="height:100%%;width:100%%;">%s</div></div>' % body)
    total_line = ""
    cd = data.get("chartData", {})
    if cd.get("total"):
        labels = cd.get("labels", [])
        vals = cd.get("datasets", [{}])[0].get("data", [])
        breakdown = ", ".join("%s: $%sK" % (esc(l), esc(v)) for l, v in zip(labels, vals))
        total_line = '<p style="font-size:1.1em;"><strong>Total funding: $%sK</strong> (%s)</p>' % (esc(cd["total"]), breakdown)
    return '<div class="pr-fallback">%s<div class="row">%s</div></div>' % (total_line, "".join(cells))


# --------------------------------------------------------------------------- #
# BibTeX parsing + publications rendering
# --------------------------------------------------------------------------- #
def clean_tex(v):
    v = v.replace("\n", " ")
    v = re.sub(r"\s+", " ", v).strip()
    v = v.replace("~", " ")
    v = v.replace("{\\%}", "%").replace("\\%", "%").replace("\\&", "&")
    v = v.replace("\\_", "_").replace("\\#", "#").replace("\\$", "$")
    v = re.sub(r"\\[`'^\"~=.]\{?([A-Za-z])\}?", r"\1", v)  # accents -> base letter
    v = re.sub(r"\\[A-Za-z]+", "", v)  # drop remaining latex commands
    v = v.replace("{", "").replace("}", "")
    v = v.replace("--", "\u2013")
    return v.strip().strip(",. ")


def format_authors(a):
    a = a.replace("\n", " ")
    out = []
    for p in re.split(r"\s+and\s+", a):
        p = p.strip().strip(",").replace("{", "").replace("}", "")
        if not p:
            continue
        if "," in p:
            last, first = p.split(",", 1)
            p = first.strip() + " " + last.strip()
        p = clean_tex(p)
        if p:
            out.append(p)
    return ", ".join(out)


def parse_bibtex(text):
    # drop full-line comments (% year separators etc.)
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("%"))
    entries = []
    i = 0
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        brace = text.find("{", at)
        if brace < 0:
            break
        etype = text[at + 1 : brace].strip().lower()
        depth, j = 0, brace
        while j < len(text):
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[brace + 1 : j]
        i = j + 1
        if etype in ("comment", "string", "preamble"):
            continue
        comma = body.find(",")
        if comma < 0:
            continue
        fields = {"__type__": etype}
        rest = body[comma + 1 :]
        pos = 0
        while pos < len(rest):
            eq = rest.find("=", pos)
            if eq < 0:
                break
            fname = rest[pos:eq].strip().strip(",").strip().lower()
            vpos = eq + 1
            while vpos < len(rest) and rest[vpos] in " \t\r\n":
                vpos += 1
            if vpos >= len(rest):
                break
            ch = rest[vpos]
            if ch == "{":
                d, k = 0, vpos
                while k < len(rest):
                    if rest[k] == "{":
                        d += 1
                    elif rest[k] == "}":
                        d -= 1
                        if d == 0:
                            break
                    k += 1
                val = rest[vpos + 1 : k]
                pos = k + 1
            elif ch == '"':
                k = vpos + 1
                while k < len(rest) and rest[k] != '"':
                    k += 1
                val = rest[vpos + 1 : k]
                pos = k + 1
            else:
                k = vpos
                while k < len(rest) and rest[k] not in ",\n":
                    k += 1
                val = rest[vpos:k]
                pos = k
            if fname:
                fields[fname] = val
            nc = rest.find(",", pos)
            pos = len(rest) if nc < 0 else nc + 1
        entries.append(fields)
    return entries


def render_publications(entries):
    by_year = {}
    for e in entries:
        year = clean_tex(e.get("year", "")) or "Other"
        by_year.setdefault(year, []).append(e)

    def year_key(y):
        m = re.search(r"\d{4}", y)
        return int(m.group()) if m else -1

    blocks = []
    for year in sorted(by_year, key=year_key, reverse=True):
        items = []
        for e in by_year[year]:
            title = clean_tex(e.get("title", ""))
            authors = format_authors(e.get("author", ""))
            venue = clean_tex(e.get("journal") or e.get("booktitle") or e.get("publisher") or "")
            url = clean_tex(e.get("url", ""))
            if not url and e.get("doi"):
                url = "https://doi.org/" + clean_tex(e["doi"])
            bits = ["<strong>%s</strong>" % esc(title)]
            if authors:
                bits.append(esc(authors))
            if venue:
                bits.append("<em>%s</em>" % esc(venue))
            line = ". ".join(bits) + (", %s." % esc(year) if year != "Other" else ".")
            if url:
                line += ' [<a href="%s" target="_blank">link</a>]' % esc(url)
            items.append("<li style='margin-bottom:10px;'>%s</li>" % line)
        blocks.append("<h3>%s</h3><ul>%s</ul>" % (esc(year), "".join(items)))
    return '<div id="pub-fallback" class="pr-fallback"><h2 class="section-heading">All Publications</h2>%s</div>' % "".join(blocks)


# --------------------------------------------------------------------------- #
# head metadata: description + JSON-LD
# --------------------------------------------------------------------------- #
ORG_JSONLD = {
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "BASH Lab (Bringing Awareness through Systems for Humans)",
    "alternateName": "BASH Lab",
    "url": BASE_URL,
    "logo": BASE_URL + "/img/header_white.png",
    "parentOrganization": {"@type": "CollegeOrUniversity", "name": "University of Massachusetts Amherst"},
    "sameAs": ["https://github.com/BASHLab", "https://huggingface.co/BASH-Lab", "https://www.youtube.com/@BASHLab_UMass"],
}


def head_block(description, extra_jsonld=None):
    graph = [ORG_JSONLD]
    if extra_jsonld:
        graph.extend(extra_jsonld)
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=2)
    return (
        '<meta name="description" content="%s">\n'
        '<meta property="og:title" content="BASH Lab">\n'
        '<meta property="og:description" content="%s">\n'
        '<meta property="og:type" content="website">\n'
        '<meta name="robots" content="index, follow">\n'
        '<script type="application/ld+json">\n%s\n</script>'
    ) % (esc(description), esc(description), ld)


# --------------------------------------------------------------------------- #
# llms.txt
# --------------------------------------------------------------------------- #
def build_llms_txt(news, research, datasets, media, team, funding, pubs):
    L = []
    L.append("# BASH Lab \u2014 Bringing Awareness through Systems for Humans")
    L.append("")
    L.append("> Research lab of Prof. Bashima Islam at the University of Massachusetts Amherst (UMass Amherst), "
             "building ubiquitous AI systems that learn from motion, audio, physiological and ambient "
             "sensor data to support human behavioral well-being. Focus areas: multimodal representation "
             "learning, sensor-grounded language models, and resource-constrained (edge / TinyML) inference.")
    L.append("")
    L.append("Site: %s" % BASE_URL)
    L.append("")

    L.append("## News")
    for n in news:
        line = "- %s \u2014 %s: %s" % (plain(n.get("date")), plain(n.get("title")), plain(n.get("content")))
        if n.get("url") and n["url"] != "#":
            line += " (%s)" % n["url"]
        L.append(line)
    L.append("")

    L.append("## Research Areas")
    for a in research.get("researchAreas", []):
        L.append("### %s" % plain(a.get("title")))
        L.append(plain(a.get("description")))
        if a.get("funding"):
            L.append("Funding: %s" % plain(a["funding"]))
        if a.get("papers"):
            L.append("Papers: " + ", ".join("%s (%s)" % (plain(p.get("title")), plain(p.get("venue"))) for p in a["papers"]))
        if a.get("learnMoreUrl"):
            L.append("More: %s" % a["learnMoreUrl"])
        L.append("")

    L.append("## Datasets")
    for d in datasets.get("datasets", []):
        L.append("- %s: %s (%s)" % (plain(d.get("title")), plain(d.get("description")), d.get("url", "")))
    L.append("")
    L.append("## Models")
    for m in datasets.get("models", []):
        L.append("- %s: %s (%s)" % (plain(m.get("title")), plain(m.get("description")), m.get("url", "")))
    L.append("")

    L.append("## Team")
    for m in team.get("members", []):
        line = "- %s \u2014 %s" % (plain(m.get("name")), plain(m.get("title")))
        if m.get("url"):
            line += " (%s)" % m["url"]
        L.append(line)
    if team.get("undergraduateAlumni") or team.get("mastersAlumni"):
        L.append("")
        L.append("### Alumni")
        for a in (team.get("undergraduateAlumni") or []) + (team.get("mastersAlumni") or []):
            L.append("- %s, %s, %s \u2014 now: %s" % (plain(a.get("name")), plain(a.get("degree")), plain(a.get("graduationYear")), plain(a.get("currentPosition"))))
    if team.get("collaborators"):
        L.append("")
        L.append("Collaborating institutions: " + ", ".join(plain(c.get("name")) for c in team["collaborators"]))
    L.append("")

    L.append("## Funding")
    cd = funding.get("chartData", {})
    if cd.get("total"):
        L.append("Total funding: $%sK" % cd["total"])
    for g in funding.get("grants", []):
        L.append("- %s (%s), %s, role: %s, %s%s" % (
            plain(g.get("title")), plain(g.get("type")), plain(g.get("amount")),
            plain(g.get("role")), plain(g.get("duration")),
            ", Lead PIs: " + plain(g["leadPIs"]) if g.get("leadPIs") else ""))
    L.append("")

    L.append("## Media")
    for v in media.get("researchVideos", []) + media.get("studentProjectVideos", []):
        L.append("- %s (%s) \u2014 %s" % (plain(v.get("title")), plain(v.get("date")), watch_url(v.get("url"))))
    L.append("")

    L.append("## Publications")
    for e in pubs:
        title = clean_tex(e.get("title", ""))
        authors = format_authors(e.get("author", ""))
        venue = clean_tex(e.get("journal") or e.get("booktitle") or e.get("publisher") or "")
        year = clean_tex(e.get("year", ""))
        url = clean_tex(e.get("url", "")) or ("https://doi.org/" + clean_tex(e["doi"]) if e.get("doi") else "")
        L.append("- %s. %s. %s %s%s" % (title, authors, venue, year, " " + url if url else ""))
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def get_bib():
    if not OFFLINE:
        try:
            print("Fetching latest publications.bib ...")
            req = urllib.request.Request(BIB_URL, headers={"User-Agent": "bashlab-prerender"})
            data = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
            write_file("publications.bib", data)
            return data
        except Exception as e:  # noqa
            print("  ! fetch failed (%s); using local publications.bib" % e)
    return read_file("publications.bib")


def main():
    news = read_json("news.json")
    research = read_json("research.json")
    datasets = read_json("datasets.json")
    media = read_json("media.json")
    team = read_json("team.json")
    funding = read_json("funding.json")
    pubs = parse_bibtex(get_bib())
    print("Parsed %d publications." % len(pubs))

    # ---- index.html ----
    h = read_file("index.html")
    h = inject_into(h, "news-grid", "news", render_news(news))
    news_ld = {"@context": "https://schema.org", "@type": "ItemList",
               "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                    "item": {"@type": "NewsArticle", "headline": plain(n.get("title")),
                                             "datePublished": plain(n.get("date")), "url": n.get("url", BASE_URL)}}
                                   for i, n in enumerate(news)]}
    h = inject_head(h, "head", head_block(
        "BASH Lab at UMass Amherst (Prof. Bashima Islam): ubiquitous AI for multimodal sensing \u2014 "
        "audio/IMU/physiological signals, sensor-grounded language models, and low-power edge ML for human well-being.",
        [news_ld]))
    write_file("index.html", h)

    # ---- research.html ----
    h = read_file("research.html")
    h = inject_into(h, "research-areas-container", "research", render_research(research.get("researchAreas", [])))
    h = inject_head(h, "head", head_block(
        "Research at BASH Lab (UMass Amherst): sensor-language intelligence, low-power edge ML (TinyML), and AI for behavioral health."))
    write_file("research.html", h)

    # ---- datasets.html ----
    h = read_file("datasets.html")
    h = inject_into(h, "datasets-container", "datasets", render_cards(datasets.get("datasets", [])))
    h = inject_into(h, "models-container", "models", render_cards(datasets.get("models", [])))
    h = inject_head(h, "head", head_block(
        "Open datasets and models from BASH Lab (UMass Amherst): AVS-QA, SensorCaps, OpenSQA, RAVEN, LLaSA and more."))
    write_file("datasets.html", h)

    # ---- media.html ----
    h = read_file("media.html")
    h = inject_into(h, "research-videos-container", "researchvideos", render_videos(media.get("researchVideos", [])))
    h = inject_into(h, "student-videos-container", "studentvideos", render_videos(media.get("studentProjectVideos", [])))
    h = inject_head(h, "head", head_block("Research talks and student project videos from BASH Lab (UMass Amherst)."))
    write_file("media.html", h)

    # ---- team.html ----
    h = read_file("team.html")
    h = inject_into(h, "members-container", "members", render_members(team.get("members", [])))
    alumni_html = render_alumni(team)
    if alumni_html:
        h = inject_into(h, "alumni-container", "alumni", alumni_html)
    h = inject_into(h, "collaborator-logos-container", "collaborators", render_collaborators(team.get("collaborators", [])))
    people_ld = [{"@type": "Person", "name": plain(m.get("name")), "jobTitle": plain(m.get("title")),
                  "url": m.get("url") or BASE_URL, "worksFor": {"@type": "Organization", "name": "BASH Lab"}}
                 for m in team.get("members", [])]
    h = inject_head(h, "head", head_block("The BASH Lab team at UMass Amherst, led by Prof. Bashima Islam.", people_ld))
    write_file("team.html", h)

    # ---- sponsors.html ----
    h = read_file("sponsors.html")
    h = inject_into(h, "grants-container", "grants", render_grants(funding))
    h = inject_head(h, "head", head_block("Research funding and sponsors supporting BASH Lab (UMass Amherst): NSF, NIH and gifts."))
    write_file("sponsors.html", h)

    # ---- publications.html ----
    h = read_file("publications.html")
    h = inject_before(h, '<div class="bibtex_structure">', "publications", render_publications(pubs))
    pub_ld = [{"@type": "ScholarlyArticle", "headline": clean_tex(e.get("title", "")),
               "author": format_authors(e.get("author", "")), "datePublished": clean_tex(e.get("year", "")),
               "url": clean_tex(e.get("url", ""))} for e in pubs[:25]]
    h = inject_head(h, "head", head_block("Publications from BASH Lab (UMass Amherst): multimodal sensing, sensor-language models and edge ML.", pub_ld))
    write_file("publications.html", h)

    # ---- llms.txt ----
    write_file("llms.txt", build_llms_txt(news, research, datasets, media, team, funding, pubs))

    # ---- sitemap.xml ----
    pages = ["index.html", "research.html", "publications.html", "datasets.html", "media.html", "team.html", "sponsors.html"]
    urls = "".join("  <url><loc>%s/%s</loc></url>\n" % (BASE_URL, p) for p in pages)
    write_file("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % urls)

    # ---- robots.txt ----
    write_file("robots.txt", "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % BASE_URL)

    print("Prerender complete: %d pages, llms.txt, sitemap.xml, robots.txt written." % len(pages))


if __name__ == "__main__":
    main()
