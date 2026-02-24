import uvicorn
import asyncio
import os
import uuid
import base64
import time
import re
from datetime import datetime
from typing import Optional, List, Dict

from fastapi import FastAPI, Header, HTTPException, Body, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import google.generativeai as genai

# ==============================================================================
# --- KONFİGÜRASYON & VERİTABANI SİMÜLASYONU ---
# ==============================================================================
GOOGLE_API_KEY = "AIzaSyCZZOiGEx9M-8wYKbl2LJWhrS6esx3sJr4"

# Gerçek projede buralar SQLite/PostgreSQL'e bağlanmalıdır.
# Admin Kullanıcıları: {username: password}
ADMINS_DB: Dict[str, str] = {
    "admin": "admin123" 
}

# API Keyler: {key: {owner, credits, used, status, created_at}}
API_DB: Dict[str, Dict] = {
    "patron_sensin": {
        "owner": "Kurucu (Sınırsız)", 
        "credits": 999999, 
        "total_used": 0, 
        "status": "active", 
        "created_at": "2026-01-01"
    }
}

QUERY_LOGS: List[Dict] = []
active_model = None

# ==============================================================================
# --- LUHN ALGORİTMASI (GÜVENLİK VE TAMAMLAMA) ---
# ==============================================================================

def is_luhn_valid(imei: str) -> bool:
    """IMEI numarasının matematiksel olarak geçerli olup olmadığını kontrol eder."""
    if len(imei) != 15 or not imei.isdigit(): return False
    digits = [int(d) for d in imei]
    checksum = digits[-1]
    payload = digits[:-1]
    total = 0
    for i, digit in enumerate(reversed(payload)):
        if i % 2 == 0:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else: total += digit
    return (10 - (total % 10)) % 10 == checksum

def get_luhn_checksum(imei_14: str) -> str:
    """14 haneli IMEI için 15. kontrol hanesini hesaplar."""
    digits = [int(d) for d in imei_14]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else: total += digit
    return str((10 - (total % 10)) % 10)

# ==============================================================================
# --- AI & ROBOT MOTORU (GELİŞMİŞ VERİ ÇEKME) ---
# ==============================================================================

def setup_ai_model():
    global active_model
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        active_model = genai.GenerativeModel("gemini-1.5-flash")
    except: pass

setup_ai_model()
BROWSER_LOCK = asyncio.Lock()

def solve_captcha(base64_string):
    try:
        if "base64," in base64_string: base64_string = base64_string.split("base64,")[1]
        img_data = base64.b64decode(base64_string)
        prompt = "Bu resimdeki güvenlik kodunu sadece harf ve rakam olarak oku. Boşluk bırakma."
        response = active_model.generate_content([prompt, {"mime_type": "image/png", "data": img_data}])
        return re.sub(r'\s+', '', response.text.strip())
    except: return None

