import pandas as pd
import sqlite3
import os

excel_yolu = 'hedeffiyat.xlsx'
db_yolu = 'borsa_verisi.db'

if os.path.exists(db_yolu):
    os.remove(db_yolu)

conn = sqlite3.connect(db_yolu)

all_sheets = pd.read_excel(excel_yolu, sheet_name=None, dtype=str)

df_list = []

for sheet_name, df in all_sheets.items():
    df.columns = [str(c).strip() for c in df.columns]
    
    if df.empty:
        continue
    
    df_temp = pd.DataFrame()
    
    try:
        df_temp['tarih'] = pd.to_datetime(df['Tarih'], errors='coerce', dayfirst=True).dt.strftime('%Y-%m-%d')
        df_temp['saat'] = df['Saat'].astype(str)
        df_temp['araci_kurum'] = df['Aracı Kurum'].astype(str).str.strip()
        
        # Hisse kodunu Hisse / Şirket sütunundan al (ilk kelime, tirenden önce)
        hisse_temp = df['Hisse / Şirket'].astype(str).str.strip()
        df_temp['hisse_kodu'] = hisse_temp.str.split('-').str[0].str.strip().str.upper()
        
        df_temp['eski_hedef_fiyat'] = pd.to_numeric(df['Eski Fiyat'], errors='coerce').fillna(0)
        df_temp['yeni_hedef_fiyat'] = pd.to_numeric(df['Yeni Fiyat'], errors='coerce').fillna(0)
        df_temp['tavsiye'] = df['Tavsiye'].astype(str)
        df_temp['tarihsel_kapanis'] = 0.0  # Excel'de kapanış sütunu yok
        
        df_list.append(df_temp)
        print(f"✓ {sheet_name} - {len(df_temp)} satır")
    except KeyError as e:
        print(f"⚠️ {sheet_name} hata: {e}")

if df_list:
    df_final = pd.concat(df_list, ignore_index=True)
    df_final = df_final[df_final['hisse_kodu'].notna()]
    df_final = df_final[df_final['hisse_kodu'] != 'NAN']
    df_final = df_final[df_final['hisse_kodu'] != '']
    df_final = df_final[df_final['hisse_kodu'] != 'nan']
    
    df_final.to_sql('tahminler', conn, if_exists='replace', index=False)
    print(f"\n✅ {len(df_final)} satır aktarıldı.")
    print(f"📊 Benzersiz hisse sayısı: {df_final['hisse_kodu'].nunique()}")
    print(f"📅 Veri aralığı: {df_final['tarih'].min()} - {df_final['tarih'].max()}")
else:
    print("❌ Veri aktarılamadı")

conn.close()
print("\n✨ Veritabanı oluşturuldu.")