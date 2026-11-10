# UNTESTED: Docker was not available where this was written. Build and try it on a staging server first.
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libraqm0 libfribidi0 fonts-noto-core libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt
COPY . .
# Run as an unprivileged user: a bug in ffmpeg / a decoder then cannot touch the system. The data/upload/output folders are created
# here, owned by that user, so the named volumes in docker-compose.yml (mounted over uploads/ and outputs/) inherit the ownership.
RUN useradd --system --create-home --uid 10001 app \
 && mkdir -p /app/data /app/uploads /app/outputs \
 && chown -R app:app /app
USER app
ENV BURMESE_FONT_PATH=/usr/share/fonts/truetype/noto/NotoSansMyanmar-Bold.ttf \
    DUB_PROVIDER=gemini
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
