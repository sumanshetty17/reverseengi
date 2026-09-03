"""
Build a deployable reconstruction project ZIP.

Goal: unzip → push to GitHub → deploy on Render → same public website pages/assets.
Missing backends are stubbed; .env.example lists optional keys the user can add.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


def _served_path(local: str) -> str:
    local = local.replace("\\", "/")
    if local.startswith("public/"):
        return "/" + local[len("public/") :]
    if local.startswith("src/styles/"):
        return "/css/" + Path(local).name
    if local.startswith("src/scripts/"):
        return "/js/" + Path(local).name
    if local.startswith("src/"):
        return "/assets/" + Path(local).name
    return "/assets/" + Path(local).name


def rewrite_references(content: str, url_to_local: Dict[str, str], base_url: str = "") -> str:
    if not content or not url_to_local:
        return content
    origin = ""
    if base_url:
        p = urlparse(base_url)
        origin = f"{p.scheme}://{p.netloc}"
    replacements: List[tuple] = []
    for remote, local in url_to_local.items():
        local_href = _served_path(local)
        forms = {remote}
        if remote.startswith("https://"):
            forms.add(remote.replace("https://", "http://", 1))
            forms.add("//" + remote.split("://", 1)[-1])
        elif remote.startswith("http://"):
            forms.add(remote.replace("http://", "https://", 1))
            forms.add("//" + remote.split("://", 1)[-1])
        if origin and remote.startswith(origin):
            forms.add(remote[len(origin) :] or "/")
        for form in forms:
            if form and len(form) > 3:
                replacements.append((form, local_href))
    for remote, local_href in sorted(replacements, key=lambda x: -len(x[0])):
        content = content.replace(remote, local_href)
    return content


def rewrite_internal_links(html: str, routes: List[Dict[str, str]], origin: str) -> str:
    if not html or not routes:
        return html
    mapping: Dict[str, str] = {}
    for r in routes:
        u = r.get("url") or ""
        name = Path(r.get("local") or "").name
        if not u or not name:
            continue
        mapping[u] = name
        path = urlparse(u).path or "/"
        mapping[path] = name
        mapping[path.rstrip("/") or "/"] = name
        if origin and u.startswith(origin):
            mapping[u[len(origin) :] or "/"] = name
    for remote, name in sorted(mapping.items(), key=lambda x: -len(x[0])):
        if len(remote) < 1:
            continue
        for q in (f'href="{remote}"', f"href='{remote}'", f'href="{remote}/"', f"href='{remote}/'"):
            html = html.replace(q, f'href="{name}"')
    return html


def _page_filename(url: str, is_home: bool = False) -> str:
    if is_home:
        return "index.html"
    path = urlparse(url).path.strip("/") or "index"
    safe = re.sub(r"[^\w.\-/]", "_", path).replace("/", "_")
    if not safe.endswith(".html"):
        safe += ".html"
    return safe


def write_server_js(dest: Path, endpoints: List[Dict], original_url: str) -> None:
    stub_paths = []
    for e in endpoints or []:
        u = e.get("url") or ""
        path = urlparse(u).path if "://" in u else u
        if path and path.startswith("/") and path not in stub_paths:
            stub_paths.append(path)
    stub_paths = stub_paths[:40]
    stubs_js = json.dumps(stub_paths, indent=2)
    server = f"""/**
 * Reconstructed site server — source: {original_url}
 * Render: Build = npm install | Start = npm start
 */
const path = require("path");
const express = require("express");
const app = express();
const PORT = process.env.PORT || 3000;
const ROOT = __dirname;

app.use(express.json());
app.use(express.static(ROOT, {{ extensions: ["html"] }}));
app.use("/css", express.static(path.join(ROOT, "public", "css")));
app.use("/js", express.static(path.join(ROOT, "public", "js")));
app.use("/images", express.static(path.join(ROOT, "public", "images")));
app.use("/fonts", express.static(path.join(ROOT, "public", "fonts")));
app.use("/assets", express.static(path.join(ROOT, "public", "assets")));
app.use("/public", express.static(path.join(ROOT, "public")));

