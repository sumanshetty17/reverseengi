# PROJECT SPEC — Website Reverse Engineering

This document mirrors the original technical implementation report.

## 1. Project Overview

Deep website reverse-engineering and reconstruction platform.  
User enters a URL → system analyzes, collects accessible code/resources, produces technical report + reconstructed project package.

## 2. Main Objectives

- Accept website URL as primary input
- Fetch & analyze available implementation
- Collect HTML, CSS, JS, JSON, source maps, templates
- Collect images, SVGs, icons, fonts, media
- Discover pages, routes, forms, client-visible APIs
- Analyze browser-rendered / dynamic content
- Identify technologies, frameworks, CMSs, libraries, CDNs
- Determine purpose, audience, positioning, motto/slogan
- Analyze accessible application data / authorized backend material
- Generate reports, source files, data files, assets
- Generate organized ZIP suitable for GitHub & deployment

## 3. Pipeline

```
Input URL
  → Fetch → Crawl → Render → Collect → Parse
  → Fingerprint → Analyze APIs/data → Map architecture
  → Reconstruct resources → Generate reports + ZIP
```

## 4–8. Collection Requirements

See original report for complete lists of:

- Code files (HTML/CSS/JS/JSON/source maps/…)
- Images & assets (PNG/JPG/WEBP/SVG/fonts/…)
- Exact resource placement (URL → local → referencing page)
- Website data (title, meta, forms, links, structured data, …)
- Backend information (only when authorized/supplied)

## 9. Browser Rendering

Playwright Chromium, `wait_until="networkidle"`, capture rendered DOM + network requests.

## 10–12. Architecture, Tech Detection, Purpose

- Architecture map of pages ↔ assets ↔ endpoints
- TECH_RULES with confidence + evidence
- Explicit motto when found; otherwise labelled inference

## 13–16. Reconstruction ZIP

Clean deployable structure, resource manifests with sha256, README, `.env.example` (names only).

## 17. Report Contents

Executive summary, purpose, tech stack, architecture, inventories, manifests, deployment instructions, missing resources, evidence.

## 18–19. API

```
POST /api/analyze
GET  /api/report/{job_id}
GET  /api/report/{job_id}/json
GET  /api/report/{job_id}/html
GET  /api/report/{job_id}/bundle
GET  /api/reconstruction/{job_id}/zip
```

FastAPI + Pydantic foundation as specified.

## 20. Folder Structure

Matches `website-reverse-engineering/` layout in README.

## 21–24. Roadmap, Instructions, Demo Goal, Expected Result

Implemented. Demonstration: enter URL → start analysis → view report & inventory → download reconstruction ZIP.
