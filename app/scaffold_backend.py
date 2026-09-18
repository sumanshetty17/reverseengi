"""
Generate a synthetic backend + mock data from frontend inference.
NOT the original private server — a deployable scaffold for 1:1 public clone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse


def _safe_name(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "item").strip()).strip("_").lower()
    return s or "item"


def build_mock_db(inference: Dict[str, Any], purpose: Dict[str, Any]) -> Dict[str, Any]:
    entities = list(inference.get("inferred_entities") or ["User", "Item"])
    domains = inference.get("inferred_data_domains") or []
    title = (purpose or {}).get("title") or "Cloned App"
    observed = inference.get("observed_from_frontend") or {}
    form_fields = observed.get("form_fields") or []
    api_paths = observed.get("api_paths") or []

    db: Dict[str, Any] = {
        "_meta": {
            "title": title,
            "note": "Synthetic DB shaped from observed frontend structures — not the original production database",
            "domains": domains,
            "observed_api_paths": api_paths[:30],
            "observed_form_fields": form_fields[:30],
            "next_data_keys": observed.get("next_data_keys") or [],
        },
        "users": [
            {"id": "u1", "name": "Demo User", "email": "demo@example.com", "role": "admin"},
            {"id": "u2", "name": "Team Member", "email": "member@example.com", "role": "member"},
        ],
        "workspaces": [
            {"id": "ws1", "name": "Demo Workspace", "plan": "beta"},
        ],
    }

    # Build a sample record from form field names (signup-like)
    if form_fields:
        sample = {"id": "form_sample_1"}
        for f in form_fields[:15]:
            fl = f.lower()
            if "email" in fl:
                sample[f] = "demo@example.com"
            elif "pass" in fl:
                sample[f] = "YOUR_PASSWORD_NOT_STORED"
            elif "name" in fl:
                sample[f] = "Demo Name"
            elif "phone" in fl:
                sample[f] = "+10000000000"
            else:
                sample[f] = f"sample_{_safe_name(f)}"
        db["form_submissions"] = [sample]

    low = " ".join(domains).lower() + " " + " ".join(str(e).lower() for e in entities)
    low += " " + " ".join(api_paths).lower()
    if "signal" in low or "feedback" in low:
        db["signals"] = [
            {"id": "s1", "source": "slack", "text": "Need CSV export", "score": 91},
            {"id": "s2", "source": "intercom", "text": "Bulk user management", "score": 78},
            {"id": "s3", "source": "linear", "text": "Slack notifications", "score": 65},
        ]
    if "opportunit" in low or "roadmap" in low or "backlog" in low:
        db["opportunities"] = [
            {"id": "o1", "title": "CSV export", "impact": 91, "status": "open"},
            {"id": "o2", "title": "Bulk user management", "impact": 78, "status": "open"},
            {"id": "o3", "title": "Mobile app", "impact": 54, "status": "backlog"},
        ]
    if "integration" in low:
        db["integrations"] = [
            {"id": "i1", "name": "Slack", "connected": True},
            {"id": "i2", "name": "Intercom", "connected": False},
            {"id": "i3", "name": "Linear", "connected": True},
        ]

    # One collection per observed API path segment
    for path in api_paths:
        parts = [p for p in path.split("/") if p and p not in ("api", "v1", "v2", "v3")]
        if not parts:
            continue
        coll = _safe_name(parts[-1])
        if coll not in db and not coll.endswith("}"):
            db[coll] = [{"id": f"{coll}_1", "path": path, "status": "active", "source": "observed_api_path"}]

    for ent in entities:
        key = _safe_name(ent) + "s"
        if key not in db:
            db[key] = [{"id": f"{_safe_name(ent)}_1", "name": f"Sample {ent}", "status": "active"}]

    # Attach shallow observed JSON samples for developers
    if observed.get("json_blobs"):
        db["_observed_json_samples"] = observed["json_blobs"][:8]

    return db



def generate_server_js(inference: Dict[str, Any], endpoints: List[Dict], original_url: str) -> str:
    ep_paths = []
    for e in endpoints or []:
        u = e.get("url") or ""
        path = urlparse(u).path if u.startswith("http") else u
        if path and path.startswith("/") and path not in ep_paths:
            ep_paths.append(path)
    for p in (
        "/api/health",
        "/api/me",
        "/api/workspaces",
        "/api/signals",
        "/api/opportunities",
        "/api/integrations",
    ):
        if p not in ep_paths:
            ep_paths.append(p)
    ep_paths = ep_paths[:50]
    ep_json = json.dumps(ep_paths, indent=2)

    return """/**
 * Scaffold backend for 1:1 public clone
 * Source site (reference only): %s
 *
 * Serves collected frontend + synthetic /api/*
 * NO private keys from the original site
 */