const STUB_PATHS = {stubs_js};
for (const p of STUB_PATHS) {{
  app.all(p, (req, res) => {{
    res.json({{
      ok: true,
      stub: true,
      path: p,
      message: "Placeholder API — add your own backend if needed.",
      method: req.method,
    }});
  }});
}}

app.get("/api/health", (_req, res) => res.json({{ status: "ok", reconstructed: true }}));

app.get("*", (req, res, next) => {{
  if (req.path.includes(".")) return next();
  res.sendFile(path.join(ROOT, "index.html"), (err) => {{
    if (err) res.status(404).send("Not found");
  }});
}});

app.listen(PORT, "0.0.0.0", () => {{
  console.log("Reconstructed site on port " + PORT);
}});
"""
    (dest / "server.js").write_text(server, encoding="utf-8")


def write_package_json(dest: Path, title: str) -> None:
    pkg = {
        "name": "reconstructed-site",
        "version": "1.0.0",
        "private": True,
        "description": f"Deployable reconstruction of {title}",
        "main": "server.js",
        "scripts": {"start": "node server.js", "serve": "node server.js"},
        "engines": {"node": ">=18"},
        "dependencies": {"express": "^4.21.0"},
    }
    (dest / "package.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")


def write_env_example(dest: Path, endpoints: List[Dict]) -> None:
    lines = [
        "# Optional — fill only if you connect your own services",
        "# No secrets were scraped from the original site.",
        "PORT=3000",
        "NODE_ENV=production",
        "",
        "# API_BASE_URL=https://your-backend.example.com",
        "# DATABASE_URL=",
    ]
    for e in (endpoints or [])[:15]:
        u = e.get("url") or ""
        if u:
            lines.append(f"# Discovered endpoint (stubbed): {u}")
    (dest / ".env.example").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_render_yaml(dest: Path) -> None:
    (dest / "render.yaml").write_text(
        """services:
  - type: web
    name: reconstructed-site
    runtime: node
    plan: free
    buildCommand: npm install
    startCommand: npm start
    envVars:
      - key: NODE_VERSION
        value: "20"
""",
        encoding="utf-8",
    )


def write_readme(dest: Path, report: Dict[str, Any], original_url: str) -> None:
    purpose = report.get("purpose") or {}
    techs = report.get("technologies") or []
    tech_list = ", ".join(t.get("name", "") for t in techs) or "Unknown"
    st = report.get("reconstruction_status") or {}
    readme = f"""# Reconstructed Website (deployable)

Auto-generated from: **`{original_url}`**

Push this folder to GitHub and deploy on **Render** to serve the collected public pages and assets.

## Deploy on Render

1. Upload **all files in this folder** to a GitHub repo (root must contain `package.json` + `server.js`).
2. Render → New → **Web Service** → connect repo.
3. Settings:

| Field | Value |
|-------|--------|
| Language | **Node** |
| Build Command | `npm install` |
| Start Command | `npm start` |

4. Open the Render URL.

## Local run

```bash
npm install
npm start
```

## Included

- HTML pages (public route snapshots)
- `public/` assets (css, js, images, fonts) when downloadable
- `server.js` — Express static server + API stubs
- `.env.example` — optional keys **you** add (nothing secret scraped)
- `render.yaml` — Render Blueprint

## Site summary

- **Title:** {purpose.get("title") or "N/A"}
- **Description:** {purpose.get("description") or "N/A"}
- **Technologies:** {tech_list}
- **Assets collected:** {st.get("assets_collected", 0)}

## Scope

