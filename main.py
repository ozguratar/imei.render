import uvicorn
import uuid
import time
from datetime import datetime
from typing import Optional, List, Dict

from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from pydantic import BaseModel

# ==============================================================================
# --- KONFİGÜRASYON & VERİTABANI SİMÜLASYONU ---
# ==============================================================================

# Admin Kullanıcıları
ADMINS_DB: Dict[str, str] = {
    "admin": "admin123" 
}

# API Keyler
API_DB: Dict[str, Dict] = {
    "patron_sensin": {
        "owner": "Kurucu (Sınırsız)", 
        "credits": 999999, 
        "total_used": 150, 
        "status": "active", 
        "created_at": "2026-01-01"
    },
    "test_key_1": {
        "owner": "Bayi 1", 
        "credits": 500, 
        "total_used": 45, 
        "status": "active", 
        "created_at": "2026-02-10"
    }
}

# Örnek Log Verileri (Dashboard Grafikleri İçin)
QUERY_LOGS: List[Dict] = [
    {"time": "10:15:00", "owner": "Bayi 1", "imei": "358911111111111", "status": "KAYITLI", "ip": "192.168.1.1"},
    {"time": "10:20:00", "owner": "Kurucu (Sınırsız)", "imei": "358922222222222", "status": "KAYIT BULUNAMADI", "ip": "127.0.0.1"}
]

# ==============================================================================
# --- LUHN ALGORİTMASI ---
# ==============================================================================

def is_luhn_valid(imei: str) -> bool:
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
    digits = [int(d) for d in imei_14]
    total = 0
    for i, digit in enumerate(reversed(digits)):
        if i % 2 == 0:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else: total += digit
    return str((10 - (total % 10)) % 10)

# ==============================================================================
# --- MOCK API SORGUSU ---
# ==============================================================================

def mock_fetch_imei_data(target_imei: str):
    """
    Güvenlik politikaları gereği scraping işlemi kaldırılmıştır.
    Sistemin çalışmasını test etmek için simüle edilmiş yanıtlar döndürür.
    """
    time.sleep(1) # İşlem süresi simülasyonu
    
    if target_imei.startswith("35"):
        return {
            "durum": "IMEI NUMARASI KAYITLI",
            "model": "Marka: APPLE Model Bilgileri: iPhone 14 Pro",
            "kaynak": "İthalat yoluyla kaydedilen IMEI",
            "tarih": "01/01/2026",
            "renk": "green",
            "error": None
        }
    else:
        return {
            "durum": "KAYIT BULUNAMADI",
            "model": None,
            "kaynak": None,
            "tarih": None,
            "renk": "red",
            "error": None
        }

# ==============================================================================
# --- FastAPI APP & MODELLER ---
# ==============================================================================

app = FastAPI(title="UT-Professional IMEI SaaS")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class IMEIReq(BaseModel): imei: str
class AdminUserReq(BaseModel): username: str; password: str
class KeyActionReq(BaseModel): key: Optional[str] = ""; owner: Optional[str] = ""; credits: Optional[int] = 0; action: str

# ==============================================================================
# --- MODERN DASHBOARD UI ---
# ==============================================================================

