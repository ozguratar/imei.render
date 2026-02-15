import uvicorn
import asyncio
from fastapi import FastAPI, Header, HTTPException, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import base64
import time
import re
from datetime import datetime
import uuid

# --- KÜTÜPHANE ---
import google.generativeai as genai

# --- AYARLAR ---
GOOGLE_API_KEY = "AIzaSyCZZOiGEx9M-8wYKbl2LJWhrS6esx3sJr4"
ADMIN_PASSWORD = "admin" # Admin paneline girmek için şifren! (Değiştirebilirsin)

# --- VERİTABANI (Hafızada tutulur) ---
# Key formatı: {"owner": "isim", "credits": 100, "total_used": 0, "created_at": "tarih"}
API_DB = {
    "test": {"owner": "Test Kullanıcısı", "credits": 100, "total_used": 0, "created_at": "Sistem"},
    "patron_sensin": {"owner": "Kurucu (Sınırsız)", "credits": 99999, "total_used": 0, "created_at": "Sistem"} 
}

# Sorgu loglarını tutacağımız liste
QUERY_LOGS = [] 

# --- AKILLI MODEL SEÇİCİ ---
active_model = None

def setup_ai_model():
    global active_model
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        print("\n--- AI MODEL TARAMASI ---")
        vision_models = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    if 'flash' in m.name or 'vision' in m.name or '1.5-pro' in m.name:
                        vision_models.append(m.name)
        except:
            vision_models = ["models/gemini-1.5-flash", "models/gemini-pro-vision"]

        if not vision_models:
            selected_model = 'models/gemini-1.5-flash'
        else:
            selected_model = vision_models[0]
            for m in vision_models:
                if 'flash' in m and '1.5' in m:
                    selected_model = m
                    break
        
        clean_name = selected_model.replace("models/", "")
        print(f"LOG: Seçilen AI Modeli: {clean_name}\n")
        active_model = genai.GenerativeModel(clean_name)
    except Exception as e:
        print(f"LOG: AI Hatası: {e}")

setup_ai_model()
BROWSER_LOCK = asyncio.Lock()

# --- MODELLER ---
class IMEIResponse(BaseModel):
    success: bool
    imei: str
    durum: Optional[str] = None
    model: Optional[str] = None
    kaynak: Optional[str] = None
    tarih: Optional[str] = None
    kategori: Optional[str] = None
    aciklama: Optional[str] = None
    renk: Optional[str] = None
    remaining_credits: int
    error: Optional[str] = None

class IMEIRequest(BaseModel):
    imei: str

class AdminCreateKeyRequest(BaseModel):
    owner: str
    credits: int

# --- YARDIMCI FONKSİYONLAR ---
def calculate_luhn(imei_14: str) -> str:
    digits = [int(d) for d in imei_14]
    checksum = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = digit * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += digit
    return str((10 - (checksum % 10)) % 10)

def solve_captcha_with_ai(base64_string):
    global active_model
    try:
        if not base64_string: return None
        if not active_model: setup_ai_model()
        if not active_model: return None
        
        if "base64," in base64_string:
            base64_string = base64_string.split("base64,")[1]
            
        img_data = base64.b64decode(base64_string)
        prompt = "Bu resimdeki metni oku. Sadece harf ve rakamları yaz. Boşluk bırakma."
        
        response = active_model.generate_content([prompt, {"mime_type": "image/png", "data": img_data}])
        response.resolve()
        
        text = response.text.strip()
        clean_text = re.sub(r'\s+', '', text)
        print(f"   -> AI Yanıtı: {clean_text}")
        return clean_text
    except Exception as e:
        print(f"   -> AI Hatası: {e}")
        return None