Public frontend material only. Real booking/login/payment backends are **stubbed** until you wire your own services via `.env` / your API.
"""
    (dest / "README.md").write_text(readme, encoding="utf-8")


def write_deployment_md(dest: Path, missing: List[str], report: Dict) -> None:
    lines = [
        "# Deployment checklist",
        f"- Pages: {report.get('pages_crawled', 0)}",
        f"- Assets OK: {(report.get('reconstruction_status') or {}).get('assets_collected', 0)}",
        "",
        "## Missing remote resources",
    ]
    if missing:
        for m in missing[:40]:
            lines.append(f"- [ ] {m}")
    else:
        lines.append("- (none recorded)")
    (dest / "deployment" / "deployment.md").write_text("\n".join(lines), encoding="utf-8")


def build_reconstruction(
    job_dir: Path,
    report: Dict[str, Any],
    pages: Dict[str, Any],
    url_to_local: Dict[str, str],
    asset_manifest: List[Dict],
    original_url: str,
    downloads_dir: Optional[Path] = None,
) -> Path:
    recon_root = job_dir / "reconstructed-site"
    if recon_root.exists():
        shutil.rmtree(recon_root)

    for sub in (
        "public/images", "public/icons", "public/fonts", "public/css",
        "public/js", "public/assets", "public/data", "manifests", "reports", "deployment",
    ):
        (recon_root / sub).mkdir(parents=True, exist_ok=True)

    if downloads_dir and Path(downloads_dir).exists():
        for item in Path(downloads_dir).rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(downloads_dir).as_posix()
            if rel.startswith("public/"):
                target = recon_root / rel
            elif rel.endswith(".css") or "/css" in rel:
                target = recon_root / "public" / "css" / Path(rel).name
            elif rel.endswith((".js", ".mjs")) or "/js" in rel:
                target = recon_root / "public" / "js" / Path(rel).name
            elif any(rel.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif")):
                target = recon_root / "public" / "images" / Path(rel).name
            elif any(rel.lower().endswith(ext) for ext in (".woff", ".woff2", ".ttf", ".eot", ".otf")):
                target = recon_root / "public" / "fonts" / Path(rel).name
            else:
                target = recon_root / "public" / "assets" / Path(rel).name
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(item, target)
            except Exception:
                pass

    served_map = {remote: _served_path(local) for remote, local in url_to_local.items()}
    origin = f"{urlparse(original_url).scheme}://{urlparse(original_url).netloc}"

    routes: List[Dict[str, str]] = []
    page_items = list((pages or {}).items())
    used_names = set()

    for i, (url, pdata) in enumerate(page_items):
        html = pdata.get("rendered_html") or pdata.get("html") or ""
        if not html:
            continue
        is_home = i == 0 or urlparse(url).path in ("", "/")
        fname = _page_filename(url, is_home=is_home)
        if fname in used_names and not is_home:
            fname = _page_filename(url + f"_{i}", is_home=False)
        used_names.add(fname)
        rewritten = rewrite_references(html, served_map, base_url=url)
        (recon_root / fname).write_text(rewritten, encoding="utf-8")
        routes.append({"url": url, "local": fname})

    for r in routes:
        fpath = recon_root / r["local"]
        if fpath.exists():
            html = fpath.read_text(encoding="utf-8", errors="replace")
            html = rewrite_internal_links(html, routes, origin)
            fpath.write_text(html, encoding="utf-8")

    if not (recon_root / "index.html").exists() and routes:
        src = recon_root / routes[0]["local"]
        if src.exists():
            shutil.copy2(src, recon_root / "index.html")

    endpoints = (
        report.get("api_endpoints")
        or (report.get("backend_architecture") or {}).get("client_visible_endpoints")
        or []
    )

    (recon_root / "manifests" / "resources.json").write_text(
        json.dumps(asset_manifest, indent=2), encoding="utf-8"
    )
    (recon_root / "manifests" / "routes.json").write_text(
        json.dumps(routes, indent=2), encoding="utf-8"
    )
    (recon_root / "manifests" / "technologies.json").write_text(
        json.dumps(report.get("technologies") or [], indent=2), encoding="utf-8"
    )
    (recon_root / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "url": original_url,
                "purpose": report.get("purpose"),
                "technologies": report.get("technologies"),
                "pages_crawled": report.get("pages_crawled"),
                "reconstruction_status": report.get("reconstruction_status"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    write_readme(recon_root, report, original_url)
    write_package_json(recon_root, (report.get("purpose") or {}).get("title") or original_url)
    write_env_example(recon_root, endpoints)
    write_server_js(recon_root, endpoints, original_url)
    write_render_yaml(recon_root)
    missing = [a["original_url"] for a in asset_manifest if a.get("status") != "collected"]
    write_deployment_md(recon_root, missing, report)
    (recon_root / ".gitignore").write_text("node_modules/\n.env\n.DS_Store\n", encoding="utf-8")

    zip_path = job_dir / "reconstructed-site.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in recon_root.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(recon_root.parent))
    return zip_path