HTML_USER = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UT-IMEI | Müşteri Paneli</title>
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
        <h3 class="text-center fw-bold mb-4">Sistem Sorgu Terminali</h3>
        <div class="mb-3">
            <label class="small fw-bold text-muted">IMEI NUMARASI</label>
            <input type="text" id="imei" class="form-control form-control-lg" placeholder="14 veya 15 Hane">
        </div>
        <div class="mb-4">
            <label class="small fw-bold text-muted">API ANAHTARI</label>
            <input type="password" id="key" class="form-control" placeholder="Anahtarınızı girin">
        </div>
        <button class="btn btn-primary w-100" id="btn" onclick="sorgula()">BAŞLAT</button>
        <div id="loading" class="text-center mt-3 small text-primary" style="display:none;">Sunucuya bağlanılıyor...</div>
        
        <div id="res" class="res-box mt-4 p-3 rounded"></div>
        
        <div class="text-center mt-4"><a href="/admin" class="text-muted small text-decoration-none">Yönetici Paneli</a></div>
    </div>
    <script>
        async function sorgula() {
            const btn = document.getElementById('btn'); 
            const res = document.getElementById('res');
            res.style.display = 'none'; 
            btn.disabled = true; 
            document.getElementById('loading').style.display = 'block';
            
            try {
                const r = await fetch('/api/check-imei', {
                    method: 'POST', 
                    headers: {'Content-Type':'application/json', 'x-api-key': document.getElementById('key').value},
                    body: JSON.stringify({imei: document.getElementById('imei').value})
                });
                const d = await r.json();
                
                document.getElementById('loading').style.display = 'none'; 
                btn.disabled = false;
                
                if(r.ok && d.success) {
                    res.style.display = 'block';
                    res.className = 'res-box mt-4 p-3 rounded ' + (d.renk == 'green' ? 'success' : (d.renk == 'red' ? 'danger' : 'warning'));
                    res.innerHTML = `
                        <div class="mb-1"><b>Durum:</b> ${d.durum}</div>
                        <div class="mb-1"><b>Model:</b> ${d.model || '-'}</div>
                        <div class="mb-1"><b>Kaynak:</b> ${d.kaynak || '-'}</div>
                        <div class="small mt-2 text-muted">Kalan Kredi: <b>${d.remaining_credits}</b></div>
                    `;
                } else { 
                    alert('Hata: ' + (d.error || d.detail || 'Bilinmeyen Hata')); 
                }
            } catch(e) { 
                alert('Bağlantı hatası!'); 
                document.getElementById('loading').style.display = 'none';
                btn.disabled = false; 
            }
        }
    </script>
