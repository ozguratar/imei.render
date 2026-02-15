# Hafif bir Python/Linux sürümü ile başla
FROM python:3.10-slim

# Gerekli Linux araçlarını kur ve Google Chrome'u modern yöntemle ekle
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    && mkdir -p /etc/apt/keyrings \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && sh -c 'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Çalışma klasörünü oluştur
WORKDIR /app

# Kütüphane listesini kopyala ve kur
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kodlarını kopyala
COPY . .

# Python dosyasını çalıştır
CMD ["python", "main.py"]
