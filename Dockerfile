FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/docuforge

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        fonts-dejavu-core \
        fonts-liberation \
        libreoffice-calc \
        libreoffice-core \
        libreoffice-impress \
        libreoffice-writer \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 docuforge \
    && useradd --uid 10001 --gid docuforge --create-home --shell /usr/sbin/nologin docuforge

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip
RUN python -m pip install --no-cache-dir ".[web]"

EXPOSE 8000

USER docuforge

CMD ["python", "-m", "docuforge.api.run"]
