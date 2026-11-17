from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_HTML = (ROOT / "backend" / "static" / "dashboard.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "backend" / "static" / "app.js").read_text(encoding="utf-8")


def test_dashboard_file_picker_accepts_json_and_csv_only():
    assert 'accept=".json,.csv,text/csv,application/json"' in DASHBOARD_HTML
    assert 'Upload a JSON or CSV payload file' in DASHBOARD_HTML


def test_workbench_validates_unsupported_uploads_and_errors():
    assert "Unsupported file type" in APP_JS
    assert "Use a payload under 5 MB" in APP_JS
    assert "Failed to generate synthetic data" in APP_JS


def test_copy_action_handles_browser_and_fallback_copy_paths():
    assert "navigator.clipboard" in APP_JS
    assert "document.execCommand('copy')" in APP_JS
    assert "Clipboard copy failed" in APP_JS


def test_dashboard_requires_sign_in_and_exposes_role_aware_controls():
    assert 'id="auth-screen"' in DASHBOARD_HTML
    assert 'id="login-form"' in DASHBOARD_HTML
    assert "X-CSRF-Token" in APP_JS
    assert 'data-role-required="admin"' in DASHBOARD_HTML
    assert "applyRoleVisibility" in APP_JS
