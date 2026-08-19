# Multi-stage Dockerfile for CDISC Builder v2
FROM python:3.12-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy project definition and source
COPY pyproject.toml README.md ./
COPY src ./src

# Install package
RUN pip install --no-cache-dir .

EXPOSE 8000

# Run Web UI
CMD ["cdiscbuilder", "app", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
