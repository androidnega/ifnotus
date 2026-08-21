"""Customer-facing path scrubbing must never leak host layout."""

from app.utils.customer_safe import scrub_host_paths, scrub_obj


def test_scrubs_tenant_docroot_to_relative():
    raw = "Saved /srv/apps/ifnotus-customers/317225d0-0e77-46f9-b63c-a45736b4c018/public_html/index.html"
    out = scrub_host_paths(raw)
    assert "/srv/apps" not in out
    assert "ifnotus-customers" not in out
    assert "index.html" in out


def test_scrubs_platform_paths():
    assert "site root" in scrub_host_paths("see /srv/apps/ifnotus/backend/app/main.py")
    assert "/etc/nginx" not in scrub_host_paths("fail /etc/nginx/sites-enabled/x.conf")


def test_scrub_obj_skips_file_content():
    payload = {
        "message": "Root /srv/apps/ifnotus-customers/abc/public_html",
        "content": "<!-- /srv/apps/ifnotus-customers/abc/public_html/index.html -->",
    }
    out = scrub_obj(payload)
    assert isinstance(out, dict)
    assert "/srv/apps" not in str(out["message"])
    assert "/srv/apps/ifnotus-customers" in str(out["content"])
