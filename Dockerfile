FROM python:3.12-alpine

WORKDIR /app

# Install tzdata so Alpine supports Europe/Prague and local timezones
RUN apk add --no-cache tzdata

# Prevent Python from writing .pyc and enable unbuffered output
ENV TZ=Europe/Prague \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CHECK_INTERVAL_SECONDS=900 \
    CLASS_NAME=C4b \
    STATE_FILE_PATH=/data/state.json

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

VOLUME ["/data"]

CMD ["python", "main.py"]
