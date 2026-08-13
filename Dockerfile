FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir --upgrade pip
RUN python -m pip install --no-cache-dir ".[web]"

EXPOSE 8000

CMD ["python", "-m", "docuforge.api.run"]