const path = require("path");
const fs = require("fs");
const express = require("express");

const app = express();
const PORT = process.env.PORT || 3000;
const ROOT = __dirname;
const pub = (...p) => path.join(ROOT, "public", ...p);

app.use(express.json());
app.use(express.static(ROOT, { extensions: ["html"] }));
app.use("/assets", express.static(pub("css")));
app.use("/assets", express.static(pub("js")));
app.use("/assets", express.static(pub("images")));
app.use("/assets", express.static(pub("fonts")));
app.use("/assets", express.static(pub("assets")));
app.use("/assets", express.static(pub()));
app.use("/css", express.static(pub("css")));
app.use("/js", express.static(pub("js")));
app.use("/images", express.static(pub("images")));
app.use("/fonts", express.static(pub("fonts")));
app.use("/public", express.static(pub()));
app.use("/_next/static/chunks", express.static(pub("js")));
app.use("/_next/static/css", express.static(pub("css")));
app.use("/_next/static/media", express.static(pub("fonts")));
app.use("/_next/static/media", express.static(pub("images")));

let db = { users: [], workspaces: [] };
try {
  db = JSON.parse(fs.readFileSync(path.join(ROOT, "backend", "data", "db.json"), "utf8"));
} catch (e) {
  console.warn("mock db missing", e.message);
}

app.get("/api/health", (_req, res) => {
  res.json({
    status: "ok",
    mode: "scaffold-clone",
    message: "Synthetic backend — not the original private server",
  });
});

app.get("/api/me", (_req, res) => {
  res.json({ user: (db.users && db.users[0]) || null, auth: "demo" });
});

app.get("/api/workspaces", (_req, res) => {
  res.json({ items: db.workspaces || [] });
});

app.get("/api/signals", (_req, res) => {
  res.json({ items: db.signals || [] });
});

app.get("/api/opportunities", (_req, res) => {
  res.json({ items: db.opportunities || [] });
});

app.get("/api/integrations", (_req, res) => {
  res.json({ items: db.integrations || [] });
});

const EXTRA = %s;
for (const p of EXTRA) {
  if (p.startsWith("/api/health")) continue;
  app.all(p, (req, res) => {
    res.json({
      ok: true,
      scaffold: true,
      path: p,
      method: req.method,
      message: "Synthetic response — replace with your own backend when ready",
    });
  });
}

app.get("*", (req, res, next) => {
  if (req.path.includes(".")) return next();
  const index = path.join(ROOT, "index.html");
  if (fs.existsSync(index)) return res.sendFile(index);
  res.status(404).send("Not found");
});

app.listen(PORT, "0.0.0.0", () => {
  console.log("1:1 scaffold clone listening on " + PORT);
});
""" % (original_url, ep_json)


def write_scaffold_backend(
    recon_root: Path,
    report: Dict[str, Any],
    original_url: str,
) -> None:
    inference = report.get("backend_inference") or {}
    purpose = report.get("purpose") or {}
    endpoints = report.get("api_endpoints") or []

    backend = recon_root / "backend"
    (backend / "data").mkdir(parents=True, exist_ok=True)
    (backend / "routes").mkdir(parents=True, exist_ok=True)

    db = build_mock_db(inference, purpose)
    (backend / "data" / "db.json").write_text(json.dumps(db, indent=2), encoding="utf-8")

    (backend / "README.md").write_text(
        (
            "# Scaffold backend (synthetic)\n\n"
            "Generated from public frontend analysis, not the original private servers.\n\n"
            f"Source reference: {original_url}\n\n"
            "## Contents\n"
            "- data/db.json — demo data from inferred entities/domains\n"
            "- API routes live in root server.js\n\n"
            "## Your keys\n"
            "Use root .env / .env.example. No private keys from the source site.\n"
        ),
        encoding="utf-8",
    )

    (recon_root / "server.js").write_text(
        generate_server_js(inference, endpoints, original_url),
        encoding="utf-8",
    )

    pkg_path = recon_root / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            pkg["description"] = (pkg.get("description") or "") + " [scaffold-clone]"
            pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")
        except Exception:
            pass
