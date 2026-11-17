"""FastAPI Main Application for VidyutSetu AMI Interoperability Testing Workbench."""

import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.db.database import engine, init_db
from backend.api.routes import router as api_router
from backend.api.ml_routes import router as ml_router

app = FastAPI(
    title="VidyutSetu — AMI Data Exchange Interoperability Testing Workbench",
    description="Software workbench for multi-vendor smart metering HES and MDMS interoperability testing, canonical data normalization, and conformance scoring.",
    version="1.0.0"
)

# CORS is same-origin by default. Cross-origin deployments explicitly opt in
# with a comma-separated VIDYUTSETU_CORS_ORIGINS allow-list.
cors_origins = [
    origin.strip()
    for origin in os.getenv("VIDYUTSETU_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize SQLite database schema
init_db()

# Mount API routes
app.include_router(api_router)
app.include_router(ml_router)

# Mount Static UI
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _static_file(name: str) -> Optional[str]:
    """Absolute path of a static file, or None when it is not present in this build."""
    path = os.path.join(STATIC_DIR, name)
    return path if os.path.isfile(path) else None


def _fallback_page(title: str, detail: str, status_hint: str = "") -> str:
    """Self-contained HTML shown when a static UI file is missing.

    Rendered without any external asset so it cannot itself be blank, and it always
    offers a working next step instead of an error body.
    """
    hint = f"<p class=\"hint\">{status_hint}</p>" if status_hint else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · VidyutSetu</title>
<style>
  :root {{ --navy:#0B2545; --teal:#0B7C87; --amber:#F59E0B; --bg:#F4F8FB; --ink:#13263B; --body:#33506B; --line:#D6E3EE; }}
  body {{ margin:0; min-height:100vh; background:var(--bg); color:var(--ink);
         font-family:"Segoe UI", Inter, system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif;
         display:flex; align-items:center; justify-content:center; padding:1.5rem; }}
  main {{ max-width:620px; background:#fff; border:1px solid var(--line); border-radius:16px; padding:1.6rem 1.7rem; }}
  h1 {{ font-size:1.35rem; margin:0 0 .5rem; }}
  p {{ color:var(--body); margin:0 0 .8rem; line-height:1.55; }}
  .hint {{ font-size:.85rem; color:#5B7288; }}
  .actions {{ display:flex; gap:.6rem; flex-wrap:wrap; margin-top:1.1rem; }}
  a.btn {{ display:inline-flex; align-items:center; border-radius:10px; padding:.6rem .95rem;
           font-weight:600; font-size:.88rem; text-decoration:none; border:1px solid var(--line); color:var(--navy); background:#fff; }}
  a.primary {{ background:var(--teal); border-color:var(--teal); color:#fff; }}
  a:focus-visible {{ outline:3px solid var(--teal); outline-offset:2px; }}
  code {{ background:#EAF2F8; padding:.1rem .3rem; border-radius:4px; font-size:.85em; }}
  .notice {{ border-left:4px solid var(--amber); background:#FFF4E0; color:#8A5A00;
             padding:.6rem .8rem; border-radius:8px; font-size:.82rem; }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p>{detail}</p>
  {hint}
  <div class="notice">The API is unaffected: validation, conversion and reports still work over HTTP.</div>
  <div class="actions">
    <a class="btn primary" href="/dashboard">Open the workbench</a>
    <a class="btn" href="/docs">API docs</a>
    <a class="btn" href="/api/health">Service health</a>
  </div>
</main>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_landing():
    """Root URL always renders a page, never a blank body or a bare JSON blob."""
    for candidate in ("start.html", "index.html", "dashboard.html"):
        path = _static_file(candidate)
        if path:
            return FileResponse(path)
    return HTMLResponse(
        _fallback_page(
            "The VidyutSetu web interface is not in this build",
            "No static landing page was found at "
            "<code>backend/static/start.html</code>, <code>index.html</code> or "
            "<code>dashboard.html</code>, so there is nothing to render here yet.",
            "In a source checkout, confirm the files exist under backend/static and that they are "
            "committed; in a deployment, check that backend/static was included in the image.",
        )
    )


@app.get("/preview", response_class=HTMLResponse)
def serve_product_preview():
    """The designed marketing page (Next.js static export), kept as-is."""
    path = _static_file("index.html")
    if path:
        return FileResponse(path)
    return HTMLResponse(
        _fallback_page(
            "Product overview page not found",
            "This build does not include the static product overview (backend/static/index.html).",
            "The workbench itself is available at /dashboard.",
        ),
        status_code=404,
    )


@app.get("/dashboard", response_class=HTMLResponse)
def serve_workbench():
    path = _static_file("dashboard.html")
    if path:
        return FileResponse(path)
    return HTMLResponse(
        _fallback_page(
            "Workbench UI file is missing",
            "This build does not include <code>backend/static/dashboard.html</code>, so the "
            "interactive workbench cannot be rendered.",
            "Restore the file in the deployment (or run from a complete checkout) and reload.",
        ),
        status_code=503,
    )


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse(url="/static/icon.svg", status_code=307)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    """Human-readable 404 for browser navigation; JSON for API clients."""
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return HTMLResponse(
            _fallback_page(
                "That page does not exist",
                f"The path <code>{request.url.path}</code> is not part of this application.",
                "Use one of the links below to get back to a working screen.",
            ),
            status_code=404,
        )
    detail = getattr(exc, "detail", "Not Found")
    return JSONResponse({"detail": detail}, status_code=404)


@app.get("/health")
def health_check():
    """Report service and database health with an HTTP failure when the DB is down."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "error"
    return JSONResponse(
        {
            "status": "ok" if db_status == "ok" else "error",
            "version": app.version,
            "db": db_status,
        },
        status_code=200 if db_status == "ok" else 503,
    )
