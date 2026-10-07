FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium && useradd --create-home robot && mkdir /app/data && chown -R robot:robot /app/data /opt/browsers
COPY portal.py server.py entrypoint.py ./
EXPOSE 8080
CMD ["python", "entrypoint.py"]
