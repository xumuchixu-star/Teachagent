FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OCR_SERVICE_HOST=0.0.0.0
ENV OCR_SERVICE_PORT=8890
ENV OCR_SERVICE_OUTPUT_ROOT=/app/scratch/mineru_runs
ENV MINERU_MODEL_SOURCE=modelscope
ENV HF_HOME=/app/model-cache/huggingface
ENV MODELSCOPE_CACHE=/app/model-cache/modelscope
ENV TORCH_HOME=/app/model-cache/torch

WORKDIR /app

COPY ocr_service/requirements.txt /tmp/ocr-service-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/ocr-service-requirements.txt

COPY ocr_service /app/ocr_service
COPY scripts /app/scripts

RUN mkdir -p /app/model-cache /app/scratch/ocr_service_uploads /app/scratch/mineru_runs

EXPOSE 8890

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8890/healthz', timeout=3).read()"]

CMD ["python", "ocr_service/server.py", "--host", "0.0.0.0", "--port", "8890"]
