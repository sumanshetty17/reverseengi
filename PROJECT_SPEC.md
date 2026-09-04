# PROJECT SPEC — Website Reverse Engineering

## Goal

Given a public website URL, produce:

1. Technical analysis report (technologies, pages, purpose, assets, APIs).
2. A **reconstruction ZIP** that is a complete project you can:
   - push to **GitHub**
   - deploy on **Render** as a **Node Web Service**
   - open and see the **same public pages and assets** that were collected

API keys and private backends are **not** scraped. They are exposed only as:
- stub API routes in `server.js`
- placeholders in `.env.example` for values **you** add yourself

## Reconstruction ZIP contents (required)

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
| `deployment/` | Missing-resource checklist |

## Deploy reconstructed site

```
Language: Node
Build: npm install
Start: npm start
```

## Platform (this repo)

Python FastAPI tool that performs analysis and builds the ZIP above.
