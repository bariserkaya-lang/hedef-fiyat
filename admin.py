from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
import os
DB_PATH = os.path.join(os.path.dirname(__file__), "borsa_verisi.db")

def get_db():
    return sqlite3.connect(DB_PATH)

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
