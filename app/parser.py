"""
HTML / CSS / JS parsing utilities.
Extracts metadata, forms, links, scripts, styles, structured data, assets.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment


def parse_html(html: str, base_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")

    # --- Title & meta ---
    title = (soup.title.string or "").strip() if soup.title else ""
    metas: Dict[str, str] = {}
    for m in soup.find_all("meta"):
        name = m.get("name") or m.get("property") or m.get("http-equiv") or ""
        content = m.get("content") or ""
        if name and content:
            metas[name.lower()] = content.strip()

    description = metas.get("description") or metas.get("og:description") or ""
    keywords = metas.get("keywords", "")

    # Open Graph / Twitter
    og = {k: v for k, v in metas.items() if k.startswith("og:")}
    twitter = {k: v for k, v in metas.items() if k.startswith("twitter:")}

    # --- Headings ---
    headings = []
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            text = h.get_text(" ", strip=True)
            if text:
                headings.append({"level": level, "text": text[:300]})

    # --- Visible text sample ---
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    body_text = soup.get_text(" ", strip=True)
    # re-parse clean soup for further extraction
    soup = BeautifulSoup(html or "", "lxml")

    # --- Forms ---
    forms = []
    for form in soup.find_all("form"):
        fields = []
        for inp in form.find_all(["input", "select", "textarea"]):
            fields.append(
                {
                    "tag": inp.name,
                    "type": inp.get("type", "text" if inp.name == "input" else inp.name),
                    "name": inp.get("name"),
                    "id": inp.get("id"),
                    "placeholder": inp.get("placeholder"),
                    "required": inp.has_attr("required"),
                }
            )
        forms.append(
            {
                "action": urljoin(base_url, form.get("action") or ""),
                "method": (form.get("method") or "GET").upper(),
                "id": form.get("id"),
                "fields": fields,
            }
        )

    # --- Links ---
    internal: List[str] = []
    external: List[str] = []
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(base_url, href)
        if full.startswith(origin):
            internal.append(full)
        else:
            external.append(full)

    # --- Scripts ---
    scripts = []
    for s in soup.find_all("script"):
        src = s.get("src")
        if src:
            scripts.append({"type": "external", "url": urljoin(base_url, src), "async": s.has_attr("async")})
        else:
            content = (s.string or "")[:500]
            scripts.append({"type": "inline", "content_preview": content, "length": len(s.string or "")})

    # --- Stylesheets ---
    stylesheets = []
    for link in soup.find_all("link", rel=lambda x: x and "stylesheet" in x.lower()):
        href = link.get("href")
        if href:
            stylesheets.append(urljoin(base_url, href))
    for style in soup.find_all("style"):
        stylesheets.append({"type": "inline", "length": len(style.string or "")})

    # --- Images & assets from HTML (thorough) ---
    images = []
    seen_img = set()

    def add_img(u, alt=None, kind="image"):
        if not u or u.startswith("data:"):
            return
        full = urljoin(base_url, u.strip())
        if full not in seen_img:
            seen_img.add(full)
            images.append({"url": full, "alt": alt, "type": kind})

    for img in soup.find_all(["img", "source", "video", "audio"]):
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "poster"):
            if img.get(attr):
                add_img(img.get(attr), img.get("alt"), img.name)
        # srcset: "url 1x, url2 2x"
        for attr in ("srcset", "data-srcset"):
            ss = img.get(attr) or ""
            for part in ss.split(","):
                part = part.strip().split(" ")[0].strip()
                if part:
                    add_img(part, img.get("alt"), "srcset")

    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") if isinstance(link.get("rel"), list) else [link.get("rel") or ""]).lower()
        href = link.get("href")
        as_attr = (link.get("as") or "").lower()
        if "icon" in rel or as_attr in ("image", "font", "style", "script") or rel in ("preload", "prefetch", "stylesheet"):
            add_img(href, kind=as_attr or "link")

    for meta in soup.find_all("meta", content=True):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if "image" in prop:
            add_img(meta.get("content"), kind="meta-image")

    # Regex sweep: any url-looking image/font/media in raw HTML
    for m in re.finditer(
        r"""https?://[^\s"'<>]+\.(?:png|jpe?g|gif|webp|svg|ico|avif|woff2?|ttf|eot|otf|mp4|webm)(?:\?[^\s"'<>]*)?""",
        html or "",
        re.I,
    ):
        add_img(m.group(0), kind="regex")
    for m in re.finditer(
        r"""["'](/_next/static/[^"']+)["']""",
        html or "",
        re.I,
    ):
        add_img(m.group(1), kind="next-static")

    # --- JSON-LD ---
    json_ld = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            json_ld.append(data)
        except Exception:
            pass

    # --- CSS background images (basic regex on style tags & inline) ---
    bg_images: Set[str] = set()
    for style in soup.find_all("style"):
        for m in re.finditer(r"url\(['\"]?([^)'\"]+)['\"]?\)", style.string or ""):
            bg_images.add(urljoin(base_url, m.group(1)))
    for el in soup.find_all(style=True):
        for m in re.finditer(r"url\(['\"]?([^)'\"]+)['\"]?\)", el.get("style", "")):
            bg_images.add(urljoin(base_url, m.group(1)))

    return {
        "title": title,
        "description": description,
        "keywords": keywords,
        "metas": metas,
        "open_graph": og,
        "twitter": twitter,
        "headings": headings[:50],
        "body_text_sample": body_text[:2000],
        "forms": forms,
        "internal_links": list(dict.fromkeys(internal))[:200],
        "external_links": list(dict.fromkeys(external))[:100],
        "scripts": scripts,
        "stylesheets": stylesheets,
        "images": images,
        "background_images": list(bg_images),
        "json_ld": json_ld,
    }


