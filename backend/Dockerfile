# Backend API image. Build context is the repo root so we can copy both the
# backend package and the scripts/ directory (seed, migrations helpers).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# A TrueType CJK font so exported PDFs render Traditional Chinese in any viewer.
# WenQuanYi Zen Hei installs at /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc,
# which app/services/exports.py already looks for (glyf-based; loadable by
# ReportLab's TTFont, unlike Noto CJK's CFF outlines). Override with CJK_FONT_PATH.
#
# LibreOffice (headless) renders uploaded Office docs (PPTX/DOCX/XLSX) to a PDF
# so agents can preview them on screen; fonts-noto-cjk keeps Chinese text intact
# in the generated PDF. Impress/Writer/Calc cover the three Office formats.
# ffmpeg extracts a frame for video thumbnails (image/PDF thumbnails use
# Pillow/PyMuPDF wheels installed via pip below).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-wqy-zenhei fonts-noto-cjk \
        libreoffice-impress libreoffice-writer libreoffice-calc \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# System deps for bcrypt/psycopg2 wheels are already provided; keep image slim.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts

RUN chmod +x /app/backend/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
