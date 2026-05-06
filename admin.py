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

# ======================== ZORLA GITHUB'DAN VERİTABANINI İNDİR ========================
try:
    url = "https://raw.githubusercontent.com/bariserkaya-lang/hedef-fiyat/main/borsa_verisi.db"
    response = requests.get(url)
    if response.status_code == 200:
        with open("borsa_verisi.db", "wb") as f:
            f.write(response.content)
        print("Veritabanı GitHub'dan indirildi")
    else:
        print(f"İndirme başarısız: {response.status_code}")
except Exception as e:
    print(f"İndirme hatası: {e}")

st.set_page_config(page_title="BIST Hedef Fiyat Portalı", layout="wide")

DB_PATH = "borsa_verisi.db"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "bariserkaya-lang/hedef-fiyat"
GITHUB_PATH = "borsa_verisi.db"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_PATH}"

def get_connection():
    return sqlite3.connect(DB_PATH)

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

@st.cache_data(ttl=300)
def get_dashboard_data():
    conn = get_connection()
    query = """
    WITH son_tahminler AS (
        SELECT hisse_kodu, araci_kurum, yeni_hedef_fiyat,
               ROW_NUMBER() OVER(PARTITION BY hisse_kodu, araci_kurum ORDER BY rowid DESC) as rn
        FROM tahminler
    )
    SELECT 
        hisse_kodu as 'Hisse',
        ROUND(AVG(yeni_hedef_fiyat), 2) as 'Ortalama Hedef Fiyat',
        COUNT(DISTINCT araci_kurum) as 'Kurum Sayısı'
    FROM son_tahminler WHERE rn = 1 
    GROUP BY hisse_kodu 
    ORDER BY hisse_kodu
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_hisse_detay(hisse_kodu):
    conn = get_connection()
    df = pd.read_sql(f"""
        SELECT rowid, tarih, araci_kurum, yeni_hedef_fiyat, eski_hedef_fiyat, tarihsel_kapanis, tavsiye
        FROM tahminler WHERE hisse_kodu = '{hisse_kodu}' ORDER BY rowid ASC
    """, conn)
    conn.close()
    if df.empty:
        return df
    dinamik_ortalamalar = []
    for i in range(len(df)):
        en_sonlar = df.iloc[:i+1].groupby('araci_kurum').last().reset_index()
        dinamik_ortalamalar.append(round(en_sonlar['yeni_hedef_fiyat'].mean(), 2))
    df['Dinamik Ortalama'] = dinamik_ortalamalar
    df['Prim Potansiyeli %'] = ((df['Dinamik Ortalama'] / df['tarihsel_kapanis']) - 1).round(2) * 100
    df = df.rename(columns={
        'rowid':'ID','tarih':'Tarih','araci_kurum':'Aracı Kurum',
        'eski_hedef_fiyat':'Eski Hedef Fiyat','yeni_hedef_fiyat':'Yeni Hedef Fiyat',
        'tarihsel_kapanis':'Kapanış','tavsiye':'Tavsiye'
    })
    return df

def fetch_current_prices(hisse_listesi):
    prices = {}
    progress_bar = st.progress(0)
    for i, hisse in enumerate(hisse_listesi):
        try:
            data = yf.Ticker(f"{hisse}.IS").history(period="1d")
            prices[hisse] = float(data['Close'].iloc[-1]) if not data.empty else 0.0
        except:
            prices[hisse] = 0.0
        time.sleep(0.2)
        progress_bar.progress((i+1)/len(hisse_listesi))
    return prices

def add_prediction(hisse_kodu, araci_kurum, yeni_fiyat, eski_fiyat, tavsiye, kapanis):
    conn = get_connection()
    c = conn.cursor()
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        c.execute("SELECT 1 FROM tahminler WHERE tarih=? AND hisse_kodu=? AND araci_kurum=? AND yeni_hedef_fiyat=? LIMIT 1",
                  (bugun, hisse_kodu.upper().strip(), araci_kurum.strip(), yeni_fiyat))
        if c.fetchone():
            conn.close()
            return False, "Bu kayıt bugün zaten var"
        c.execute("INSERT INTO tahminler (tarih, araci_kurum, hisse_kodu, eski_hedef_fiyat, yeni_hedef_fiyat, tavsiye, tarihsel_kapanis) VALUES (?,?,?,?,?,?,?)",
                  (bugun, araci_kurum.strip(), hisse_kodu.upper().strip(), eski_fiyat, yeni_fiyat, tavsiye, kapanis))
        conn.commit()
        conn.close()
        github_upload()
        return True, "Kaydedildi"
    except Exception as e:
        conn.close()
        return False, str(e)

def sil_tahmin(tahmin_id):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM tahminler WHERE rowid = ?", (tahmin_id,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted:
            github_upload()
        return deleted > 0, "Silindi" if deleted else "ID yok"
    except Exception as e:
        return False, str(e)

if "dashboard_data" not in st.session_state:
    st.session_state.dashboard_data = get_dashboard_data()
if "fiyatlar" not in st.session_state:
    st.session_state.fiyatlar = {}

st.title("📈 BIST Hedef Fiyat Portalı")
tabs = st.tabs(["📊 Dashboard", "🔍 Hisse Analizi", "➕ Yeni Tahmin Ekle", "🗑️ Yönetim"])

with tabs[0]:
    st.subheader("Güncel Hedef Fiyat Ortalamaları")
    df_view = st.session_state.dashboard_data.copy()
    if st.session_state.fiyatlar:
        df_view["Son Kapanış"] = df_view["Hisse"].map(st.session_state.fiyatlar)
        df_view["Potansiyel %"] = 0.0
        mask = df_view["Son Kapanış"] > 0
        df_view.loc[mask, "Potansiyel %"] = (df_view["Ortalama Hedef Fiyat"] / df_view["Son Kapanış"] - 1).round(3) * 100
        df_view["Potansiyel %"] = df_view["Potansiyel %"].round(1)
    else:
        df_view["Son Kapanış"] = 0.0
        df_view["Potansiyel %"] = 0.0
    if st.button("🔄 Fiyatları Güncelle", type="primary"):
        with st.spinner("Fiyatlar çekiliyor..."):
            hisseler = df_view["Hisse"].tolist()
            fiyatlar = fetch_current_prices(hisseler)
            st.session_state.fiyatlar = fiyatlar
            df_view["Son Kapanış"] = df_view["Hisse"].map(fiyatlar)
            df_view["Potansiyel %"] = 0.0
            mask = df_view["Son Kapanış"] > 0
            df_view.loc[mask, "Potansiyel %"] = (df_view["Ortalama Hedef Fiyat"] / df_view["Son Kapanış"] - 1).round(3) * 100
            df_view["Potansiyel %"] = df_view["Potansiyel %"].round(1)
            st.session_state.dashboard_data = df_view
            st.success("Fiyatlar güncellendi!")
            st.rerun()
    st.dataframe(df_view, use_container_width=True)
    sec = st.selectbox("Hisse seç", df_view["Hisse"].tolist(), key="dashboard_hisse")
    if sec:
        st.session_state.selected_stock = sec

with tabs[1]:
    hisseler = st.session_state.dashboard_data["Hisse"].tolist()
    if hisseler:
        idx = 0
        if "selected_stock" in st.session_state and st.session_state.selected_stock in hisseler:
            idx = hisseler.index(st.session_state.selected_stock)
        sec_hisse = st.selectbox("Hisse Analizi", hisseler, index=idx, key="analiz_hisse")
        if sec_hisse:
            detay = get_hisse_detay(sec_hisse)
            if not detay.empty:
                graf = detay[["Tarih","Dinamik Ortalama","Kapanış"]].drop_duplicates("Tarih").sort_values("Tarih")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=graf["Tarih"], y=graf["Dinamik Ortalama"], mode="lines+markers", name="Dinamik Hedef"))
                fig.add_trace(go.Scatter(x=graf["Tarih"], y=graf["Kapanış"], mode="lines+markers", name="Kapanış"))
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(detay, use_container_width=True)

with tabs[2]:
    st.subheader("➕ Yeni Tahmin Ekle")
    with st.form("ekle_form"):
        c1, c2 = st.columns(2)
        hisse = c1.text_input("Hisse Kodu")
        kurum = c1.text_input("Aracı Kurum")
        eski = c2.number_input("Eski Hedef Fiyat", min_value=0.0, step=0.1, format="%.2f")
        yeni = c2.number_input("Yeni Hedef Fiyat", min_value=0.0, step=0.1, format="%.2f")
        tavsiye = st.selectbox("Tavsiye", ["AL","TUT","SAT","NÖTR","ENDEX ÜSTÜ","ENDEKSE PARALEL","ENDEX ALTI"])
        kapanis = st.number_input("Bugünkü Kapanış", min_value=0.0, step=0.1, format="%.2f")
        submitted = st.form_submit_button("💾 KAYDET")
        if submitted:
            if not hisse or not kurum or yeni <= 0:
                st.error("Eksik bilgi")
            else:
                ok, msg = add_prediction(hisse, kurum, yeni, eski, tavsiye, kapanis)
                if ok:
                    st.success(msg)
                    st.balloons()
                    st.session_state.dashboard_data = get_dashboard_data()
                    st.rerun()
                else:
                    st.error(msg)

with tabs[3]:
    st.subheader("🗑️ Tahmin Silme")
    hisseler = st.session_state.dashboard_data["Hisse"].tolist()
    if hisseler:
        sil_hisse = st.selectbox("Hisse seç", hisseler, key="silme_hisse")
        if sil_hisse:
            detay = get_hisse_detay(sil_hisse)
            if not detay.empty:
                st.dataframe(detay[["ID","Tarih","Aracı Kurum","Yeni Hedef Fiyat","Kapanış","Tavsiye"]])
                sil_id = st.number_input("Silinecek ID", min_value=1, step=1, key="sil_id")
                if st.button("🗑️ SİL"):
                    ok, msg = sil_tahmin(sil_id)
                    if ok:
                        st.success(msg)
                        st.session_state.dashboard_data = get_dashboard_data()
                        st.rerun()
                    else:
                        st.error(msg)
    if st.button("📤 GitHub'a MANUEL YEDEKLE"):
        with st.spinner("Yedekleniyor..."):
            if github_upload():
                st.success("Yedeklendi")
            else:
                st.error("Hata")
