"""Entry-point hardening: the root URL and app routes must never render blank or JSON-only."""

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_renders_honest_landing_with_working_ctas(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "Try sample validation" in body
    assert "Open workbench" in body
    assert 'href="/dashboard?sample=1"' in body
    assert 'href="/dashboard"' in body
    assert "Who it is for" in body
    assert "The workflow, in four steps" in body
    assert "synthetic" in body.lower()


def test_dashboard_and_preview_routes_serve_html(client):
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "text/html" in dashboard.headers["content-type"]
    assert "workbench" in dashboard.text.lower()

    preview = client.get("/preview")
    assert preview.status_code == 200
    assert "text/html" in preview.headers["content-type"]


def test_each_workbench_tab_has_a_page_level_heading(client):
    body = client.get("/dashboard").text
    expected_titles = {
        "overview": "Workspace overview",
        "workbench": "Validation workbench",
        "mapping": "Vendor mapping",
        "compare": "Compare validation runs",
        "roundtrip": "Transformation inspector",
        "suites": "Test suites",
        "vendors": "Vendor adapters",
        "history": "Run history",
        "standards": "Standards reference",
    }

    for tab_id, title in expected_titles.items():
        section_start = body.index(f'<section id="view-{tab_id}"')
        heading_start = body.index('<div class="page-heading">', section_start)
        section_end = body.index("</section>", section_start)
        assert heading_start < section_end
        assert f"<h1>{title}</h1>" in body[heading_start:section_end]


def test_unknown_path_negotiates_html_for_browsers(client):
    browser = client.get("/does-not-exist", headers={"accept": "text/html"})
    assert browser.status_code == 404
    assert "text/html" in browser.headers["content-type"]
    assert "does not exist" in browser.text
    assert 'href="/dashboard"' in browser.text

    api = client.get("/does-not-exist", headers={"accept": "application/json"})
    assert api.status_code == 404
    assert "application/json" in api.headers["content-type"]
    assert api.json()["detail"] == "Not Found"


def test_favicon_redirects_to_static_icon(client):
    res = client.get("/favicon.ico", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/static/icon.svg"


def test_root_falls_back_when_static_ui_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "STATIC_DIR", str(tmp_path))

    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert "not in this build" in root.text
    assert 'href="/api/health"' in root.text

    workbench = client.get("/dashboard")
    assert workbench.status_code == 503
    assert "Workbench UI file is missing" in workbench.text
    assert 'href="/dashboard"' in workbench.text

    preview = client.get("/preview")
    assert preview.status_code == 404
    assert "Product overview page not found" in preview.text


def test_root_falls_back_to_dashboard_when_only_workbench_exists(client, monkeypatch, tmp_path):
    """A build without the entry/landing pages still renders the workbench at the root."""
    (tmp_path / "dashboard.html").write_text("<!doctype html><title>wb</title>", encoding="utf-8")
    monkeypatch.setattr(main_module, "STATIC_DIR", str(tmp_path))

    assert "wb" in client.get("/").text


def test_root_serves_legacy_export_when_entry_page_is_absent(client, monkeypatch, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>landing</title>", encoding="utf-8")
    monkeypatch.setattr(main_module, "STATIC_DIR", str(tmp_path))

    assert "landing" in client.get("/").text
    assert "landing" in client.get("/preview").text
