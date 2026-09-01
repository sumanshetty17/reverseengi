# Website Reverse Engineering — SiteScope — Project Master Guide

> Motto: "Understand what the public web reveals — with evidence, transparency, and respect for boundaries."

## 1. Project Vision
Build a tool where a user enters a public website URL and receives an evidence-backed analysis of its publicly
observable implementation. The report covers identity, purpose, visible technologies, frontend code/resources,
assets, metadata, forms, links, third-party services, security headers, robots.txt, sitemap.xml and limitations.

## 2. Core Principle
The system distinguishes **OBSERVED** facts, **INFERRED** conclusions, **UNKNOWN** information and **NOT
APPLICABLE** fields. A public URL normally cannot reveal private backend source code, databases, credentials,
secret keys or protected APIs. The system never claims to have recovered information that was not publicly
delivered.

## 3. Main Features
URL validation; safe fetching; controlled crawling; HTML/CSS/JavaScript collection; asset inventory; technology
fingerprinting; purpose/audience/positioning analysis; explicit motto detection; SEO/Open Graph/Twitter metadata;
JSON-LD; forms; links/routes; third-party services; HTTP/security headers; robots.txt; sitemap.xml; HTML and JSON
reports; public-source inventory/bundle; evidence and confidence.

## 4. Architecture
Frontend → API → security/SSRF layer → fetcher/crawler → HTML/resource parser → technology fingerprint engine
→ purpose/inference engine → report generator → storage. Responsibilities are kept modular and testable
(`security.py`, `analyzer.py`, `reporting.py`, `main.py`).

## 5. Recommended Stack
First version (implemented): Python, FastAPI, HTTPX, BeautifulSoup/lxml and HTML/CSS/JavaScript.
Advanced version (roadmap): Playwright for browser rendering, PostgreSQL for persistent reports/jobs, Redis plus
a worker queue, object storage for artifacts, and authentication for multi-user deployment.

## 6. Data Model
Title, description, canonical URL, language, generator, Open Graph, Twitter cards, JSON-LD, public HTML/CSS/JS,
images/fonts/icons, framework clues, third-party SDKs, forms, internal/external links, status/content-type/server
headers, robots.txt and sitemap.xml. Each resource stores source URL, local filename, size and hash where
applicable.

## 7. Technology Detection
Multiple public signals are combined per finding (HTTP headers, path markers, DOM markers, generator meta,
known SDK URLs). Every detection carries a name, confidence and evidence list. High confidence never comes from
a single weak signal — corroborating signals raise confidence instead.

## 8. Purpose and Motto
Title, meta description, Open Graph text, headings, navigation labels and structured data are analyzed. An
explicit slogan element (class/id containing "tagline"/"slogan"/"motto") is marked OBSERVED. Otherwise the system
says no explicit motto was found and may offer an INFERRED positioning statement — it never fabricates an
official slogan.

## 9. Browser Rendering (Roadmap Phase 5)
Modern JavaScript applications may hide information from raw HTML. Playwright can be added later to render pages
in an isolated browser and inspect the post-render DOM, lazy-loaded assets, client-side routes, screenshots and
computed styles — without bypassing authentication, CAPTCHAs, paywalls or access controls.

## 10. Security
HTTP/HTTPS only. Localhost, loopback, private/internal, link-local, multicast, reserved and unspecified IPs are
blocked, including after DNS resolution. Redirect destinations are re-checked on every hop. Timeouts and
byte/asset/page/crawl limits are enforced and configurable. Credentials are never forwarded. Downloaded
JavaScript is never executed server-side. Cookies, Authorization headers and API keys are never exposed in
reports.

## 11. API
- `POST /api/analyze` `{url, max_assets}`
- `GET /api/report/{job_id}`
- `GET /api/report/{job_id}/json`
- `GET /api/report/{job_id}/html`
- `GET /api/report/{job_id}/bundle`

The JSON report is the canonical source for HTML rendering.

## 12. Code Foundation
FastAPI for the API; separate `analyzer.py`, `security.py` and `reporting.py` modules. The analyzer uses an async
HTTP client with manually re-validated redirects, a strict timeout and a descriptive User-Agent; parses HTML with
BeautifulSoup/lxml; resolves discovered resource URLs relative to the final page URL.

## 13. Suggested Structure
```
sitescope/
  app/main.py
  app/analyzer.py
  app/security.py
  app/reporting.py
  app/static/index.html
  reports/
  downloads/
  tests/
  requirements.txt
  README.md
  PROJECT_SPEC.md
```

## 14. Reports
Executive summary; target/final URL; timestamp; identity; purpose/audience/positioning; motto evidence;
technology stack with confidence/evidence; frontend architecture; HTML/CSS/JS inventory; public source inventory;
assets; forms; routes/links; third-party services; SEO; structured data; headers; robots/sitemap; performance and
accessibility observations; non-invasive security observations; unknown/private components; evidence; artifacts;
limitations.

## 15. Roadmap
- **Phase 1** — safe fetch and basic report. ✅ implemented
- **Phase 2** — fingerprints, metadata, assets, forms and links. ✅ implemented
- **Phase 3** — HTML/JSON reports and bundle. ✅ implemented
- **Phase 4** — robots/sitemap, headers and evidence model. ✅ implemented
- **Phase 5** — Playwright rendering. ⏳ not yet implemented
- **Phase 6** — controlled multi-page crawl and route map. ⏳ not yet implemented
- **Phase 7** — database, queue, accounts and history. ⏳ not yet implemented
- **Phase 8** — visual comparison, dependency/license analysis, explainable technology graphs. ⏳ not yet implemented

## 16. Testing
Valid HTTP/HTTPS, invalid URLs, redirects, private-target redirects, localhost, non-HTML responses, large
responses, broken assets, malformed JSON-LD, weak/strong fingerprints, missing mottos, bundle consistency and
absence of credentials/cookies/auth headers in reports are all covered in `tests/`.

## 17. Instructions for the Developer/AI Assistant
Read the complete specification before modifying the project. Preserve working functionality. Implement features
incrementally and test them. Keep security separate from crawling. Record evidence. Label inference. Never claim
private backend recovery. Keep secrets out of reports. Make limits configurable. Test SSRF, redirects, timeouts,
malformed resources and large responses. Before completion, compare the implementation against every requirement
in this guide.

## 18. Definition of Done
A user can enter a public URL, receive a reproducible report, inspect evidence for major conclusions, download a
public-resource inventory/bundle and clearly see what was not observable. Security boundaries and failure
handling are implemented, not merely documented.

## 19. Final Principle
The strongest version is an evidence-driven website intelligence and educational reverse-engineering platform —
not a fake complete source-code extractor. It explains why each conclusion was reached, shows public evidence,
provides publicly delivered resources and clearly identifies unknown information.
