from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime
import os
import base64
import requests

# --- ÖNCE Flask uygulamasını oluştur ---
app = Flask(__name__)
# ------------------------------------

DB_PATH = os.path.join(os.path.dirname(__file__), "borsa_verisi.db")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "bariserkaya-lang/hedef-fiyat"
GITHUB_PATH = "borsa_verisi.db"

def get_db():
    return sqlite3.connect(DB_PATH)

def github_upload():
    if not GITHUB_TOKEN:
        print("GitHub token yok")
        return False
    try:
        with open(DB_PATH, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_PATH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
        data = {"message": f"Yedek {datetime.now()}", "content": content, "branch": "main"}
        if sha:
            data["sha"] = sha
        r2 = requests.put(url, headers=headers, json=data)
        return r2.status_code in [200, 201]
    except Exception as e:
        print(f"Yedekleme hatası: {e}")
        return False

@app.route('/')
def index():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tahminler")
    total = c.fetchone()[0]
    conn.close()
    return render_template('index.html', total=total)

@app.route('/list')
def list_predictions():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT rowid, tarih, hisse_kodu, araci_kurum, yeni_hedef_fiyat, tarihsel_kapanis, tavsiye 
        FROM tahminler 
        ORDER BY tarih DESC, hisse_kodu 
        LIMIT 100
    """)
    rows = c.fetchall()
    conn.close()
    return render_template('list.html', predictions=rows)

@app.route('/add', methods=['GET', 'POST'])
def add_prediction():
    if request.method == 'POST':
        try:
            tarih = request.form['tarih']
            hisse = request.form['hisse'].upper()
            kurum = request.form['kurum']
            eski_fiyat = float(request.form['eski_fiyat'])
            yeni_fiyat = float(request.form['yeni_fiyat'])
            kapanis = float(request.form['kapanis'])
            tavsiye = request.form['tavsiye']
            
            conn = get_db()
            c = conn.cursor()
            
            c.execute("""
                SELECT 1 FROM tahminler 
                WHERE tarih = ? AND hisse_kodu = ? AND araci_kurum = ? AND yeni_hedef_fiyat = ?
            """, (tarih, hisse, kurum, yeni_fiyat))
            
            if c.fetchone():
                conn.close()
                return render_template('add.html', error="Bu kayıt zaten var!")
            
            c.execute("""
                INSERT INTO tahminler (tarih, araci_kurum, hisse_kodu, eski_hedef_fiyat, yeni_hedef_fiyat, tavsiye, tarihsel_kapanis)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (tarih, kurum, hisse, eski_fiyat, yeni_fiyat, tavsiye, kapanis))
            
            conn.commit()
            conn.close()
            return redirect(url_for('list_predictions'))
        except Exception as e:
            return render_template('add.html', error=str(e))
    
    return render_template('add.html', error=None)

@app.route('/delete/<int:rowid>')
def delete_prediction(rowid):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM tahminler WHERE rowid = ?", (rowid,))
    conn.commit()
    conn.close()
    return redirect(url_for('list_predictions'))

@app.route('/api/stats')
def api_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tahminler")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT hisse_kodu) FROM tahminler")
    stocks = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT araci_kurum) FROM tahminler")
    brokers = c.fetchone()[0]
    conn.close()
    return jsonify({'total': total, 'stocks': stocks, 'brokers': brokers})

# ======================== MANUEL DÜZELTME SAYFALARI ========================

@app.route('/adjustments')
def adjustments():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, hisse_kodu, bolunme_tarihi, oran, aciklama, created_at FROM bolunme_duzeltmeleri ORDER BY bolunme_tarihi DESC")
    rows = c.fetchall()
    conn.close()
    return render_template('adjustments.html', adjustments=rows)

@app.route('/add_adjustment', methods=['GET', 'POST'])
def add_adjustment():
    if request.method == 'POST':
        try:
            hisse_kodu = request.form['hisse_kodu'].upper()
            bolunme_tarihi = request.form['bolunme_tarihi']
            oran = float(request.form['oran'])
            aciklama = request.form.get('aciklama', '')
            
            conn = get_db()
            c = conn.cursor()
            
            c.execute("""
                INSERT INTO bolunme_duzeltmeleri (hisse_kodu, bolunme_tarihi, oran, aciklama)
                VALUES (?, ?, ?, ?)
            """, (hisse_kodu, bolunme_tarihi, oran, aciklama))
            
            conn.commit()
            
            apply_adjustment(hisse_kodu, bolunme_tarihi, oran)
            github_upload()
            
            conn.close()
            return redirect(url_for('adjustments'))
        except Exception as e:
            return render_template('add_adjustment.html', error=str(e))
    
    return render_template('add_adjustment.html', error=None)

