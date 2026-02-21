FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -r pyproject.toml

COPY . .

EXPOSE 5000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["bash", "docker-entrypoint.sh"]
CMD ["python", "app.py"]
