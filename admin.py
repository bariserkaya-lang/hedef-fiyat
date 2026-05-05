@app.route('/kapanis_duzenle', methods=['GET', 'POST'])
def kapanis_duzenle():
    if request.method == 'POST':
        hisse = request.form['hisse'].upper()
        conn = get_db()
        c = conn.cursor()
        
        for key, value in request.form.items():
            if key.startswith('kapanis_'):
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
        conn.close()
        return redirect(url_for('kapanis_duzenle', hisse=hisse))
    
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
