"""FastAPI Main Application for VidyutSetu AMI Interoperability Testing Workbench."""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

# Enable CORS for utility integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "VidyutSetu API is running. Build static UI in backend/static/index.html to view dashboard."
    }


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "error"
    return {"status": "ok", "version": "0.1.0", "db": db_status}
