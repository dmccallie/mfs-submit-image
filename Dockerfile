FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
        ca-certificates \
        libimage-exiftool-perl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "boto3>=1.42.64" \
    "pyexiftool>=0.5.6" \
    "python-dotenv>=1.1.1" \
    "python-fasthtml>=0.12.39"

COPY submit_image.py /app/submit_image.py
COPY static /app/static

RUN mkdir -p /app/data/images

ENV PORT=5001
EXPOSE 5001

# CMD ["python", "main.py"]
# run with uvicorn submit_image:app --host
CMD ["sh", "-c", "exec .venv/bin/uvicorn submit_image:app --host 0.0.0.0 --port ${PORT:-5001} --proxy-headers"]
