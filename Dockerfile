# EAGLE EYE console in one container:  docker build -t eagle-eye . && docker run -p 8000:8000 eagle-eye
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY eagle_eye/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY eagle_eye/ .
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "python server.py --host 0.0.0.0 --port ${PORT} --no-browser"]