</body>
</html>
"""

HTML_ADMIN = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UT-Tool | Yönetim Merkezi</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root { --sb-bg: #111827; --primary: #4f46e5; }
        body { background: #f3f4f6; font-family: 'Inter', sans-serif; }
        #sidebar { width: 260px; height: 100vh; position: fixed; background: var(--sb-bg); color: white; transition: 0.3s; z-index: 1000; }
        #content { margin-left: 260px; padding: 40px; transition: 0.3s; }
        .nav-link { color: #9ca3af; padding: 15px 25px; border-left: 4px solid transparent; cursor: pointer; transition: 0.2s; }
        .nav-link:hover, .nav-link.active { color: white; background: #1f2937; border-left-color: var(--primary); }
        .card { border: none; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 24px; }
        .stat-card { padding: 24px; border-radius: 12px; color: white; }
        #login-screen { position: fixed; inset: 0; background: var(--sb-bg); z-index: 2000; display: flex; align-items: center; justify-content: center; }
        .table th { font-weight: 600; color: #4b5563; }
        .badge-active { background: #dcfce7; color: #166534; } 
        .badge-banned { background: #fee2e2; color: #991b1b; }
    </style>
</head>
<body>
    <div id="login-screen">
        <div class="card p-4 shadow-lg" style="width: 400px; background: white;">
            <h3 class="text-center fw-bold mb-4" style="color: var(--sb-bg);">Yönetici Girişi</h3>
            <input type="text" id="admU" class="form-control mb-3" placeholder="Kullanıcı Adı">
            <input type="password" id="admP" class="form-control mb-4" placeholder="Şifre">
            <button class="btn btn-primary w-100 py-2 fw-bold" onclick="tryLogin()">GİRİŞ</button>
        </div>
    </div>

    <div id="sidebar">
        <div class="p-4 mb-4 text-center border-bottom border-secondary"><h4 class="fw-bold">UT-Admin</h4></div>
        <nav class="nav flex-column">
            <a class="nav-link active" onclick="navTo('dash')"><i class="fa fa-chart-pie me-2"></i> İstatistikler</a>
            <a class="nav-link" onclick="navTo('keys')"><i class="fa fa-key me-2"></i> Lisans Yönetimi</a>
            <a class="nav-link" onclick="navTo('logs')"><i class="fa fa-list-check me-2"></i> İşlem Kayıtları</a>
            <a href="/" class="nav-link mt-5 text-danger"><i class="fa fa-sign-out-alt me-2"></i> Çıkış Yap</a>
        </nav>
    </div>

    <div id="content">
        <div id="v-dash" class="view">
            <h2 class="fw-bold mb-4">Genel Durum</h2>
            <div class="row">
                <div class="col-md-4">
                    <div class="stat-card" style="background: linear-gradient(135deg, #4f46e5, #6366f1);">
                        <h6>Toplam Sorgu</h6>
                        <h2 id="s-queries" class="fw-bold mb-0">0</h2>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="stat-card" style="background: linear-gradient(135deg, #059669, #10b981);">
                        <h6>Aktif Müşteriler</h6>
                        <h2 id="s-keys" class="fw-bold mb-0">0</h2>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="stat-card" style="background: linear-gradient(135deg, #ea580c, #f59e0b);">
                        <h6>Toplam Kredi Kullanımı</h6>
                        <h2 id="s-credits" class="fw-bold mb-0">0</h2>
                    </div>
                </div>
            </div>
            
            <div class="row mt-4">
                <div class="col-md-8">
                    <div class="card p-4 h-100">
                        <h5 class="fw-bold mb-4">Kullanım Özeti</h5>
                        <canvas id="usageChart" height="100"></canvas>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card p-4 h-100">
                        <h5 class="fw-bold mb-4">Son İşlemler</h5>
                        <div id="dash-logs" class="small"></div>
                    </div>
                </div>
            </div>
        </div>

        <div id="v-keys" class="view" style="display:none;">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold mb-0">Lisans ve API Yönetimi</h2>
                <button class="btn btn-primary" onclick="keyModal()"><i class="fa fa-plus me-2"></i>Yeni Müşteri Ekle</button>
            </div>
            <div class="card">
                <div class="table-responsive">
                    <table class="table table-hover align-middle mb-0">
                        <thead class="table-light">
                            <tr>
                                <th>Müşteri Bilgisi</th>
                                <th>API Anahtarı</th>
                                <th>Bakiye</th>
                                <th>Kullanım</th>
                                <th>Durum</th>
                                <th>Oluşturulma</th>
                                <th class="text-end">İşlemler</th>
                            </tr>
                        </thead>
                        <tbody id="keyTable"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <div id="v-logs" class="view" style="display:none;">
            <h2 class="fw-bold mb-4">Sistem Kayıtları</h2>
            <div class="card">
                <div class="table-responsive" style="max-height: 70vh;">
                    <table class="table table-hover mb-0">
                        <thead class="table-light position-sticky top-0">
                            <tr>
                                <th>Zaman</th>
                                <th>Müşteri</th>
                                <th>Sorgulanan IMEI</th>
                                <th>Sonuç Durumu</th>
                                <th>IP Adresi</th>
                            </tr>
                        </thead>
                        <tbody id="fullLogs"></tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <script>
        let auth = { u: '', p: '' };
        let usageChartInstance = null;

        function navTo(id) {
            document.querySelectorAll('.view').forEach(v => v.style.display = 'none');
            document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
            document.getElementById('v-' + id).style.display = 'block';
            event.target.classList.add('active'); 
            refresh();
        }

        async function tryLogin() {
            const u = document.getElementById('admU').value; 
            const p = document.getElementById('admP').value;
            const r = await fetch('/api/admin/verify', { 
                method: 'POST', 
                headers: {'Content-Type':'application/json'}, 
                body: JSON.stringify({username: u, password: p})
            });
            if(r.ok) { 
                auth = {u, p}; 
                document.getElementById('login-screen').style.display = 'none'; 
                refresh(); 
            } else { 
                alert('Giriş Başarısız!'); 
            }
        }

        async function refresh() {
            const r = await fetch('/api/admin/data', { headers: {'x-adm-u': auth.u, 'x-adm-p': auth.p} });
            if(!r.ok) return;
            const d = await r.json();
            
            // Dashboard İstatistikleri
            document.getElementById('s-queries').innerText = d.logs.length;
            
            const activeKeys = Object.values(d.keys).filter(k => k.status === 'active');
            document.getElementById('s-keys').innerText = activeKeys.length;
            
            let totalUsage = 0;
            let chartLabels = [];
            let chartData = [];
            
            let kHtml = ''; 
            for(const [k, info] of Object.entries(d.keys)) {
                totalUsage += info.total_used;
                
                // Grafik verileri
                if(info.owner !== "Kurucu (Sınırsız)") {
                    chartLabels.push(info.owner);
                    chartData.push(info.total_used);
                }

                kHtml += `
                    <tr>
                        <td><div class="fw-bold">${info.owner}</div></td>
                        <td><code class="text-muted bg-light px-2 py-1 rounded">${k}</code></td>
                        <td><span class="badge bg-primary rounded-pill fs-6">${info.credits}</span></td>
                        <td>${info.total_used}</td>
                        <td><span class="badge ${info.status == 'active' ? 'badge-active' : 'badge-banned'}">${info.status.toUpperCase()}</span></td>
                        <td><small class="text-muted">${info.created_at}</small></td>
                        <td class="text-end">
                            <div class="btn-group">
                                <button class="btn btn-sm btn-outline-success" onclick="upK('${k}', 'add')" title="Kredi Ekle"><i class="fa fa-coins"></i></button>
                                <button class="btn btn-sm btn-outline-warning" onclick="upK('${k}', 'toggle')" title="Durum Değiştir"><i class="fa fa-ban"></i></button>
                                <button class="btn btn-sm btn-outline-danger" onclick="upK('${k}', 'del')" title="Sil"><i class="fa fa-trash"></i></button>
                            </div>
                        </td>
                    </tr>`;
            }
            document.getElementById('s-credits').innerText = totalUsage;
            document.getElementById('keyTable').innerHTML = kHtml;
            
            // Grafik Güncelleme
            updateChart(chartLabels, chartData);

            // Loglar
            let lHtml = ''; 
            let miniLogHtml = '';
            
            d.logs.slice().reverse().forEach((l, index) => {
                const row = `<tr><td><small class="text-muted">${l.time}</small></td><td>${l.owner}</td><td><code>${l.imei}</code></td><td><span class="badge bg-light text-dark border">${l.status}</span></td><td><small class="text-muted">${l.ip}</small></td></tr>`;
                lHtml += row;
                
                if(index < 8) {
                    miniLogHtml += `<div class="d-flex justify-content-between border-bottom py-2">
                        <div><span class="fw-bold">${l.owner}</span><br><small class="text-muted">${l.imei}</small></div>
                        <div class="text-end"><span class="badge bg-light text-dark">${l.status}</span><br><small class="text-muted">${l.time}</small></div>
                    </div>`;
                }
            });
            document.getElementById('fullLogs').innerHTML = lHtml; 
            document.getElementById('dash-logs').innerHTML = miniLogHtml || '<div class="text-muted text-center py-3">Henüz işlem yapılmadı.</div>';
        }

        function updateChart(labels, data) {
            const ctx = document.getElementById('usageChart').getContext('2d');
            if(usageChartInstance) usageChartInstance.destroy();
            
            usageChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Kullanım Miktarı',
                        data: data,
                        backgroundColor: 'rgba(79, 70, 229, 0.2)',
                        borderColor: 'rgba(79, 70, 229, 1)',
                        borderWidth: 2,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    scales: { y: { beginAtZero: true } }
                }
            });
        }

        async function keyModal() {
            const owner = prompt("Müşteri Adı:"); 
            if(!owner) return;
            const credits = prompt("Başlangıç Kredisi:", "100");
            if(credits) { 
                await fetch('/api/admin/key/action', { 
                    method: 'POST', 
                    headers: {'Content-Type':'application/json', 'x-adm-u': auth.u, 'x-adm-p': auth.p}, 
                    body: JSON.stringify({owner, credits: parseInt(credits), action: 'create'})
                }); 
                refresh(); 
            }
        }

        async function upK(key, action) {
            if(action === 'del' && !confirm("Bu anahtarı silmek istediğinize emin misiniz?")) return;
            
            await fetch('/api/admin/key/action', { 
                method: 'POST', 
                headers: {'Content-Type':'application/json', 'x-adm-u': auth.u, 'x-adm-p': auth.p}, 
                body: JSON.stringify({key, action})
            }); 
            refresh();
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
    if x_adm_u not in ADMINS_DB or ADMINS_DB[x_adm_u] != x_adm_p: 
        raise HTTPException(status_code=401, detail="Yetkisiz erişim")
    return True

@app.post("/api/admin/verify")
def auth_login(req: AdminUserReq):
    if req.username in ADMINS_DB and ADMINS_DB[req.username] == req.password: 
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Hatalı kimlik bilgileri")

@app.get("/api/admin/data")
def get_admin_data(v=Depends(verify_admin)):
    return {"keys": API_DB, "logs": QUERY_LOGS}

@app.post("/api/admin/key/action")
def manage_keys(req: KeyActionReq, v=Depends(verify_admin)):
    if req.action == "create":
        nk = "key-" + uuid.uuid4().hex[:12]
        API_DB[nk] = {
            "owner": req.owner, 
            "credits": req.credits, 
            "total_used": 0, 
            "status": "active", 
            "created_at": datetime.now().strftime("%Y-%m-%d")
        }
    elif req.key in API_DB:
        if req.action == "del": 
            del API_DB[req.key]
        elif req.action == "add": 
            API_DB[req.key]["credits"] += 500
        elif req.action == "toggle": 
            API_DB[req.key]["status"] = "banned" if API_DB[req.key]["status"] == "active" else "active"
    return {"ok": True}

# --- ANA SORGU ENDPOINTİ ---

@app.post("/api/check-imei")
async def check_imei(req: IMEIReq, x_api_key: str = Header(None), r: Request = None):
    # 1. API Key Doğrulama
    if not x_api_key or x_api_key not in API_DB or API_DB[x_api_key]["status"] != "active":
        raise HTTPException(status_code=401, detail="Geçersiz veya Pasif API Key")
    
    user = API_DB[x_api_key]
    if user["credits"] <= 0: 
        return {"success": False, "error": "Bakiye yetersiz. Lütfen kredi yükleyin."}

    # 2. IMEI Format ve Güvenlik Doğrulaması (Luhn Check)
    imei = req.imei.strip()
    if len(imei) == 14:
        imei += get_luhn_checksum(imei)
    elif len(imei) == 15:
        if not is_luhn_valid(imei): 
            return {"success": False, "error": "Geçersiz IMEI Numarası (Luhn Doğrulaması Başarısız)"}
    else: 
        return {"success": False, "error": "IMEI numarası 14 veya 15 hane olmalıdır."}

    # 3. Veri Çekme (Simüle Edilmiş)
    data = mock_fetch_imei_data(imei)
    
    # 4. Kayıt ve Yanıt İşlemleri
    if not data.get("error"):
        user["credits"] -= 1
        user["total_used"] += 1
        
        # Log Kaydı Oluştur
        log_entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
            "owner": user["owner"], 
            "imei": imei, 
            "status": data["durum"], 
            "ip": r.client.host if r else "unknown"
        }
        QUERY_LOGS.append(log_entry)
        
        # Belleği şişirmemek için son 500 kaydı tut
        if len(QUERY_LOGS) > 500: 
            QUERY_LOGS.pop(0)
            
        return {"success": True, **data, "remaining_credits": user["credits"]}
    
    return {"success": False, "error": data["error"]}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
