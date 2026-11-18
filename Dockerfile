FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COLOR_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 appuser \
    && mkdir /data && chown appuser:appuser /data
COPY chromatic ./chromatic
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["uvicorn", "chromatic.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
