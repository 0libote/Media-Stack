FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PANEL_STATE_DIR=/state PANEL_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY control ./control
COPY portal ./portal
USER 1000:1000
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/api/health', timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:8088", "--workers", "1", "--threads", "8", "--timeout", "120", "control.app:create_app()"]