# --- ROBOT (Arka Planda Gizli Çalışan) ---
def fetch_imei_data(target_imei: str):
    driver = None
    result = {"durum": None, "model": None, "kaynak": None, "tarih": None, "renk": None, "error": None}
    
    try:
        options = uc.ChromeOptions()
        # ARKA PLANDA ÇALIŞMASI İÇİN HEADLESS AÇILDI! 🚀
        options.add_argument("--headless=new") 
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        
        driver = uc.Chrome(options=options, version_main=144)
        wait = WebDriverWait(driver, 20)

        success_flag = False

        for attempt in range(1, 4):
            print(f"\nLOG: Deneme {attempt}/3...")
            try:
                driver.get("https://www.turkiye.gov.tr/imei-sorgulama")
                
                # ADIM 1: IMEI YAZ
                wait.until(EC.visibility_of_element_located((By.ID, "txtImei"))).send_keys(target_imei)
                print("   -> 1. IMEI Yazıldı.")

                # ADIM 2 & 3: CAPTCHA
                captcha_images = driver.find_elements(By.CLASS_NAME, "captchaImage")
                if len(captcha_images) > 0:
                    print("   -> 2. Captcha TESPİT EDİLDİ.")
                    captcha_img = captcha_images[0]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", captcha_img)
                    time.sleep(0.5)
                    
                    code = solve_captcha_with_ai(captcha_img.screenshot_as_base64)
                    if not code or len(code) < 4:
                        print("   -> Captcha okunamadı, yenileniyor.")
                        continue 
                    
                    try:
                        driver.find_element(By.NAME, "captcha_name").send_keys(code)
                    except:
                        driver.execute_script(f"document.getElementsByName('captcha_name')[0].value = '{code}';")
                else:
                    print("   -> 3. Captcha YOK. Direkt sorgulanıyor...")

                time.sleep(0.5)

                # BUTON
                try:
                    driver.execute_script("var c=document.querySelector('.cookie-policy'); if(c) c.remove();")
                    submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.submitButton")))
                    driver.execute_script("arguments[0].click();", submit_btn)
                except Exception as e:
                    continue

                # SONUÇ
                time.sleep(2.5)
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                
                errs = driver.find_elements(By.CLASS_NAME, "error")
                if errs and ("resmi" in errs[0].text.lower() or "yanlış" in errs[0].text.lower()):
                    print(f"   -> HATA: Captcha Yanlış. Tekrar deneniyor...")
                    continue 
                
                page_text = driver.find_element(By.TAG_NAME, "body").text
                
                if "Durum" in page_text or "Kayıt bulunamadı" in page_text:
                    if "Kayıt bulunamadı" in page_text:
                        result["durum"] = "KAYIT BULUNAMADI"
                        result["renk"] = "red"
                    else:
                        d_match = re.search(r"Durum\n(.+)", page_text)
                        if d_match: result["durum"] = d_match.group(1).strip()
                        
                        k_match = re.search(r"Kaynak\n(.+)", page_text)
                        if k_match: result["kaynak"] = k_match.group(1).strip()
                        
                        t_match = re.search(r"Tarihi\n(.+)", page_text)
                        if t_match: result["tarih"] = t_match.group(1).strip()
                        
                        m_match = re.search(r"Model Bilgileri\n(.+)", page_text) or re.search(r"Marka/Model\n(.+)", page_text)
                        if m_match: result["model"] = m_match.group(1).strip()

                        if result["durum"]:
                            if "KAYITLI" in result["durum"].upper(): result["renk"] = "green"
                            elif "ÇALINTI" in result["durum"].upper(): result["renk"] = "red"
                            else: result["renk"] = "orange"

                    success_flag = True
                    break 
            except Exception as e:
                continue 

        if success_flag:
            return result
        else:
            return {"error": "Sonuç alınamadı."}

    except Exception as e:
        result["error"] = str(e)
    finally:
        if driver: driver.quit()
    return result

