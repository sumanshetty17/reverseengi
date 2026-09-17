# Official Playwright image: Python + Chromium/Firefox/WebKit + all OS deps
# preinstalled, so there's no apt/su step at build time (which is what
# fails on Render's native Python buildpack).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /app

# Install Python deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Render sets $PORT at runtime
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