def fetch_imei_data(target_imei: str):
    driver = None
    result = {
        "durum": None, "model": None, "kaynak": None, 
        "tarih": None, "renk": "orange", "error": None
    }
    try:
        options = uc.ChromeOptions()
        # --- BÜYÜ BURADA: ANTI-BOT GÜVENLİK DUVARI DELİCİ AYARLAR ---
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled") # Ben bot değilim komutu
        options.add_argument("--disable-infobars")
        
        # Rastgele User-Agent atayarak her seferinde farklı bir PC gibi davranıyoruz
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
        ]
        options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        # Tarayıcıyı başlat
        driver = uc.Chrome(options=options, version_main=114) # Render'da sürüm uyuşmazlığı olmaması için esneklik
        
        # WebDriver gizleme (Cloudflare/F5 aşmak için zorunlu)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
            """
        })
        
        driver.set_page_load_timeout(30) # Sayfa 30 saniyede açılmazsa patlasın (Asılı kalmasın)
        wait = WebDriverWait(driver, 20)
        
        # E-Devlet'e giriş
        driver.get("https://www.turkiye.gov.tr/imei-sorgulama")
        
        # Rastgele insanvari bekleme (Botların saniyesinde işlem yapmasını WAF yakalar)
        time.sleep(random.uniform(1.5, 3.0))
        
        # IMEI Kutusunu bul ve yaz
        imei_input = wait.until(EC.presence_of_element_located((By.ID, "txtImei")))
        # İnsan gibi tek tek yazma simülasyonu
        for digit in target_imei:
            imei_input.send_keys(digit)
            time.sleep(random.uniform(0.05, 0.2))
        
        # Captcha var mı diye kontrol et
        time.sleep(1)
        captcha_imgs = driver.find_elements(By.CLASS_NAME, "captchaImage")
        if captcha_imgs:
            code = solve_captcha(captcha_imgs[0].screenshot_as_base64)
            if code: 
                # Harfleri büyük/küçük rastgele mi yazıyor diye e-devlet anlamasın diye temizle
                clean_code = code.replace(" ", "").strip()
                driver.find_element(By.NAME, "captcha_name").send_keys(clean_code)
        
        # Çerez uyarısını kapat (Tıklamayı engellememesi için)
        driver.execute_script("var c=document.querySelector('.cookie-policy'); if(c) c.remove();")
        
        # Butona tıkla
        submit_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.submitButton")))
        driver.execute_script("arguments[0].scrollIntoView();", submit_btn) # Önce butona kaydır
        time.sleep(0.5)
        submit_btn.click() # Script ile değil gerçek tıklama (Bot korumasını aşar)
        
        # Sonucu bekle
        time.sleep(random.uniform(3.0, 4.5))
        page_text = driver.find_element(By.TAG_NAME, "body").text
        
        if "Kayıt bulunamadı" in page_text:
            result["durum"] = "KAYIT BULUNAMADI"; result["renk"] = "red"
        elif "Durum" in page_text and "Marka/Model" in page_text:
            # --- DETAYLI VERİ AYIKLAMA ---
            d_match = re.search(r"Durum\n(.+)", page_text)
            if d_match: result["durum"] = d_match.group(1).strip()
            
            m_match = re.search(r"Model Bilgileri\n(.+)", page_text) or re.search(r"Marka/Model\n(.+)", page_text)
            if m_match: result["model"] = m_match.group(1).strip()
            
            k_match = re.search(r"Kaynak\n(.+)", page_text)
            if k_match: result["kaynak"] = k_match.group(1).strip()
            
            t_match = re.search(r"Sorgulama Tarihi\n(.+)", page_text)
            if t_match: result["tarih"] = t_match.group(1).strip()

            if result["durum"]:
                if "KAYITLI" in result["durum"].upper(): result["renk"] = "green"
                elif "ÇALINTI" in result["durum"].upper() or "YOLCU" in result["durum"].upper() or "KLON" in result["durum"].upper(): result["renk"] = "red"
                else: result["renk"] = "orange"
        else:
            result["error"] = "Bot Koruması Aşılamadı veya E-Devlet Yanıt Vermiyor."
            # Render loglarında görmek için hatayı ekrana bas
            print("--- WAF / BOT ENGELİ ---")
            print(f"Mevcut URL: {driver.current_url}")
            print(f"Sayfa Başlığı: {driver.title}")
            
    except Exception as e: 
        result["error"] = f"Tarayıcı Hatası: {str(e)}"
        print(f"KRİTİK CATCH: {str(e)}")
    finally:
        if driver: driver.quit()
        
    return result

# ==============================================================================
# --- FastAPI APP & MODELLER ---
# ==============================================================================

app = FastAPI(title="UT-Professional IMEI SaaS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class IMEIReq(BaseModel): imei: str
class AdminUserReq(BaseModel): username: str; password: str
class KeyActionReq(BaseModel): key: Optional[str] = ""; owner: Optional[str] = ""; credits: Optional[int] = 0; action: str

# ==============================================================================
# --- MODERN DASHBOARD UI (SIDEBAR + SPA) ---
# ==============================================================================

HTML_USER = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8"><title>UT-IMEI | Sorgulama Merkezi</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #f8fafc; font-family: 'Segoe UI', sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; }
        .sorgu-card { background: white; border-radius: 20px; box-shadow: 0 15px 35px rgba(0,0,0,0.05); padding: 40px; width: 100%; max-width: 500px; border: 1px solid #e2e8f0; }
        .btn-primary { background: #6366f1; border: none; padding: 14px; border-radius: 12px; font-weight: 600; }
        .res-box { border-left: 5px solid; transition: 0.3s; display: none; }
        .success { background: #f0fdf4; border-color: #22c55e; color: #166534; }
        .danger { background: #fef2f2; border-color: #ef4444; color: #991b1b; }
        .warning { background: #fffbeb; border-color: #f59e0b; color: #92400e; }
    </style>
</head>
<body>
    <div class="sorgu-card">
        <h3 class="text-center fw-bold mb-4">IMEI Detaylı Sorgu</h3>
        <div class="mb-3">
            <label class="small fw-bold text-muted">IMEI NUMARASI</label>
            <input type="text" id="imei" class="form-control form-control-lg" placeholder="14 veya 15 Hane">
        </div>
        <div class="mb-4">
            <label class="small fw-bold text-muted">API KEY</label>
            <input type="password" id="key" class="form-control" placeholder="Anahtarınızı girin">
        </div>
        <button class="btn btn-primary w-100" id="btn" onclick="sorgula()">SORGULA 🚀</button>
        <div id="loading" class="text-center mt-3 small text-primary" style="display:none;">AI Captcha çözülüyor, lütfen bekleyin...</div>
        
        <div id="res" class="res-box mt-4 p-3 rounded"></div>
        
        <div class="text-center mt-4"><a href="/admin" class="text-muted small text-decoration-none">Yönetim Paneli</a></div>
    </div>
    <script>
        async function sorgula() {
            const btn = document.getElementById('btn'); const res = document.getElementById('res');
            res.style.display = 'none'; btn.disabled = true; document.getElementById('loading').style.display = 'block';
            try {
                const r = await fetch('/api/check-imei', {
                    method: 'POST', headers: {'Content-Type':'application/json', 'x-api-key': document.getElementById('key').value},
                    body: JSON.stringify({imei: document.getElementById('imei').value})
                });
                const d = await r.json();
                document.getElementById('loading').style.display = 'none'; btn.disabled = false;
                if(d.success) {
                    res.style.display = 'block';
                    res.className = 'res-box mt-4 p-3 rounded ' + (d.renk == 'green' ? 'success' : (d.renk == 'red' ? 'danger' : 'warning'));
                    res.innerHTML = `
                        <div class="mb-1"><b>Durum:</b> ${d.durum}</div>
                        <div class="mb-1"><b>Model:</b> ${d.model || '-'}</div>
                        <div class="mb-1"><b>Kaynak:</b> ${d.kaynak || '-'}</div>
                        <div class="small mt-2 text-muted">Kalan Kredi: ${d.remaining_credits}</div>
                    `;
                } else { alert('HATA: ' + d.error); }
            } catch(e) { alert('Sistem hatası!'); btn.disabled = false; }
        }
    </script>
</body>
</html>
"""

