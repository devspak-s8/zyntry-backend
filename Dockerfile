FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libpq-dev \
    curl \
    git \
    openssl \
    libssl3t64 \
    openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/python -m pip install --upgrade "pip>=26.2" "setuptools>=78.1.1" wheel && \
    /opt/venv/bin/python -m pip install --no-cache-dir --upgrade -r requirements.txt && \
    /opt/venv/bin/python -c "from importlib.metadata import version; from packaging.version import Version; assert Version(version('msgpack')) >= Version('1.2.1'); assert Version(version('setuptools')) >= Version('78.1.1')" && \
    /opt/venv/bin/python -c "import pathlib, pip; [path.unlink() for path in pathlib.Path(pip.__file__).parent.rglob('bom.cdx.json')]"

FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    bash \
    postgresql-client \
    redis-tools \
    openssl \
    libssl3t64 \
    openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/*

# The base Python image includes its own pip/setuptools. They are not needed at
# runtime, and leaving their metadata beside the application environment can
# make scanners report packages that are not used by this image.
RUN find /usr/local/lib/python3.12/site-packages -maxdepth 1 \
    \( -name 'pip' -o -name 'pip-*.dist-info' \
       -o -name 'setuptools' -o -name 'setuptools-*.dist-info' \
       -o -name 'wheel' -o -name 'wheel-*.dist-info' \) \
    -exec rm -rf {} +

COPY --from=builder /opt/venv /opt/venv

COPY alembic ./alembic
COPY alembic.ini .
COPY app ./app
COPY scripts ./scripts
COPY entrypoints ./entrypoints
COPY requirements.txt .

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    chmod +x /app/entrypoints/*.sh && \
    chmod +x /app/scripts/migrate.sh

USER appuser

EXPOSE 8000 8001 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
