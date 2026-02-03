FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir iptcinfo3 python-fasthtml

COPY main.py /app/main.py

RUN mkdir -p /app/data/images

EXPOSE 5001

CMD ["python", "main.py"]
