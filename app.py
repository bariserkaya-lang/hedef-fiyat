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
    except:
        pass
    return False

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
    c.execute("""
        CREATE TABLE IF NOT EXISTS tahminler (
            tarih TEXT,
            araci_kurum TEXT,
            hisse_kodu TEXT,
            eski_hedef_fiyat REAL,
            yeni_hedef_fiyat REAL,
            tavsiye TEXT,
            tarihsel_kapanis REAL
        )
    """)
    conn.commit()
    conn.close()

github_download()
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

@st.cache_data(ttl=300)
def fetch_current_prices(hisse_listesi):
    prices = {}
    for hisse in hisse_listesi:
        try:
            data = yf.Ticker(f"{hisse}.IS").history(period="1d")
            prices[hisse] = float(data['Close'].iloc[-1]) if not data.empty else 0.0
        except:
            prices[hisse] = 0.0
        time.sleep(0.1)
    return prices

@st.cache_data(ttl=60)
def get_adjustment_factor(hisse_kodu, hedef_tarihi):
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT oran FROM bolunme_duzeltmeleri
            WHERE hisse_kodu =? AND bolunme_tarihi >?
            ORDER BY bolunme_tarihi ASC
        """, (hisse_kodu, hedef_tarihi))

        toplam_carpan = 1.0
        for (carpan,) in c.fetchall():
            toplam_carpan *= float(carpan)
        conn.close()
        return toplam_carpan
    except:
        return 1.0

@st.cache_data(ttl=60)
def get_dashboard_data():
    conn = get_connection()
    try:
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
    except:
        df = pd.DataFrame()
    conn.close()

    if df.empty:
        return pd.DataFrame(columns=['Hisse', 'Ortalama Hedef Fiyat', 'Kurum Sayısı'])

    duzeltilmis_fiyatlar = []
    for _, row in df.iterrows():
        carpan = get_adjustment_factor(row['hisse_kodu'], row['tarih'])
        duzeltilmis_fiyatlar.append(row['yeni_hedef_fiyat'] / carpan)

    df['duzeltilmis_hedef'] = duzeltilmis_fiyatlar
    son_tahminler = df[df['rn'] == 1]

    if son_tahminler.empty:
        return pd.DataFrame(columns=['Hisse', 'Ortalama Hedef Fiyat', 'Kurum Sayısı'])

    result = son_tahminler.groupby('hisse_kodu').agg({
        'duzeltilmis_hedef': 'mean',
        'araci_kurum': 'nunique'
    }).reset_index()

    result.columns = ['Hisse', 'Ortalama Hedef Fiyat', 'Kurum Sayısı']
    result['Ortalama Hedef Fiyat'] = result['Ortalama Hedef Fiyat'].round(2)
    result = result.sort_values('Hisse')

    return result

def get_hisse_detay(hisse_kodu):
    conn = get_connection()
    try:
        df = pd.read_sql(f"""
            SELECT rowid, tarih, araci_kurum, yeni_hedef_fiyat, eski_hedef_fiyat, tarihsel_kapanis, tavsiye
            FROM tahminler WHERE hisse_kodu = '{hisse_kodu}' ORDER BY rowid ASC
        """, conn)
    except:
        df = pd.DataFrame()
    conn.close()

    if df.empty:
        return df

    for idx, row in df.iterrows():
        carpan = get_adjustment_factor(hisse_kodu, row['tarih'])
        df.at[idx, 'yeni_hedef_fiyat'] = row['yeni_hedef_fiyat'] / carpan
        if pd.notna(row['eski_hedef_fiyat']) and row['eski_hedef_fiyat'] > 0:
            df.at[idx, 'eski_hedef_fiyat'] = row['eski_hedef_fiyat'] / carpan

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
        c.execute("DELETE FROM tahminler WHERE rowid =?", (tahmin_id,))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted:
            github_upload()
        return deleted > 0, "Silindi" if deleted else "ID yok"
    except Exception as e:
        return False, str(e)

# Dashboard verisini çek
dashboard_data = get_dashboard_data()

# Fiyatlar boşsa otomatik çek
if "fiyatlar" not in st.session_state:
    if not dashboard_data.empty:
        with st.spinner("Güncel fiyatlar çekiliyor... İlk açılış 15-20 saniye sürebilir"):
            hisseler = dashboard_data["Hisse"].tolist()
            st.session_state.fiyatlar = fetch_current_prices(hisseler)
    else:
        st.session_state.fiyatlar = {}

st.title("📈 BIST Hedef Fiyat Portalı")
tabs = st.tabs(["📊 Dashboard", "🔍 Hisse Analizi", "➕ Yeni Tahmin Ekle", "🗑️ Yönetim"])

with tabs[0]:
    st.subheader("Güncel Hedef Fiyat Ortalamaları")
    df_view = dashboard_data.copy()

    if df_view.empty:
        st.warning("Henüz tahmin eklenmemiş veya veritabanı boş.")
    else:
        df_view["Son Kapanış"] = df_view["Hisse"].map(st.session_state.fiyatlar)
        df_view["Potansiyel %"] = 0.0
        mask = df_view["Son Kapanış"] > 0
        df_view.loc[mask, "Potansiyel %"] = (df_view["Ortalama Hedef Fiyat"] / df_view["Son Kapanış"] - 1).round(3) * 100
        df_view["Potansiyel %"] = df_view["Potansiyel %"].round(1)

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
                st.success("Fiyatlar güncellendi!")
                st.rerun()

        st.dataframe(df_view, width='stretch')
        sec = st.selectbox("Hisse seç", df_view["Hisse"].tolist() if not df_view.empty else [], key="dashboard_hisse")
        if sec:
            st.session_state.selected_stock = sec

with tabs[1]:
    hisseler = dashboard_data["Hisse"].tolist() if not dashboard_data.empty else []
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
                fig.update_layout(height=500, title=f"{sec_hisse} - Hedef Fiyat vs Kapanış")
                st.plotly_chart(fig, width='stretch')
                st.dataframe(detay, width='stretch')
            else:
                st.info("Bu hisse için veri bulunamadı")
    else:
        st.info("Henüz tahmin eklenmemiş")

with tabs[2]:
    st.subheader("➕ Yeni Tahmin Ekle")
    with st.form("ekle_form"):
        c1, c2 = st.columns(2)
        hisse = c1.text_input("Hisse Kodu").upper()
        kurum = c1.text_input("Aracı Kurum")
        eski = c2.number_input("Eski Hedef Fiyat", min_value=0.0, step=0.1, format="%.2f")
        yeni = c2.number_input("Yeni Hedef Fiyat", min_value=0.0, step=0.1, format="%.2f")
        tavsiye = st.selectbox("Tavsiye", ["AL","TUT","SAT","NÖTR","ENDEX ÜSTÜ","ENDEKSE PARALEL","ENDEX ALTI"])
        kapanis = st.number_input("Bugünkü Kapanış", min_value=0.0, step=0.1, format="%.2f")
        submitted = st.form_submit_button("💾 KAYDET")
        if submitted:
            if not hisse or not kurum or yeni <= 0:
                st.error("Hisse kodu, aracı kurum ve yeni hedef fiyat zorunlu")
            else:
                ok, msg = add_prediction(hisse, kurum, yeni, eski, tavsiye, kapanis)
                if ok:
                    st.success(msg)
                    st.balloons()
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(msg)

with tabs[3]:
    st.subheader("🗑️ Tahmin Silme")
    hisseler = dashboard_data["Hisse"].tolist() if not dashboard_data.empty else []
    if hisseler:
        sil_hisse = st.selectbox("Hisse seç", hisseler, key="silme_hisse")
        if sil_hisse:
            detay = get_hisse_detay(sil_hisse)
            if not detay.empty:
                st.dataframe(detay[["ID","Tarih","Aracı Kurum","Yeni Hedef Fiyat"]], width='stretch')
                sil_id = st.number_input("Silinecek ID", min_value=1, step=1, key="sil_id")
                if st.button("🗑️ SİL", type="primary"):
                    ok, msg = sil_tahmin(sil_id)
                    if ok:
                        st.success(msg)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.info("Bu hisse için tahmin yok")
    else:
        st.info("Silinecek tahmin bulunamadı")

    st.divider()
    if st.button("📤 GitHub'a MANUEL YEDEKLE"):
        with st.spinner("Yedekleniyor..."):
            if github_upload():
                st.success("Yedeklendi")
            else:
                st.error("Hata: GitHub token kontrol edin")