def extract_css_urls(css_text: str, base_url: str) -> List[str]:
    """Find url() references inside CSS."""
    urls = []
    for m in re.finditer(r"url\(['\"]?([^)'\"]+)['\"]?\)", css_text or ""):
        u = m.group(1).strip()
        if u and not u.startswith("data:"):
            urls.append(urljoin(base_url, u))
    return list(dict.fromkeys(urls))


def guess_purpose(parsed: Dict[str, Any], tech: List[Dict]) -> Dict[str, Any]:
    """Infer website purpose / motto from available signals."""
    title = parsed.get("title") or ""
    desc = parsed.get("description") or ""
    headings = [h["text"] for h in parsed.get("headings", [])[:10]]
    og_title = parsed.get("open_graph", {}).get("og:title", "")
    og_desc = parsed.get("open_graph", {}).get("og:description", "")

    # Explicit slogan heuristics
    motto = None
    for key in ("og:site_name", "twitter:title"):
        if key in parsed.get("metas", {}):
            candidate = parsed["metas"][key]
            if candidate and candidate != title:
                motto = candidate
                break

    # Inferred positioning
    text_blob = " ".join([title, desc, og_title, og_desc] + headings).lower()
    purpose_hints = []
    if any(w in text_blob for w in ("shop", "cart", "buy", "store", "product")):
        purpose_hints.append("E-commerce / online store")
    if any(w in text_blob for w in ("blog", "article", "post", "news")):
        purpose_hints.append("Blog / content publishing")
    if any(w in text_blob for w in ("portfolio", "designer", "photographer", "artist")):
        purpose_hints.append("Portfolio / personal brand")
    if any(w in text_blob for w in ("saas", "platform", "api", "dashboard", "login")):
        purpose_hints.append("SaaS / web application")
    if any(w in text_blob for w in ("university", "college", "school", "course")):
        purpose_hints.append("Educational institution")
    if any(w in text_blob for w in ("docs", "documentation", "guide", "reference")):
        purpose_hints.append("Documentation site")
    if not purpose_hints:
        purpose_hints.append("General informational / marketing website")

    tech_names = [t.get("name", "") for t in tech]
    if "Shopify" in tech_names:
        purpose_hints.insert(0, "Shopify storefront")
    if "WordPress" in tech_names:
        purpose_hints.insert(0, "WordPress site")

    return {
        "title": title,
        "description": desc,
        "explicit_motto_or_slogan": motto,
        "inferred_positioning": purpose_hints[0] if purpose_hints else "Unknown",
        "purpose_hints": purpose_hints,
        "audience_guess": "General public / consumers" if "E-commerce" in str(purpose_hints) else "Website visitors",
    }
