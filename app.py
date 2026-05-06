import streamlit as st
import pandas as pd
import sqlite3
import plotly.graph_objects as go
import yfinance as yf
import time
import os
import base64
import requests
from datetime import datetime

st.set_page_config(page_title="BIST Hedef Fiyat Portalı", layout="wide")
DB_PATH = "borsa_verisi.db"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "bariserkaya-lang/hedef-fiyat"
GITHUB_PATH = "borsa_verisi.db"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_PATH}"

def github_download():
    try:
        response = requests.get(GITHUB_RAW_URL)
        if response.status_code == 200:
            with open(DB_PATH, "wb") as f:
                f.write(response.content)
            return True
    except: pass
    return False

if not os.path.exists(DB_PATH):
    github_download()

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_tables():
    conn = get_connection()
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

init_tables()

def github_upload():
    if not GITHUB_TOKEN:
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
    except:
        return False

@st.cache_data(ttl=30)
def get_adjustment_factor(hisse_kodu, hedef_tarihi):
    try:
        conn = get_connection()
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM bolunme_duzeltmeleri WHERE hisse_kodu =?", (hisse_kodu,))
        toplam_bolunme = c.fetchone()[0]
        
        c.execute("""
            SELECT oran, bolunme_tarihi FROM bolunme_duzeltmeleri
            WHERE hisse_kodu =? AND bolunme_tarihi >?
            ORDER BY bolunme_tarihi ASC
        """, (hisse_kodu, hedef_tarihi))

        rows = c.fetchall()
        toplam_carpan = 1.0
        for (carpan,) in rows:
            toplam_carpan *= float(carpan)
        conn.close()
        
        return toplam_carpan, toplam_bolunme, len(rows)
    except Exception as e:
        return 1.0, 0, 0

@st.cache_data(ttl=30)
def get_dashboard_data():
    conn = get_connection()
    query = """
    SELECT
        hisse_kodu,
        tarih,
        araci_kurum,
        yeni_hedef_fiyat,
        ROW_NUMBER() OVER(PARTITION BY hisse_kodu, araci_kurum ORDER BY rowid DESC) as rn
    FROM tahminler
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        return pd.DataFrame(columns=['Hisse', 'Ortalama Hedef Fiyat', 'Kurum Sayısı'])

    duzeltilmis_fiyatlar = []
    debug_info = {}
    for _, row in df.iterrows():
        carpan, toplam, uygulanan = get_adjustment_factor(row['hisse_kodu'], row['tarih'])
        duzeltilmis_fiyatlar.append(row['yeni_hedef_fiyat'] / carpan)
        if row['hisse_kodu'] not in debug_info:
            debug_info[row['hisse_kodu']] = f"Toplam {toplam} bölünme kaydı var"

    df['duzeltilmis_hedef'] = duzeltilmis_fiyatlar
    son_tahminler = df[df['rn'] == 1]

    result = son_tahminler.groupby('hisse_kodu').agg({
        'duzeltilmis_hedef': 'mean',
        'araci_kurum': 'nunique'
    }).reset_index()

    result.columns = ['Hisse', 'Ortalama Hedef Fiyat', 'Kurum Sayısı']
    result['Ortalama Hedef Fiyat'] = result['Ortalama Hedef Fiyat'].round(2)
    result = result.sort_values('Hisse')

    return result, debug_info

def get_hisse_detay(hisse_kodu):
    conn = get_connection()
    df = pd.read
