FROM python:3.12-slim

# ffmpeg is required by yt-dlp for audio extraction and muxing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV WORK_DIR=/app/work
ENV COOKIES_FILE=/app/cookies/cookies.txt
EXPOSE 8000

# uvicorn imposes no per-request timeout by default, so long synchronous
# downloads are not cut off.
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
