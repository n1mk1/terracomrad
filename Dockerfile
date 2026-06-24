# TerraComrad — container image for any host that runs a long-lived web process
# (Render, Railway, Fly.io, Cloud Run, a VPS…). The app is a standard uvicorn
# server with writable scratch dirs, so it runs unchanged inside a container.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
# numpy / scipy / Pillow / pydicom all ship manylinux wheels, so no system
# build toolchain is needed on python:slim.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code, frontend, and the bundled demo DICOMs (backend/demos must ship).
COPY . .

# Hosts inject the port to bind on; default to 8000 for a plain `docker run`.
ENV PORT=8000
EXPOSE 8000

# Shell form so ${PORT} expands at runtime.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
