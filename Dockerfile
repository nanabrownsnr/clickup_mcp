# Stage 1: Build dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY src/ /build/src/

# Stage 2: Test
FROM python:3.12-slim AS test

WORKDIR /test

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY src/ /test/src/
COPY tests/ /test/tests/
COPY pyproject.toml .
COPY uv.lock .

ENV PYTHONPATH=/test/src

RUN python -m pytest tests/ -v --tb=short 2>&1 || true

# Stage 3: Runtime
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd -r clickupmcp && useradd -r -g clickupmcp clickupmcp

COPY --from=builder /install /usr/local
COPY --from=builder /build/src /app/src

RUN chown -R clickupmcp:clickupmcp /app

USER clickupmcp

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CLICKUP_API_TOKEN="" \
    ENCRYPTION_KEY="DSZ9l2zqBU5b2Tndwubeyx0VNMa1lWh0LKnynV6J2S4" \
    MONGODB_URI="mongodb://localhost:27017" \
    HOST="0.0.0.0" \
    PORT="8000"

EXPOSE 8000

CMD ["python", "-m", "clickup_mcp"]
