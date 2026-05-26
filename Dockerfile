FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    STOCK_PRICES_OUTPUT_DIR=/app/animations

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY scripts ./scripts
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/animations /app/logs /app/stock /app/global /app/currency /app/futures

CMD ["python", "-m", "stock_prices", "bot"]
