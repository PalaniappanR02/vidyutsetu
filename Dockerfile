FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIDYUTSETU_ENV=production \
    VIDYUTSETU_AUTH_MODE=password \
    VIDYUTSETU_DATABASE_URL=sqlite:////data/vidyutsetu.db

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app app \
    && mkdir /data && chown app:app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

VOLUME ["/data"]
EXPOSE 8000
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/ready', timeout=3)"]

CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
