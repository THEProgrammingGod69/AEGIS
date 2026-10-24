# EAGLE EYE console in one container:  docker build -t eagle-eye . && docker run -p 8000:8000 eagle-eye
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY eagle_eye/requirements-engine.txt .
RUN pip install --no-cache-dir -r requirements-engine.txt \
    && pip install --no-cache-dir --no-deps rapidocr-onnxruntime==1.4.4

COPY eagle_eye/ .
ENV PORT=8000 PYTHONUNBUFFERED=1 EAGLE_EYE_REAL_DATA=/app/data/emerson EAGLE_AGENT_ENABLED=0
EXPOSE 8000
CMD ["sh", "-c", "python server.py --host 0.0.0.0 --port ${PORT} --no-browser"]
