FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
    aiohttp==3.9.3 \
    aiohttp-cors==0.7.0 \
    python-dotenv==1.0.1 \
    aiodns==3.1.1 \
    "numpy>=1.24.0" \
    "requests>=2.31.0" \
    "aiohttp-jinja2>=1.5.0" \
    "jinja2>=3.1.0" \
    "aiohttp-session>=2.12.0" \
    "cryptography>=41.0.0"

COPY src/ src/

RUN mkdir -p data/probe_reports

EXPOSE 8081

CMD ["python", "src/main.py"]
