"""Site path masking for customer Dev Companion replies."""

from app.services.ai.memory import mask_site_paths


def test_masks_ifnotus_customers_prefix():
    raw = "Root is /srv/apps/ifnotus-customers/abc-123/public_html/index.html"
    out = mask_site_paths(raw, "/srv/apps/ifnotus-customers/abc-123/public_html")
    assert "/srv/apps/ifnotus-customers" not in out
    assert "index.html" in out


def test_site_root_when_exact_docroot():
    doc = "/srv/apps/ifnotus-customers/abc/public_html"
    out = mask_site_paths(f"Path: {doc}", doc)
    assert out == "Path: site root"
