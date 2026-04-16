FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
  apt-get install -y --no-install-recommends git curl && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY backend/ ./backend/
COPY alembic.ini ./

EXPOSE 8000

CMD ["python", "backend/run.py"]