# VidyutSetu Deployment Guide

## 1. Local Deployment (Standalone Python)
```bash
# 1. Clone repository
git clone https://github.com/PalaniappanR02/vidyutsetu.git
cd vidyutsetu

# Set up virtual environment, then activate it for your shell
python -m venv .venv
pip install -r requirements.txt

# Start workbench server
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
In demo mode, the first-run administrator password is logged once to the local
server console when no initial password is set. Use password mode and a unique
initial administrator password for any shared or controlled environment. See
[Security and Access](docs/SECURITY_AND_ACCESS.md).

---

## 2. Docker & Container Deployment
```bash
# Build Docker image
docker build -t vidyutsetu:latest .

# Run container with durable data and password authentication
docker volume create vidyutsetu-data
docker run -d -p 8000:8000 \
  -e VIDYUTSETU_INITIAL_ADMIN_PASSWORD="<set-a-unique-secret>" \
  -v vidyutsetu-data:/data \
  --name vidyutsetu-app vidyutsetu:latest
```

### Docker Compose
```bash
# Optional for a local-only demo: defaults to demo auth on localhost port 8000.
docker-compose up -d

# For a controlled deployment, configure these in the environment first:
# VIDYUTSETU_ENV=production
# VIDYUTSETU_AUTH_MODE=password
# VIDYUTSETU_INITIAL_ADMIN_PASSWORD=<unique-secret>
```
The image runs as a non-root user, persists SQLite data in `/data`, and probes
`/ready` for container health. Production cookie security defaults to Secure;
terminate TLS at a trusted reverse proxy and do not expose the app directly.

---

## 3. Production Hardening & Reverse Proxy (Nginx)
In production or enterprise utility intranets, deploy behind Nginx or Traefik with TLS/SSL:
```nginx
server {
    listen 80;
    server_name vidyutsetu.utility.internal;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 4. Cloud Deployment (Free Tier / Container PaaS)
VidyutSetu persists its audit and workbench data in SQLite. A platform must provide
a durable writable volume for `/data`; ephemeral storage is not suitable when
history must survive restarts. Multi-worker deployment should use a shared
rate-limiting layer at the reverse proxy because login throttling is local to
the application database.
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- **Port**: Set by hosting environment (default 8000).
- **Persistent Storage**: Mount a durable volume at `/data`.
- **Cross-origin access**: The UI is same-origin by default. If a separately hosted
  frontend must call the API, set `VIDYUTSETU_CORS_ORIGINS` to a comma-separated
  allow-list such as `https://workbench.utility.example`; do not use a wildcard.
