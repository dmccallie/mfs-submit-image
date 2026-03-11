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

COPY main.py /app/main.py
COPY static /app/static

RUN mkdir -p /app/data/images

EXPOSE 5001

CMD ["python", "main.py"]