HTML_ADMIN = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8"><title>UT-Tool | Admin</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --sb-bg: #0f172a; --primary: #6366f1; }
        body { background: #f1f5f9; font-family: 'Inter', sans-serif; }
        #sidebar { width: 260px; height: 100vh; position: fixed; background: var(--sb-bg); color: white; transition: 0.3s; z-index: 1000; }
        #content { margin-left: 260px; padding: 40px; transition: 0.3s; }
        .nav-link { color: #94a3b8; padding: 15px 25px; border-left: 4px solid transparent; cursor: pointer; transition: 0.2s; }
        .nav-link:hover, .nav-link.active { color: white; background: #1e293b; border-left-color: var(--primary); }
        .card { border: none; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.03); }
        .stat-card { padding: 25px; border-radius: 15px; color: white; position: relative; }
        #login-screen { position: fixed; inset: 0; background: var(--sb-bg); z-index: 2000; display: flex; align-items: center; justify-content: center; }
        .badge-active { background: #dcfce7; color: #166534; } .badge-banned { background: #fee2e2; color: #991b1b; }
    </style>
</head>
<body>
    <div id="login-screen">
        <div class="card p-4 shadow-lg" style="width: 380px;">
            <h3 class="text-center fw-bold mb-4">UT-TOOL LOGIN</h3>
            <input type="text" id="admU" class="form-control mb-3" placeholder="Kullanıcı Adı">
            <input type="password" id="admP" class="form-control mb-4" placeholder="Şifre">
            <button class="btn btn-primary w-100 py-2 fw-bold" onclick="tryLogin()">GİRİŞ YAP</button>
        </div>
    </div>

    <div id="sidebar">
        <div class="p-4 mb-4 border-bottom border-secondary text-center"><h4 class="fw-bold">UT-SaaS</h4></div>
        <nav class="nav flex-column">
            <a class="nav-link active" onclick="navTo('dash')"><i class="fa fa-gauge me-2"></i> Dashboard</a>
            <a class="nav-link" onclick="navTo('keys')"><i class="fa fa-key me-2"></i> API Keyler</a>
            <a class="nav-link" onclick="navTo('admins')"><i class="fa fa-user-shield me-2"></i> Admin Ayarları</a>
            <a class="nav-link" onclick="navTo('logs')"><i class="fa fa-list me-2"></i> Log Kayıtları</a>
            <a href="/" class="nav-link mt-5 text-danger"><i class="fa fa-power-off me-2"></i> Güvenli Çıkış</a>
        </nav>
    </div>

    <div id="content">
        <div id="v-dash" class="view">
            <h2 class="fw-bold mb-4 text-dark">Sistem Özeti</h2>
            <div class="row">
                <div class="col-md-4"><div class="stat-card bg-primary"><h6>Toplam Sorgu</h6><h2 id="s-queries">0</h2></div></div>
                <div class="col-md-4"><div class="stat-card bg-success"><h6>Aktif Keyler</h6><h2 id="s-keys">0</h2></div></div>
                <div class="col-md-4"><div class="stat-card bg-dark"><h6>Durum</h6><h2>AKTİF</h2></div></div>
            </div>
            <div class="card p-4 mt-4">
                <h5 class="fw-bold mb-3 text-muted">Son İşlemler (Canlı)</h5>
                <table class="table"><tbody id="dash-logs"></tbody></table>
            </div>
        </div>

        <div id="v-keys" class="view" style="display:none;">
            <div class="d-flex justify-content-between mb-4">
                <h2 class="fw-bold">Müşteri Keyleri</h2>
                <button class="btn btn-primary" onclick="keyModal()"><i class="fa fa-plus"></i> Key Üret</button>
            </div>
            <div class="card overflow-hidden"><table class="table mb-0">
                <thead class="table-light"><tr><th>Müşteri</th><th>Key</th><th>Kredi</th><th>Kullanım</th><th>Durum</th><th>İşlem</th></tr></thead>
                <tbody id="keyTable"></tbody>
            </table></div>
        </div>

        <div id="v-admins" class="view" style="display:none;">
            <h2 class="fw-bold mb-4">Admin Yönetimi</h2>
            <div class="row">
                <div class="col-md-5">
                    <div class="card p-4">
                        <h5 class="fw-bold mb-3">Admin Ekle / Şifre Değiştir</h5>
                        <input type="text" id="newAU" class="form-control mb-3" placeholder="Kullanıcı Adı">
                        <input type="password" id="newAP" class="form-control mb-4" placeholder="Şifre">
                        <button class="btn btn-dark w-100 fw-bold" onclick="saveAdmin()">KAYDET</button>
                    </div>
                </div>
                <div class="col-md-7"><div class="card p-4"><ul class="list-group list-group-flush" id="adminList"></ul></div></div>
            </div>
        </div>

        <div id="v-logs" class="view" style="display:none;">
            <h2 class="fw-bold mb-4">Sorgu Geçmişi</h2>
            <div class="card overflow-auto" style="max-height: 600px;"><table class="table mb-0"><thead><tr><th>Saat</th><th>Müşteri</th><th>IMEI</th><th>Sonuç</th><th>IP</th></tr></thead><tbody id="fullLogs"></tbody></table></div>
        </div>
    </div>

    <script>
        let auth = { u: '', p: '' };
        function navTo(id) {
            document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
            document.getElementById('v-' + id).style.display = 'block';
            event.target.classList.add('active'); refresh();
        }
        async function tryLogin() {
            const u = document.getElementById('admU').value; const p = document.getElementById('admP').value;
            const r = await fetch('/api/admin/verify', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({username: u, password: p})});
            if(r.ok) { auth = {u, p}; document.getElementById('login-screen').style.display = 'none'; refresh(); } else { alert('HATA!'); }
        }
        async function refresh() {
            const r = await fetch('/api/admin/data', { headers: {'x-adm-u': auth.u, 'x-adm-p': auth.p} });
            const d = await r.json();
            document.getElementById('s-queries').innerText = d.logs.length;
            document.getElementById('s-keys').innerText = Object.values(d.keys).filter(k => k.status == 'active').length;
            
            let kHtml = ''; for(const [k, info] of Object.entries(d.keys)) {
                kHtml += `<tr><td><b>${info.owner}</b></td><td><small>${k}</small></td><td class="text-primary fw-bold">${info.credits}</td><td>${info.total_used}</td>
                    <td><span class="badge ${info.status == 'active' ? 'badge-active' : 'badge-banned'}">${info.status}</span></td>
                    <td><button class="btn btn-sm btn-outline-primary" onclick="upK('${k}', 'add')">+500</button>
                    <button class="btn btn-sm btn-outline-warning" onclick="upK('${k}', 'toggle')">Durum</button>
                    <button class="btn btn-sm btn-outline-danger" onclick="upK('${k}', 'del')"><i class="fa fa-trash"></i></button></td></tr>`;
            }
            document.getElementById('keyTable').innerHTML = kHtml;
            let aHtml = ''; for(const [u, p] of Object.entries(d.admins)) {
                aHtml += `<li class="list-group-item d-flex justify-content-between"><b>${u}</b> <button class="btn btn-sm text-danger" onclick="delA('${u}')">SİL</button></li>`;
            }
            document.getElementById('adminList').innerHTML = aHtml;
            let lHtml = ''; d.logs.forEach(l => lHtml += `<tr><td>${l.time}</td><td>${l.owner}</td><td>${l.imei}</td><td>${l.status}</td><td><small>${l.ip}</small></td></tr>`);
            document.getElementById('fullLogs').innerHTML = lHtml; document.getElementById('dash-logs').innerHTML = lHtml.split('</tr>').slice(0,10).join('</tr>');
        }
        async function keyModal() {
            const owner = prompt("Müşteri Adı:"); const credits = prompt("Kredi:", "100");
            if(owner) { await fetch('/api/admin/key/action', { method: 'POST', headers: {'Content-Type':'application/json', 'x-adm-u': auth.u, 'x-adm-p': auth.p}, body: JSON.stringify({owner, credits: parseInt(credits), action: 'create'})}); refresh(); }
        }
        async function upK(key, action) {
            await fetch('/api/admin/key/action', { method: 'POST', headers: {'Content-Type':'application/json', 'x-adm-u': auth.u, 'x-adm-p': auth.p}, body: JSON.stringify({key, action})}); refresh();
        }
        async function saveAdmin() {
            const username = document.getElementById('newAU').value; const password = document.getElementById('newAP').value;
            await fetch('/api/admin/user/manage', { method: 'POST', headers: {'Content-Type':'application/json', 'x-adm-u': auth.u, 'x-adm-p': auth.p}, body: JSON.stringify({username, password})}); refresh();
        }
    </script>
</body>
</html>
"""

# ==============================================================================
# --- API ENDPOINTLERİ ---
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def home(): return HTML_USER

@app.get("/admin", response_class=HTMLResponse)
def admin_portal(): return HTML_ADMIN

async def verify_admin(x_adm_u: str = Header(None), x_adm_p: str = Header(None)):
    if x_adm_u not in ADMINS_DB or ADMINS_DB[x_adm_u] != x_adm_p: raise HTTPException(status_code=401)
    return True

@app.post("/api/admin/verify")
def auth_login(req: AdminUserReq):
    if req.username in ADMINS_DB and ADMINS_DB[req.username] == req.password: return {"ok": True}
    raise HTTPException(status_code=401)

@app.get("/api/admin/data")
def get_admin_data(v=Depends(verify_admin)):
    return {"keys": API_DB, "logs": QUERY_LOGS, "admins": ADMINS_DB}

@app.post("/api/admin/user/manage")
def manage_adm(req: AdminUserReq, v=Depends(verify_admin)):
    ADMINS_DB[req.username] = req.password; return {"ok": True}

@app.post("/api/admin/key/action")
def manage_keys(req: KeyActionReq, v=Depends(verify_admin)):
    if req.action == "create":
        nk = "key-" + uuid.uuid4().hex[:12]
        API_DB[nk] = {"owner": req.owner, "credits": req.credits, "total_used": 0, "status": "active", "created_at": datetime.now().strftime("%Y-%m-%d")}
    elif req.key in API_DB:
        if req.action == "del": del API_DB[req.key]
        elif req.action == "add": API_DB[req.key]["credits"] += 500
        elif req.action == "toggle": API_DB[req.key]["status"] = "banned" if API_DB[req.key]["status"] == "active" else "active"
    return {"ok": True}

# --- ANA SORGU ENDPOINTİ ---

@app.post("/api/check-imei")
async def check_imei(req: IMEIReq, x_api_key: str = Header(None), r: Request = None):
    # 1. Key Kontrolü
    if x_api_key not in API_DB or API_DB[x_api_key]["status"] != "active":
        raise HTTPException(status_code=401, detail="Geçersiz API Key")
    
    user = API_DB[x_api_key]
    if user["credits"] <= 0: return {"success": False, "error": "Bakiye yetersiz."}

    # 2. LUHN DOĞRULAMASI & TAMAMLAMA
    imei = req.imei.strip()
    if len(imei) == 14:
        imei += get_luhn_checksum(imei)
    elif len(imei) == 15:
        if not is_luhn_valid(imei): return {"success": False, "error": "Geçersiz IMEI (Luhn Hatası)"}
    else: return {"success": False, "error": "IMEI 14 veya 15 hane olmalıdır."}

    # 3. SORGU İŞLEMİ (BOT ÇALIŞIR)
    async with BROWSER_LOCK:
        data = fetch_imei_data(imei)
    
    # 4. LOGLAMA & SONUÇ
    if not data["error"]:
        user["credits"] -= 1; user["total_used"] += 1
        QUERY_LOGS.insert(0, {"time": datetime.now().strftime("%H:%M:%S"), "owner": user["owner"], "imei": imei, "status": data["durum"], "ip": r.client.host})
        if len(QUERY_LOGS) > 200: QUERY_LOGS.pop()
        return {"success": True, **data, "remaining_credits": user["credits"]}
    
    return {"success": False, "error": data["error"]}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
