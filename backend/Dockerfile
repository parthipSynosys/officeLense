# EventLens backend image (API + workers share this image).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODELS_DIR=/app/models \
    PHOTOS_DIR=/data/photos

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Download + verify the OpenCV Zoo models at build time (Apache-2.0).
COPY scripts/download_models.py scripts/download_models.py
RUN python scripts/download_models.py --dir /app/models

COPY . .

RUN useradd --system --uid 1000 --home /app eventlens \
    && mkdir -p /data/photos \
    && chown -R eventlens:eventlens /data /app
USER eventlens

EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:8000"]
