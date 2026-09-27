# PROJECT SPEC — Website Reverse Engineering (Carbon upgrade)

## Goal

Given a public website URL, produce:

1. Technical analysis report (technologies, pages, purpose, assets, APIs, scroll gates).
2. A **reconstruction ZIP** you can push to GitHub and deploy on Render.

## Capture upgrades

- Detect and click scroll locks (“Scroll to explore”, cookie accept, etc.)
- Force `overflow: auto` when pages freeze the document
- Deep-scroll after unlock for lazy-loaded assets
- Record `gate_info` on browser results

## Reconstruction ZIP contents

| File / folder | Role |
|---------------|------|
| `index.html` + other `.html` | Public page snapshots |
| `public/` | CSS, JS, images, fonts |
| `server.js` | Express server (static + API stubs) |
| `package.json` | `npm install` / `npm start` |
| `render.yaml` | Render Node web service |
| `.env.example` | Optional env vars you fill in |
| `README.md` | Deploy instructions |
| `manifests/` | routes, resources, technologies |

## Platform (this repo)

Python FastAPI tool that performs analysis and builds the ZIP above.

Private API keys from the source site are never included.
