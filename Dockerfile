FROM python:3.11-slim

ARG APP_VERSION=dev
ENV PYTHONUNBUFFERED=1 \
    APP_VERSION=${APP_VERSION}

WORKDIR /app
COPY app.py .

EXPOSE 5000

# Docker HEALTHCHECK: dijalankan Docker Engine dari DALAM container secara berkala
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=2)"

CMD ["python", "app.py"]
