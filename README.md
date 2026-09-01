# SiteScope

Evidence-backed analysis of a public website's **publicly observable** implementation — identity, purpose,
technologies, frontend assets, forms, links, third-party services, security headers, robots.txt and sitemap.xml.

SiteScope is deliberately *not* a source-code extractor. It only ever reasons about bytes a normal,
unauthenticated visitor's browser would receive, and it labels every conclusion as **OBSERVED**, **INFERRED**,
**UNKNOWN**, or **NOT APPLICABLE** so you can see exactly how confident each claim is and why.

See [`PROJECT_SPEC.md`](./PROJECT_SPEC.md) for the full design spec this implementation follows, section by
section, including what's built (Phases 1–4) and what's future roadmap (Phases 5–8).

## Quick start

```bash
cd sitescope
python -m venv .venv && source .venv/bin/activate      # optional but recommended
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000** in a browser, enter a public URL, and click **Analyze**.

## API

| Method | Path                          | Description                                   |
|--------|-------------------------------|------------------------------------------------|
| POST   | `/api/analyze`                 | Body: `{"url": "...", "max_assets": 20}`. Returns `{job_id, status}`. |
| GET    | `/api/report/{job_id}`         | Job status (`running` / `done` / `failed`).    |
| GET    | `/api/report/{job_id}/json`    | Canonical JSON report.                         |
| GET    | `/api/report/{job_id}/html`    | Rendered HTML report.                          |
| GET    | `/api/report/{job_id}/bundle`  | Downloadable `.zip`: report.json + report.html + manifest.json + any downloaded public CSS/JS/HTML. |

Example:

```bash
curl -X POST localhost:8000/api/analyze -H "Content-Type: application/json" \
     -d '{"url": "https://example.com", "max_assets": 15}'
# => {"job_id": "a1b2c3...", "status": "running"}

curl localhost:8000/api/report/a1b2c3.../json | jq .
```

## Running the tests

```bash
pip install -r requirements.txt   # includes pytest, pytest-asyncio, respx
pytest -q
```

The suite runs fully offline: `respx` mocks the HTTP transport and `tests/conftest.py` mocks DNS resolution for
the fake `*.example` hostnames used in redirect tests, while real IP-literal safety checks (blocking `127.0.0.1`,
`169.254.169.254`, `10.0.0.0/8`, etc.) are still exercised for real. Coverage includes: valid/invalid URLs,
same-origin and cross-origin redirects, **redirects to private/loopback/metadata targets** (SSRF-via-redirect),
localhost, non-HTML responses, oversized responses (byte-cap truncation), broken/404 assets, malformed JSON-LD,
weak vs. strong technology fingerprints, missing/observed mottos, bundle contents, and confirmation that
`Authorization`/`Set-Cookie` values are never written into a report.

## Security model (Section 10 of the spec)

- Only `http://` and `https://` are accepted.
- Every hostname is resolved and every returned IP is checked against loopback, private, link-local, multicast,
  reserved, and unspecified ranges *before* a request is made — including cloud metadata endpoints like
  `169.254.169.254`.
- **Every redirect hop is re-validated the same way**, not just the original URL, so a public URL that 302s to an
  internal address is rejected mid-flight (`security.SecurityError`).
- Timeouts and byte/asset/page/crawl caps are enforced and configurable via `security.Limits`.
- Sensitive request headers (`Authorization`, `Cookie`, etc.) are never forwarded to the target.
- Sensitive response headers (`Set-Cookie`, `Authorization`, `WWW-Authenticate`, ...) are stripped before a report
  is built, with a second, independent redaction pass in `reporting.py` as defense-in-depth. Only the *names* of
  sensitive headers that were present are recorded, never their values.
- Downloaded JavaScript/CSS is stored as inert bytes and is **never executed**.

## What's implemented vs. roadmap

Implemented (Phases 1–4 of `PROJECT_SPEC.md`): safe single-page fetch with SSRF-guarded redirects, technology
fingerprinting with confidence/evidence, metadata/Open Graph/Twitter/JSON-LD extraction, motto/tagline detection,
forms, internal/external link extraction, asset inventory + bounded CSS/JS download, robots.txt and sitemap.xml
checks, non-invasive security header summary, JSON + HTML reports, and a downloadable bundle.

Not yet implemented (roadmap, see `PROJECT_SPEC.md` §15): Playwright-based post-render inspection (Phase 5),
controlled multi-page crawling with a route map (Phase 6), persistent storage via PostgreSQL/Redis/worker queue
and multi-user accounts (Phase 7), and visual comparison / dependency-license analysis / technology graphs
(Phase 8). Jobs currently live in an in-memory dict (`main.JOBS`) and are lost on restart — that's the intended
seam where Phase 7 plugs in without touching the API surface.

## Project layout

```
sitescope/
  app/
    main.py        # FastAPI app, job orchestration, API routes
    security.py     # SSRF guard, scheme validation, header scrubbing, configurable limits
    analyzer.py      # safe fetching, HTML parsing, fingerprinting, metadata/motto/forms/links extraction
    reporting.py     # canonical JSON shape, HTML rendering, zip bundle
    static/index.html  # minimal frontend
  reports/          # per-job report.json / report.html / bundle.zip (created at runtime)
  downloads/         # per-job downloaded public assets (created at runtime)
  tests/            # pytest suite (offline, mocked network/DNS)
  requirements.txt
  PROJECT_SPEC.md    # the full design spec this implementation follows
```
