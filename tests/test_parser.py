"""Basic unit tests for parser & fingerprint modules."""

from app.parser import parse_html, guess_purpose
from app.fingerprint import detect_technologies


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Acme Store — Best Gadgets</title>
  <meta name="description" content="Shop the latest gadgets online.">
  <meta property="og:title" content="Acme Store">
  <link rel="stylesheet" href="/static/app.css">
  <script src="https://cdn.shopify.com/s/files/1/theme.js"></script>
</head>
<body>
  <h1>Welcome to Acme</h1>
  <form action="/cart" method="post">
    <input type="text" name="email" required>
    <button type="submit">Buy</button>
  </form>
  <img src="/images/logo.png" alt="Logo">
  <a href="/products">Products</a>
  <a href="https://external.example">External</a>
</body>
</html>
"""


def test_parse_title_and_meta():
    p = parse_html(SAMPLE_HTML, "https://acme.example")
    assert p["title"] == "Acme Store — Best Gadgets"
    assert "gadgets" in p["description"].lower()
    assert len(p["forms"]) == 1
    assert p["forms"][0]["method"] == "POST"
    assert any("logo.png" in (i.get("url") or "") for i in p["images"])


def test_tech_detection():
    techs = detect_technologies([SAMPLE_HTML], [{}], [])
    names = [t["name"] for t in techs]
    assert "Shopify" in names


def test_purpose():
    p = parse_html(SAMPLE_HTML, "https://acme.example")
    techs = detect_technologies([SAMPLE_HTML], [{}], [])
    purpose = guess_purpose(p, techs)
    assert purpose["title"]
    assert "E-commerce" in purpose["inferred_positioning"] or "Shopify" in purpose["inferred_positioning"]


if __name__ == "__main__":
    test_parse_title_and_meta()
    test_tech_detection()
    test_purpose()
    print("All tests passed.")
