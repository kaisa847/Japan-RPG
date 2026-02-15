FROM python:3.11-slim

WORKDIR /app

# Install only runtime dependencies (no dev tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt gunicorn

# Copy application code
COPY backend/ backend/
COPY frontend/ frontend/
COPY data/start_prompt.txt data/locations.json data/
COPY data/characters/ data/characters/
COPY generate_placeholders.py .

# Generate placeholder assets
RUN python generate_placeholders.py

# Create data directories for runtime
RUN mkdir -p data/users data/saves

EXPOSE 8000

# Run with gunicorn + uvicorn workers for production
CMD ["gunicorn", "backend.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
