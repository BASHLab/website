# BASH Lab website

Static site for [bashlab.wpi.edu](https://bashlab.wpi.edu).

## How content works (important)

You edit content in the **JSON files** and in the **publications repo**, not in the HTML:

| Content | Edit here |
|---|---|
| Home news cards | `news.json` |
| Research areas | `research.json` |
| Datasets & models | `datasets.json` |
| Media / videos | `media.json` |
| Team, alumni, collaborators | `team.json` |
| Funding / sponsors | `funding.json` |
| Publications | `publications.bib` in [`BASHLab/publications`](https://github.com/BASHLab/publications) |

The pages also load this data with JavaScript in the browser, so visitors always
see the latest data. **But JavaScript-only content is invisible to LLM agents,
chatbots and search crawlers** — they don't run JS, so they'd see empty pages.

## `prerender.py` — makes the site readable by LLMs & crawlers

`prerender.py` reads the same JSON/BibTeX data and **bakes the content directly
into the static HTML**, so it's present in the raw HTML before any JS runs. It also
generates `llms.txt`, `sitemap.xml`, `robots.txt`, and injects meta descriptions +
schema.org JSON-LD into every page.

- Pure Python standard library — **no dependencies, no Node required**.
- **Idempotent**: every injected block is wrapped in `<!--PRERENDER:name-->` markers
  and replaced on each run, so re-running never duplicates content.
- Browser visitors are unaffected: each page's JavaScript clears the baked
  fallback and re-renders the interactive version.

### Run it

```bash
python3 prerender.py            # fetches the latest publications.bib from GitHub
python3 prerender.py --offline  # uses the local publications.bib instead
```

Then commit the changed files.

## Automatic prerendering (GitHub Actions)

`.github/workflows/prerender.yml` runs `prerender.py` automatically:

- on every push to `main`,
- once a day (so new publications in the `.bib` repo get picked up), and
- on manual dispatch.

It commits the baked HTML back to the branch with a `[prerender]` marker in the
commit message (the workflow skips its own commits, so it never loops). Whatever
serves `main` to bashlab.wpi.edu then serves the baked HTML.

> If you have a separate deploy workflow, you can instead run `python3 prerender.py`
> as the step right before it uploads, and skip the auto-commit — either approach works.

## Local preview

```bash
python3 -m http.server 8000
# open http://localhost:8000
```
