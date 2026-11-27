FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    STOCK_PRICES_OUTPUT_DIR=/app/animations

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml pdm_build.py README.md LICENSE ./
COPY docs/assets/demo-sber-lkoh.mp4 ./docs/assets/
COPY scripts ./scripts
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/animations /app/logs

CMD ["python", "-m", "stock_prices", "bot"]