# --- FastAPI KURULUM ---
app = FastAPI(title="AI IMEI Checker API & Admin Panel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ARAYÜZLER İÇİN HTML KODLARI ---

# 1. Kullanıcı Sorgu Ekranı
HTML_USER = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI IMEI Sorgulama Merkezi</title>
    <style>
        * { box-sizing: border-box; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #f0f2f5; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
        .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); width: 100%; max-width: 500px; }
        h2 { text-align: center; color: #333; margin-top: 0; }
        .input-group { margin-bottom: 20px; }
        label { font-weight: bold; color: #555; display: block; margin-bottom: 8px; }
        input { width: 100%; padding: 12px; border: 2px solid #ddd; border-radius: 8px; font-size: 16px; outline: none; transition: border 0.3s; }
        input:focus { border-color: #007bff; }
        button { width: 100%; padding: 14px; background: #007bff; color: white; font-size: 16px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; transition: background 0.3s; }
        button:hover { background: #0056b3; }
        button:disabled { background: #aaa; cursor: not-allowed; }
        #loading { display: none; text-align: center; margin-top: 15px; font-weight: bold; color: #007bff; }
        .result-box { margin-top: 25px; padding: 20px; border-radius: 8px; display: none; border-left: 5px solid; }
        .success { background-color: #e8f5e9; border-color: #2e7d32; color: #1b5e20; }
        .danger { background-color: #ffebee; border-color: #c62828; color: #b71c1c; }
        .warning { background-color: #fff8e1; border-color: #f57f17; color: #f57f17; }
        .result-item { margin-bottom: 8px; }
        .result-item b { display: inline-block; width: 110px; }
        .footer-link { text-align: center; margin-top: 20px; font-size: 14px; }
        .footer-link a { color: #666; text-decoration: none; }
        .footer-link a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🤖 AI IMEI Sorgulama</h2>
        <div class="input-group">
            <label>IMEI Numarası:</label>
            <input type="text" id="imei" placeholder="15 Haneli IMEI Giriniz..." maxlength="15" onkeypress="return event.charCode >= 48 && event.charCode <= 57">
        </div>
        <div class="input-group">
            <label>API Anahtarı:</label>
            <input type="password" id="apikey" placeholder="Size verilen key'i girin...">
        </div>
        <button id="btn" onclick="sorgula()">Sorgula 🚀</button>
        <div id="loading">Arka planda analiz ediliyor... Lütfen Bekleyin ⏳</div>
        <div id="result" class="result-box"></div>
        <div class="footer-link"><a href="/admin">Yönetici Paneline Git</a></div>
    </div>

    <script>
        async function sorgula() {
            const imei = document.getElementById('imei').value;
            const apiKey = document.getElementById('apikey').value;
            const btn = document.getElementById('btn');
            const loading = document.getElementById('loading');
            const resultDiv = document.getElementById('result');

            if (imei.length < 14) { alert("Lütfen geçerli bir IMEI girin!"); return; }
            if (!apiKey) { alert("Lütfen API Key girin!"); return; }

            btn.disabled = true; loading.style.display = "block"; resultDiv.style.display = "none";

            try {
                const response = await fetch('/api/check-imei', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'x-api-key': apiKey },
                    body: JSON.stringify({ imei: imei })
                });

                const data = await response.json();
                loading.style.display = "none"; btn.disabled = false; resultDiv.style.display = "block";

                if (!data.success) {
                    resultDiv.className = "result-box danger";
                    resultDiv.innerHTML = `<div class="result-item"><b>Hata:</b> ${data.error}</div>`;
                    return;
                }

                if (data.renk === "green") resultDiv.className = "result-box success";
                else if (data.renk === "red") resultDiv.className = "result-box danger";
                else resultDiv.className = "result-box warning";

                resultDiv.innerHTML = `
                    <div class="result-item"><b>📱 IMEI:</b> ${data.imei}</div>
                    <div class="result-item"><b>📌 Durum:</b> ${data.durum || '-'}</div>
                    <div class="result-item"><b>🏷️ Model:</b> ${data.model || '-'}</div>
                    <div class="result-item"><b>🏢 Kaynak:</b> ${data.kaynak || '-'}</div>
                    <div class="result-item"><b>📅 Tarih:</b> ${data.tarih || '-'}</div>
                    <div class="result-item" style="margin-top:10px; font-size:12px;"><i>Kalan Krediniz: ${data.remaining_credits}</i></div>
                `;
            } catch (error) {
                loading.style.display = "none"; btn.disabled = false;
                resultDiv.className = "result-box danger";
                resultDiv.innerHTML = "Sunucuya bağlanılamadı."; resultDiv.style.display = "block";
            }
        }
    </script>
</body>
</html>
"""

# 2. Yönetim Paneli Ekranı
HTML_ADMIN = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistem Yönetim Paneli</title>
    <style>
        * { box-sizing: border-box; font-family: 'Segoe UI', sans-serif; }
        body { background-color: #f4f7f6; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; background: #2c3e50; color: white; padding: 15px 30px; border-radius: 8px; margin-bottom: 20px;}
        .container { display: flex; gap: 20px; flex-wrap: wrap; }
        .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); flex: 1; min-width: 300px; }
        .full-width { flex: 100%; }
        h3 { margin-top: 0; color: #34495e; border-bottom: 2px solid #eee; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
        th, td { text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }
        th { background-color: #f8f9fa; color: #333; }
        tr:hover { background-color: #f1f1f1; }
        .badge-green { background: #2ecc71; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
        .badge-red { background: #e74c3c; color: white; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
        .input-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; font-size: 14px; }
        input { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { background: #3498db; color: white; border: none; padding: 10px 15px; border-radius: 4px; cursor: pointer; font-weight: bold; width: 100%; }
        button:hover { background: #2980b9; }
        #login-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(44, 62, 80, 0.95); display: flex; justify-content: center; align-items: center; z-index: 1000; }
        .login-box { background: white; padding: 30px; border-radius: 8px; width: 350px; text-align: center; }
    </style>
</head>
<body>
    <div id="login-overlay">
        <div class="login-box">
            <h2 style="margin-top:0;">Admin Girişi</h2>
            <input type="password" id="adminPass" placeholder="Yönetici Şifrenizi Girin..." style="margin-bottom: 15px;">
            <button onclick="login()">Giriş Yap</button>
            <p id="loginError" style="color: red; display: none; margin-top: 10px; font-size: 14px;">Şifre Hatalı!</p>
        </div>
    </div>

    <div class="header">
        <h2>⚙️ Yönetim Paneli</h2>
        <a href="/" style="color: white; text-decoration: none;">Ana Sayfaya Dön</a>
    </div>

    <div class="container">
        <div class="card" style="flex: 0.3;">
            <h3>🔑 Yeni API Key Üret</h3>
            <div class="input-group">
                <label>Müşteri/Kullanıcı Adı:</label>
                <input type="text" id="newOwner" placeholder="Örn: Ahmet Bey">
            </div>
            <div class="input-group">
                <label>Sorgu Limiti (Kredi):</label>
                <input type="number" id="newCredits" placeholder="Örn: 1000">
            </div>
            <button onclick="createKey()">Oluştur ve Kaydet</button>
            <p id="keyResult" style="color: green; font-weight: bold; margin-top: 10px; word-break: break-all;"></p>
        </div>

        <div class="card" style="flex: 0.7;">
            <h3>📋 Aktif Kullanıcılar ve Kotalar</h3>
            <table>
                <thead>
                    <tr>
                        <th>Müşteri</th>
                        <th>API Key</th>
                        <th>Kalan Limit</th>
                        <th>Kullanılan</th>
                        <th>Oluşturulma</th>
                    </tr>
                </thead>
                <tbody id="keysTable">
                    </tbody>
            </table>
        </div>

        <div class="card full-width">
            <h3>📊 Sistem Sorgu Logları (Son İşlemler)</h3>
            <table>
                <thead>
                    <tr>
                        <th>Tarih / Saat</th>
                        <th>Müşteri</th>
                        <th>API Key</th>
                        <th>Sorgulanan IMEI</th>
                        <th>Sonuç</th>
                        <th>Kalan Kredisi</th>
                    </tr>
                </thead>
                <tbody id="logsTable">
                    </tbody>
            </table>
        </div>
    </div>

    <script>
        let sessionPass = "";

        async function login() {
            const pass = document.getElementById('adminPass').value;
            // Şifreyi doğrulamak için verileri çekmeyi deneriz
            const res = await fetch('/api/admin/data', { headers: { 'x-admin-key': pass } });
            if(res.ok) {
                sessionPass = pass;
                document.getElementById('login-overlay').style.display = "none";
                loadData();
            } else {
                document.getElementById('loginError').style.display = "block";
            }
        }

        async function loadData() {
            const res = await fetch('/api/admin/data', { headers: { 'x-admin-key': sessionPass } });
            const data = await res.json();
            
            // Keyleri Doldur
            let keysHtml = "";
            for (const [key, info] of Object.entries(data.keys)) {
                let displayKey = key.length > 15 ? key.substring(0, 10) + "***" : key;
                let badge = info.credits > 0 ? `<span class="badge-green">${info.credits}</span>` : `<span class="badge-red">Bitti</span>`;
                keysHtml += `<tr>
                    <td><b>${info.owner}</b></td>
                    <td style="font-family: monospace;">${displayKey}</td>
                    <td>${badge}</td>
                    <td>${info.total_used} Sorgu</td>
                    <td>${info.created_at}</td>
                </tr>`;
            }
            document.getElementById('keysTable').innerHTML = keysHtml;

            // Logları Doldur
            let logsHtml = "";
            data.logs.forEach(log => {
                let statusBadge = log.status.includes("Başarılı") ? "badge-green" : "badge-red";
                logsHtml += `<tr>
                    <td>${log.time}</td>
                    <td>${log.owner}</td>
                    <td style="font-family: monospace;">${log.key.substring(0,6)}***</td>
                    <td><b>${log.imei}</b></td>
                    <td><span class="${statusBadge}">${log.status}</span></td>
                    <td>${log.kredi_kalan}</td>
                </tr>`;
            });
            document.getElementById('logsTable').innerHTML = logsHtml;
        }

        async function createKey() {
            const owner = document.getElementById('newOwner').value;
            const credits = document.getElementById('newCredits').value;

            if(!owner || !credits) return alert("Lütfen isim ve kredi miktarını girin!");

            const res = await fetch('/api/admin/create-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-admin-key': sessionPass },
                body: JSON.stringify({ owner: owner, credits: parseInt(credits) })
            });

            const data = await res.json();
            if(data.success) {
                document.getElementById('keyResult').innerHTML = `Yeni Key: <br> <b>${data.key}</b>`;
                document.getElementById('newOwner').value = "";
                document.getElementById('newCredits').value = "";
                loadData(); // Tabloları yenile
            }
        }
    </script>
</body>
</html>
"""

# --- ROUTERLAR ---

@app.get("/", response_class=HTMLResponse)
def get_user_interface():
    return HTMLResponse(content=HTML_USER, status_code=200)

@app.get("/admin", response_class=HTMLResponse)
def get_admin_interface():
    return HTMLResponse(content=HTML_ADMIN, status_code=200)

async def verify_key(x_api_key: str = Header(...)):
    if x_api_key not in API_DB:
        raise HTTPException(status_code=401, detail="Geçersiz API Anahtarı")
    return x_api_key

async def verify_admin(x_admin_key: str = Header(...)):
    if x_admin_key != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Yetkisiz Erişim")
    return True

# --- API ENDPOINTLERİ ---

@app.post("/api/check-imei", response_model=IMEIResponse)
async def check_imei_post(body: IMEIRequest, x_api_key: str = Depends(verify_key)):
    async with BROWSER_LOCK:
        imei = body.imei.strip()
        if len(imei) == 14: imei += calculate_luhn(imei)
        
        # Kredi Kontrolü
        if API_DB[x_api_key]["credits"] <= 0:
            # Logla (Başarısız)
            QUERY_LOGS.insert(0, {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "key": x_api_key, "owner": API_DB[x_api_key]["owner"], "imei": imei,
                "status": "HATA: Yetersiz Kredi", "kredi_kalan": 0
            })
            return {"success": False, "imei": imei, "error": "Krediniz bitmiştir.", "remaining_credits": 0}

        # Sorguyu Yap
        data = fetch_imei_data(imei)
        
        if data["error"]:
            return {"success": False, "imei": imei, "error": data["error"], "remaining_credits": API_DB[x_api_key]["credits"]}

        # Krediyi düş, kullanımı artır
        API_DB[x_api_key]["credits"] -= 1
        API_DB[x_api_key]["total_used"] += 1
        kalan = API_DB[x_api_key]["credits"]

        # LOGU VERİTABANINA YAZ
        durum_text = "Başarılı" if data["durum"] != "KAYIT BULUNAMADI" else "Kayıt Bulunamadı"
        QUERY_LOGS.insert(0, {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "key": x_api_key,
            "owner": API_DB[x_api_key]["owner"],
            "imei": imei,
            "status": durum_text,
            "kredi_kalan": kalan
        })

        # Liste çok uzamasın diye son 100 kaydı tut
        if len(QUERY_LOGS) > 100: QUERY_LOGS.pop()

        return {
            "success": True,
            "imei": imei,
            "durum": data["durum"],
            "model": data["model"],
            "kaynak": data["kaynak"],
            "tarih": data["tarih"],
            "renk": data["renk"],
            "remaining_credits": kalan
        }

# --- ADMIN API ENDPOINTLERİ ---

@app.get("/api/admin/data")
async def get_admin_data(is_admin: bool = Depends(verify_admin)):
    # Panel için gerekli tüm verileri yolla
    return {"keys": API_DB, "logs": QUERY_LOGS}

@app.post("/api/admin/create-key")
async def create_new_key(req: AdminCreateKeyRequest, is_admin: bool = Depends(verify_admin)):
    # Yeni eşsiz API Key üret
    new_key = "key-" + str(uuid.uuid4()).replace("-", "")[:12]
    
    API_DB[new_key] = {
        "owner": req.owner,
        "credits": req.credits,
        "total_used": 0,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    return {"success": True, "key": new_key}

# --- SİSTEMİ BAŞLAT ---
if __name__ == "__main__":
    import os
    print("\n" + "="*50)
    print("🚀 SİSTEM HAYALET MODDA (HEADLESS) BAŞLADI!")
    print("🌐 SORGULAMA EKRANI : http://127.0.0.1:8000")
    print("⚙️  YÖNETİM PANELİ  : http://127.0.0.1:8000/admin")
    print(f"🔑 ADMIN ŞİFRESİ    : {ADMIN_PASSWORD}")
    print("="*50 + "\n")
    
    # Render'ın dinamik portunu al, yoksa 8000 kullan
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
