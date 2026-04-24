from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_PATH = "borsa_verisi.db"

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)