# Temel işletim sistemi (Python ve hafif bir Linux)
FROM python:3.10-slim

# Linux'u güncelle, Google Chrome'u ve gerekli kütüphaneleri kur
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Çalışma klasörünü ayarla
WORKDIR /app

# Kütüphaneleri kopyala ve kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Senin main.py dosyanı sunucuya kopyala
COPY . .

# FastAPI'yi başlat
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