@app.route('/delete_adjustment/<int:adj_id>')
def delete_adjustment(adj_id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT hisse_kodu, bolunme_tarihi, oran FROM bolunme_duzeltmeleri WHERE id = ?", (adj_id,))
    adj = c.fetchone()
    
    if adj:
        hisse_kodu, bolunme_tarihi, oran = adj
        revert_adjustment(hisse_kodu, bolunme_tarihi, oran)
        c.execute("DELETE FROM bolunme_duzeltmeleri WHERE id = ?", (adj_id,))
        conn.commit()
        github_upload()
    
    conn.close()
    return redirect(url_for('adjustments'))

def apply_adjustment(hisse_kodu, bolunme_tarihi, oran):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE tahminler 
        SET eski_hedef_fiyat = eski_hedef_fiyat / ?,
            yeni_hedef_fiyat = yeni_hedef_fiyat / ?
        WHERE hisse_kodu = ? AND tarih < ?
    """, (oran, oran, hisse_kodu, bolunme_tarihi))
    updated = c.rowcount
    conn.commit()
    conn.close()
    print(f"✅ {hisse_kodu} için {updated} satır düzeltildi")

def revert_adjustment(hisse_kodu, bolunme_tarihi, oran):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        UPDATE tahminler 
        SET eski_hedef_fiyat = eski_hedef_fiyat * ?,
            yeni_hedef_fiyat = yeni_hedef_fiyat * ?
        WHERE hisse_kodu = ? AND tarih < ?
    """, (oran, oran, hisse_kodu, bolunme_tarihi))
    updated = c.rowcount
    conn.commit()
    conn.close()
    print(f"🔄 {hisse_kodu} için {updated} satır geri alındı")

# ======================== KAPANIŞ FİYATI DÜZENLEME (ORANTISAL) ========================

@app.route('/kapanis_duzenle', methods=['GET', 'POST'])
def kapanis_duzenle():
    if request.method == 'POST':
        hisse = request.form['hisse'].upper()
        conn = get_db()
        c = conn.cursor()
        
        # Mevcut tüm kapanış fiyatlarını al
        c.execute("""
            SELECT tarih, tarihsel_kapanis 
            FROM tahminler 
            WHERE hisse_kodu = ? 
            ORDER BY tarih ASC
        """, (hisse,))
        mevcut_fiyatlar = {tarih: fiyat for tarih, fiyat in c.fetchall()}
        
        # Orantısal düzeltme: Kullanıcının girdiği tarih ve fiyatı bul
        yeni_referans = None
        referans_tarih = None
        
        for key, value in request.form.items():
            if key.startswith('kapanis_') and value:
                referans_tarih = key.replace('kapanis_', '')
                try:
                    yeni_referans = float(value)
                    break
                except:
                    pass
        
        if yeni_referans and referans_tarih and referans_tarih in mevcut_fiyatlar:
            eski_referans = mevcut_fiyatlar[referans_tarih]
            if eski_referans > 0:
                oran = yeni_referans / eski_referans
                
                # Tüm fiyatları orantısal olarak güncelle
                for tarih, eski_fiyat in mevcut_fiyatlar.items():
                    yeni_fiyat = eski_fiyat * oran
                    c.execute("""
                        UPDATE tahminler 
                        SET tarihsel_kapanis = ? 
                        WHERE hisse_kodu = ? AND tarih = ?
                    """, (yeni_fiyat, hisse, tarih))
                
                conn.commit()
                github_upload()
                mesaj = f"✅ {hisse} için {len(mevcut_fiyatlar)} satır kapanış fiyatı, {referans_tarih} tarihindeki {yeni_referans} TL referansına göre orantısal olarak düzeltildi."
            else:
                mesaj = "❌ Referans fiyat 0 olamaz!"
        else:
            mesaj = "❌ Lütfen bir tarih için doğru fiyat girin!"
        
        conn.close()
        
        # Güncel verileri tekrar göster
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT tarih, tarihsel_kapanis 
            FROM tahminler 
            WHERE hisse_kodu = ? 
            ORDER BY tarih ASC
        """, (hisse,))
        rows = c.fetchall()
        conn.close()
        
        return render_template('kapanis_duzenle.html', hisse=hisse, kapanislar=rows, mesaj=mesaj)
    
    else: # GET isteği
        hisse = request.args.get('hisse', '').upper()
        if not hisse:
            return render_template('kapanis_duzenle.html', hisse=None, kapanislar=None)
        
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT tarih, tarihsel_kapanis 
            FROM tahminler 
            WHERE hisse_kodu = ? 
            ORDER BY tarih ASC
        """, (hisse,))
        rows = c.fetchall()
        conn.close()
        
        return render_template('kapanis_duzenle.html', hisse=hisse, kapanislar=rows)

def init_adjustments_table():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bolunme_duzeltmeleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hisse_kodu TEXT NOT NULL,
            bolunme_tarihi TEXT NOT NULL,
            oran REAL NOT NULL,
            aciklama TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_adjustments_table()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
