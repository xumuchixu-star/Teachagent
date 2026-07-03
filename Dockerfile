FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TEACHAGENT_HOST=0.0.0.0
ENV TEACHAGENT_PORT=8765

WORKDIR /app

COPY app/requirements-web.txt /tmp/requirements-web.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-web.txt

COPY . /app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()"]

CMD ["python", "app/server.py"]
