FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PAPER_DB=/data/paper.sqlite3
WORKDIR /app
COPY paper_btc5m.py dashboard.py runner.py index.html ./
EXPOSE 8080
CMD ["python", "/app/runner.py"]
