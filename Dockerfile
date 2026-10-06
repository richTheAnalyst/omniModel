FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN pip install --no-cache-dir uv

# Install dependencies and the project (the package folder must exist before `uv sync`)
COPY pyproject.toml uv.lock README.md ./
COPY omnimodel ./omnimodel
COPY profiles ./profiles
RUN uv sync --frozen --extra api --extra scraping

# Browser used by the website scraper (this is the big download)
RUN playwright install --with-deps chromium

EXPOSE 8000
CMD ["sh", "-c", "uvicorn omnimodel.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
