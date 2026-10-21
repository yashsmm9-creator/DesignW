FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000 \
    COOKIE_SECURE=1 \
    FLASK_ENV=production \
    FLASK_DEBUG=0

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3000
CMD ["sh", "-c", "exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-3000} --timeout 120 app:app"]
