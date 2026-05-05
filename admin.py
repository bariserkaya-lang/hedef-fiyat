@app.route('/kapanis_duzenle', methods=['GET', 'POST'])
def kapanis_duzenle():
    if request.method == 'POST':
        hisse = request.form['hisse'].upper()
        orantili = request.form.get('orantili')
        
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
        
        if orantili:
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
        else:
            # Normal manuel güncelleme (tek tek)
            for key, value in request.form.items():
                if key.startswith('kapanis_') and value:
                    tarih = key.replace('kapanis_', '')
                    try:
                        yeni_kapanis = float(value)
                        c.execute("""
                            UPDATE tahminler 
                            SET tarihsel_kapanis = ? 
                            WHERE hisse_kodu = ? AND tarih = ?
                        """, (yeni_kapanis, hisse, tarih))
                    except:
                        pass
            
            conn.commit()
            github_upload()
            mesaj = f"✅ {hisse} için güncellemeler kaydedildi."
        
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
    
    else:
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
