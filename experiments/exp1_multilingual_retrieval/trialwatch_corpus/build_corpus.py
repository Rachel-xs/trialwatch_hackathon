# -*- coding: utf-8 -*-
"""Builds a synthetic Turkish + Indonesian news corpus (50 docs) and 30 English queries
with gold paragraph labels. Labels are correct by construction.
Run: python3 build_corpus.py   (writes into ./data)"""
import json, os, random, shutil

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

TR_M = ["Ocak","Şubat","Mart","Nisan","Mayıs","Haziran","Temmuz","Ağustos","Eylül","Ekim","Kasım","Aralık"]
ID_M = ["Januari","Februari","Maret","April","Mei","Juni","Juli","Agustus","September","Oktober","November","Desember"]
def d_tr(s): y,m,d = map(int,s.split("-")); return f"{d} {TR_M[m-1]} {y}"
def d_id(s): y,m,d = map(int,s.split("-")); return f"{d} {ID_M[m-1]} {y}"

# ---------------- Turkish ----------------
TR_CH = {
 "217A": dict(charge="halkı yanıltıcı bilgiyi alenen yayma", statute="Türk Ceza Kanunu 217/A (halkı yanıltıcı bilgiyi alenen yayma)",
              pred="kamuoyunu yanıltacak nitelikte bilgi yaymıştır", demand="1 yıldan 3 yıla kadar"),
 "125":  dict(charge="hakaret", statute="Türk Ceza Kanunu 125 (hakaret)",
              pred="bir kamu görevlisine hakaret etmiştir", demand="3 aydan 2 yıla kadar"),
 "7/2":  dict(charge="terör örgütü propagandası", statute="Terörle Mücadele Kanunu 7/2 (terör örgütü propagandası)",
              pred="örgüt propagandası yapmıştır", demand="1 yıldan 5 yıla kadar"),
 "285":  dict(charge="soruşturmanın gizliliğini ihlal", statute="Türk Ceza Kanunu 285 (soruşturmanın gizliliğini ihlal)",
              pred="soruşturmanın gizliliğini ihlal etmiştir", demand="1 yıldan 3 yıla kadar"),
}
TR_ISSUE = {
 "file_access": "dosyadaki bazı belgelere erişimlerinin kısıtlandığını ve bunun savunma hakkını zedelediğini söyledi.",
 "closed": "duruşmanın gözlemcilere kapalı yapılmasına itiraz ettiklerini söyledi.",
 "witness": "savunma tanıklarının dinlenmesine izin verilmediğini söyledi.",
 "expert": "haberin bilirkişi incelemesi yapılmadan suç sayıldığını belirtti.",
 "delay": "dosyanın iki yıldır sonuçlanmadığını söyleyerek yargılamanın makul sürede bitirilmesini istedi.",
 "recusal": "hakimin reddi talebinin kabul edilmediğini söyledi.",
 "pretrial": "müvekkilinin {days} gündür tutuklu olduğunu ve tutukluluğun makul süreyi aştığını belirtti.",
}
TR_OUT = {"acquit":"beraat","hagb":"hükmün açıklanmasının geri bırakılması (HAGB)","prison":"{m} ay hapis cezası"}
TR_DET = {"free":"tutuksuz yargılanıyor","jailed":"tutuklu bulunuyor","released":"serbest"}
TR_P5B = ["Gazetecilik örgütleri, davanın basın özgürlüğü üzerinde caydırıcı etki yaratabileceğini söyledi.",
          "Basın meslek kuruluşları, davayı yakından izlediklerini açıkladı."]

# stage tuples: (stage, date, n, next, issue, days, det, outcome)
TR_CASES = [
 dict(k="T1", name="Selin Karaoğlu", outlet="Kıyı Haber", city="İzmir", topic="belediyedeki ihale usulsüzlüğü", ch="217A",
      court="İzmir 5. Asliye Ceza Mahkemesi", lawyer="Pelin Koç", pub="2025-09-14", arts=[
      ("indictment","2025-11-18",None,"2026-02-12","expert",None,"free",None),
      ("hearing","2026-03-12",2,"2026-06-04","file_access",None,"free",None)]),
 dict(k="T2", name="Mehmet Yıldız", outlet="Doğu Postası", city="Diyarbakır", topic="gözaltındaki polis şiddeti iddiaları", ch="7/2",
      court="Diyarbakır 9. Ağır Ceza Mahkemesi", lawyer="Hakan Demirtaş", pub="2025-06-02", arts=[
      ("hearing","2026-01-22",3,"2026-04-16","pretrial",214,"jailed",None),
      ("hearing","2026-04-16",4,"2026-07-09","closed",None,"jailed",None)]),
 dict(k="T3", name="Emre Akbulut", outlet="Anadolu Çizgi", city="Hatay", topic="deprem konteyner kentlerindeki yardım dağıtımı", ch="125",
      court="Hatay 2. Asliye Ceza Mahkemesi", lawyer="Murat Aksoy", pub="2025-10-21", arts=[
      ("indictment","2025-12-04",None,"2026-03-19","recusal",None,"free",None),
      ("verdict","2026-03-19",None,None,"expert",None,"released",("acquit",None))]),
 dict(k="T4", name="Zeynep Aydemir", outlet="Karadeniz Gündem", city="Zonguldak", topic="devlet hastanesindeki yoğun bakım ölümleri", ch="217A",
      court="Zonguldak 3. Asliye Ceza Mahkemesi", lawyer="Selma Çakır", pub="2025-08-30", arts=[
      ("hearing","2026-02-05",1,"2026-05-14","expert",None,"free",None),
      ("verdict","2026-05-14",None,None,"delay",None,"released",("hagb",None))]),
 dict(k="T5", name="Mehmet Yıldız", outlet="Başkent Haber", city="Ankara", topic="bir cinayet soruşturmasındaki ifadeler", ch="285",
      court="Ankara 12. Asliye Ceza Mahkemesi", lawyer="Orhan Bilgin", pub="2025-11-03", arts=[
      ("indictment","2026-01-15",None,"2026-04-02","file_access",None,"free",None),
      ("hearing","2026-04-02",1,"2026-07-23","witness",None,"free",None)]),
 dict(k="T6", name="Gülşen Tarhan", outlet="Ege Mercek", city="Muğla", topic="çöp depolama sahasındaki sızıntı", ch="125",
      court="Muğla 1. Asliye Ceza Mahkemesi", lawyer="Derya Sönmez", pub="2025-07-12", arts=[
      ("hearing","2026-02-26",2,"2026-05-21","delay",None,"free",None),
      ("verdict","2026-05-21",None,None,"witness",None,"released",("prison",10))]),
 dict(k="T7", name="Burak Sezer", outlet="Kent Sesi", city="Bursa", topic="sınır kasabasındaki göçmen ölümleri", ch="217A",
      court="Bursa 7. Asliye Ceza Mahkemesi", lawyer="Kemal Arslan", pub="2026-01-09", arts=[
      ("indictment","2026-03-03",None,"2026-06-11","file_access",None,"jailed",None),
      ("hearing","2026-06-11",1,"2026-09-17","pretrial",87,"jailed",None)]),
 dict(k="T8", name="Nilay Ertürk", outlet="Trakya Bülten", city="Edirne", topic="grevdeki işçilerle yapılan röportaj", ch="7/2",
      court="Edirne 2. Ağır Ceza Mahkemesi", lawyer="Fulya Yaman", pub="2025-05-19", arts=[
      ("hearing","2026-01-29",5,"2026-04-30","closed",None,"free",None),
      ("verdict","2026-04-30",None,None,"expert",None,"released",("acquit",None))]),
 dict(k="T9", name="Cem Özkaya", outlet="Orta Anadolu Haber", city="Konya", topic="yolsuzluk soruşturmasının iddianame ayrıntıları", ch="285",
      court="Konya 4. Asliye Ceza Mahkemesi", lawyer="Tolga Erdem", pub="2026-02-11", arts=[
      ("indictment","2026-04-07",None,"2026-07-02","expert",None,"free",None),
      ("hearing","2026-07-02",1,"2026-10-22","recusal",None,"free",None)]),
 dict(k="T10", name="Ayten Korkmaz", outlet="Güney Gazete", city="Mersin", topic="kamu kurumundaki torpilli atamalar", ch="217A",
      court="Mersin 6. Asliye Ceza Mahkemesi", lawyer="Nesrin Güler", pub="2025-12-08", arts=[
      ("hearing","2026-05-08",2,"2026-08-13","witness",None,"free",None),
      ("verdict","2026-08-13",None,None,"delay",None,"released",("hagb",None))]),
]

# ---------------- Indonesian ----------------
ID_CH = {
 "27A": dict(charge="pencemaran nama baik", statute="Pasal 27A UU ITE (menyerang kehormatan orang lain)",
             alleg="menyerang kehormatan seorang pejabat", demand="hingga 2 tahun"),
 "28_3": dict(charge="penyebaran berita bohong", statute="Pasal 28 ayat (3) UU ITE (informasi bohong yang menimbulkan keonaran)",
             alleg="menyebarkan informasi bohong yang menimbulkan keonaran", demand="hingga 6 tahun"),
 "28_2": dict(charge="ujaran kebencian", statute="Pasal 28 ayat (2) UU ITE (ujaran kebencian berbasis SARA)",
             alleg="menyebarkan kebencian terhadap kelompok tertentu", demand="hingga 6 tahun"),
 "310":  dict(charge="pencemaran nama baik", statute="Pasal 310 KUHP (pencemaran nama baik)",
             alleg="menuduhkan suatu perbuatan sehingga merusak nama baik seseorang", demand="hingga 9 bulan"),
 "1946": dict(charge="penyiaran kabar bohong", statute="Pasal 14 UU Nomor 1 Tahun 1946 (penyiaran kabar bohong)",
             alleg="menyiarkan kabar bohong", demand="hingga 10 tahun"),
}
ID_ISSUE = {
 "file_access": "tidak diberi akses ke sejumlah berkas perkara sehingga hak pembelaan terganggu.",
 "closed": "memprotes keputusan majelis hakim yang menutup sidang bagi pengamat.",
 "witness": "mengatakan saksi-saksi yang diajukan pembela tidak diizinkan memberikan keterangan.",
 "expert": "menyebut berita itu dipidana tanpa meminta pendapat ahli dari Dewan Pers.",
 "delay": "mengatakan perkara ini sudah berjalan dua tahun dan meminta peradilan diselesaikan dalam waktu yang wajar.",
 "recusal": "mengatakan permohonan pembela agar hakim diganti ditolak oleh majelis.",
 "pretrial": "menyatakan kliennya sudah ditahan {days} hari dan masa penahanan itu melampaui batas yang wajar.",
}
ID_OUT = {"acquit":"terdakwa dinyatakan bebas","prison":"terdakwa divonis {m} bulan penjara","suspended":"terdakwa dijatuhi pidana percobaan"}
ID_DET = {"free":"tidak ditahan selama persidangan","jailed":"masih ditahan di rumah tahanan","released":"tidak ditahan"}
ID_P5B = ["Organisasi jurnalis menilai kasus ini dapat menimbulkan efek jera bagi kebebasan pers.",
          "Aliansi jurnalis menyatakan akan memantau jalannya persidangan."]

ID_CASES = [
 dict(k="I1", name="Rahmat Hidayat", outlet="Suara Pesisir", city="Makassar", topic="dugaan korupsi proyek jalan kabupaten", ch="27A",
      court="Pengadilan Negeri Makassar", lawyer="Andi Pratiwi", pub="2025-09-02", arts=[
      ("indictment","2025-11-20",None,"2026-02-04","expert",None,"free",None),
      ("hearing","2026-03-18",2,"2026-04-15","file_access",None,"free",None)]),
 dict(k="I2", name="Ahmad Fauzi", outlet="Harian Borneo Raya", city="Pontianak", topic="kematian pasien di rumah sakit daerah", ch="28_3",
      court="Pengadilan Negeri Pontianak", lawyer="Yusuf Maulana", pub="2025-08-11", arts=[
      ("hearing","2026-01-28",3,"2026-02-25","pretrial",120,"jailed",None),
      ("verdict","2026-02-25",None,None,"witness",None,"jailed",("prison",8))]),
 dict(k="I3", name="Dewi Anggraini", outlet="Kabar Tambang", city="Palu", topic="izin tambang nikel", ch="1946",
      court="Pengadilan Negeri Palu", lawyer="Rina Susanti", pub="2025-10-05", arts=[
      ("indictment","2025-12-10",None,"2026-01-14","recusal",None,"free",None),
      ("verdict","2026-03-11",None,None,"expert",None,"released",("acquit",None))]),
 dict(k="I4", name="Ahmad Fauzi", outlet="Jawa Tengah Kini", city="Semarang", topic="pungutan liar di pelabuhan", ch="310",
      court="Pengadilan Negeri Semarang", lawyer="Bambang Wicaksono", pub="2025-11-17", arts=[
      ("hearing","2026-02-09",1,"2026-03-02","witness",None,"free",None),
      ("verdict","2026-03-30",None,None,"delay",None,"released",("suspended",None))]),
 dict(k="I5", name="Siti Marlina", outlet="Lombok Kita", city="Mataram", topic="konflik lahan antara dua kelompok warga", ch="28_2",
      court="Pengadilan Negeri Mataram", lawyer="Hasan Basri", pub="2025-12-22", arts=[
      ("indictment","2026-01-26",None,"2026-02-16","file_access",None,"free",None),
      ("hearing","2026-03-09",2,"2026-03-30","closed",None,"free",None)]),
 dict(k="I6", name="Yoga Pratama", outlet="Info Sumatera", city="Medan", topic="limbah pabrik kelapa sawit", ch="27A",
      court="Pengadilan Negeri Medan", lawyer="Maya Kartika", pub="2025-07-25", arts=[
      ("hearing","2026-03-05",4,"2026-03-26","delay",None,"free",None),
      ("verdict","2026-03-26",None,None,"recusal",None,"released",("acquit",None))]),
 dict(k="I7", name="Nur Aisyah", outlet="Warta Maluku", city="Ambon", topic="penyaluran bantuan bencana banjir", ch="28_3",
      court="Pengadilan Negeri Ambon", lawyer="Fitri Handayani", pub="2026-02-03", arts=[
      ("indictment","2026-04-14",None,"2026-05-05","expert",None,"jailed",None),
      ("hearing","2026-05-26",2,"2026-06-16","pretrial",63,"jailed",None)]),
 dict(k="I8", name="Bagus Setiawan", outlet="Sorot Kalimantan", city="Banjarmasin", topic="kualitas bangunan sekolah", ch="310",
      court="Pengadilan Negeri Banjarmasin", lawyer="Dedi Gunawan", pub="2026-03-14", arts=[
      ("hearing","2026-05-12",1,"2026-06-02","file_access",None,"free",None),
      ("verdict","2026-06-30",None,None,"expert",None,"released",("suspended",None))]),
 dict(k="I9", name="Lestari Wulandari", outlet="Berita Sulut", city="Manado", topic="pidato kampanye calon wali kota", ch="28_2",
      court="Pengadilan Negeri Manado", lawyer="Ratna Sari", pub="2026-04-01", arts=[
      ("indictment","2026-06-02",None,"2026-06-23","closed",None,"free",None),
      ("hearing","2026-07-14",2,"2026-08-04","recusal",None,"free",None)]),
 dict(k="I10", name="Hendra Kusuma", outlet="Kilas Jambi", city="Jambi", topic="pembalakan liar di hutan lindung", ch="1946",
      court="Pengadilan Negeri Jambi", lawyer="Agus Santoso", pub="2026-04-28", arts=[
      ("hearing","2026-07-21",3,"2026-08-11","expert",None,"free",None),
      ("verdict","2026-08-11",None,None,"delay",None,"released",("prison",6))]),
]

# ---------------- paragraph builders ----------------
def tr_doc(c, a, ai):
    stage,date,n,nxt,issue,days,det,outc = a; ch = TR_CH[c["ch"]]; name=c["name"]
    if stage=="indictment":
        p1=f"{c['outlet']} muhabiri {name} hakkında, {c['topic']} haberi nedeniyle {ch['charge']} suçlamasıyla dava açıldı."
        p3=f"İddianame, {c['court']} tarafından {d_tr(date)} tarihinde kabul edildi. İlk duruşma {d_tr(nxt)} tarihinde yapılacak."
        p6=f"Savcılık, {name} için {ch['demand']} hapis cezası talep ediyor. {name} {TR_DET[det]}."
        title=f"{c['outlet']} muhabiri {name} hakkında dava açıldı"
    elif stage=="hearing":
        p1=f"{c['outlet']} muhabiri {name} hakkında {ch['charge']} suçlamasıyla açılan davanın {n}. duruşması yapıldı."
        p3=f"Dava, {c['court']} önünde {d_tr(date)} tarihinde görüldü. Mahkeme, duruşmayı {d_tr(nxt)} tarihine erteledi."
        p6=f"Savcılık esas hakkındaki mütalaasını sonraki duruşmada sunacak. {name} {TR_DET[det]}."
        title=f"{name} davasında {n}. duruşma"
    else:
        o,m = outc; out = TR_OUT[o].format(m=m)
        p1=f"{c['outlet']} muhabiri {name} hakkında {ch['charge']} suçlamasıyla açılan davada karar açıklandı. Sonuç: {out}."
        p3=f"Karar, {c['court']} tarafından {d_tr(date)} tarihli duruşmada açıklandı. Gerekçeli karar henüz yayımlanmadı."
        p6=f"Karara karşı istinaf yoluna başvurulabilecek. {name} {TR_DET[det]}."
        title=f"{name} davasında karar"
    p2=f"İddianameye göre {name}, {d_tr(c['pub'])} tarihinde yayımlanan {c['topic']} haberiyle {ch['pred']}. Uygulanan hüküm: {ch['statute']}."
    p4=f"{name} davasında Avukat {c['lawyer']}, "+TR_ISSUE[issue].format(days=days)
    p5=f"{name}, {c['outlet']} adlı yayın organında {c['city']} muhabiri olarak çalışıyor. {TR_P5B[(ai+len(name))%2]}"
    return title,date,[p1,p2,p3,p4,p5,p6]

def id_doc(c, a, ai):
    stage,date,n,nxt,issue,days,det,outc = a; ch = ID_CH[c["ch"]]; name=c["name"]
    if stage=="indictment":
        p1=f"Wartawan {c['outlet']}, {name}, didakwa dengan tuduhan {ch['charge']} terkait berita tentang {c['topic']}."
        p3=f"Surat dakwaan dibacakan di {c['court']} pada {d_id(date)}. Sidang pertama pemeriksaan saksi dijadwalkan pada {d_id(nxt)}."
        p6=f"Ancaman hukuman untuk pasal ini adalah penjara {ch['demand']}. {name} {ID_DET[det]}."
        title=f"Wartawan {name} didakwa {ch['charge']}"
    elif stage=="hearing":
        p1=f"Sidang ke-{n} perkara {ch['charge']} terhadap wartawan {c['outlet']}, {name}, telah digelar."
        p3=f"Sidang digelar di {c['court']} pada {d_id(date)}. Majelis hakim menunda sidang hingga {d_id(nxt)}."
        p6=f"Jaksa akan membacakan tuntutan pada sidang berikutnya. {name} {ID_DET[det]}."
        title=f"Sidang ke-{n} wartawan {name}"
    else:
        o,m = outc; out = ID_OUT[o].format(m=m)
        p1=f"Putusan perkara {ch['charge']} terhadap wartawan {c['outlet']}, {name}, telah dibacakan. Hasilnya: {out}."
        p3=f"Majelis hakim {c['court']} membacakan putusan pada {d_id(date)}. Salinan putusan lengkap belum dipublikasikan."
        p6=f"Jaksa dan terdakwa masih dapat mengajukan banding. {name} {ID_DET[det]}."
        title=f"Putusan perkara wartawan {name}"
    p2=f"Menurut dakwaan, {name} menerbitkan berita tentang {c['topic']} pada {d_id(c['pub'])} yang dinilai jaksa {ch['alleg']}. Pasal yang digunakan: {ch['statute']}."
    p4=f"Dalam perkara {name}, kuasa hukum {c['lawyer']} "+ID_ISSUE[issue].format(days=days)
    p5=f"{name} bekerja sebagai wartawan {c['outlet']} di {c['city']}. {ID_P5B[(ai+len(name))%2]}"
    return title,date,[p1,p2,p3,p4,p5,p6]

TR_DIS = [
 ("Kıyıspor evinde farklı kazandı","2026-03-08",["Kıyıspor, sahasında oynadığı karşılaşmada rakibini 3-1 mağlup etti.","İlk yarı golsüz sona erdi. Konuk takım 52. dakikada öne geçti ancak ev sahibi son yarım saatte üç gol buldu.","Teknik direktör maç sonunda oyuncularının mücadelesinden memnun olduğunu söyledi.","Takım gelecek hafta deplasmanda ligin son sırasındaki ekiple karşılaşacak."]),
 ("Esnaf odası kira artışlarından şikayetçi","2026-04-02",["Bir esnaf odasının başkanı, dükkan kiralarındaki artışın küçük işletmeleri zorladığını söyledi.","Başkan, kira artış oranının yeni bir düzenlemeyle sınırlanmasını istedi.","Oda üyeleri önümüzdeki hafta belediye ile bir araya gelecek.","Esnaf, sezon öncesi müşteri sayısının düştüğünü belirtiyor."]),
 ("Sosyal medya paylaşımı nedeniyle iş insanına dava","2026-02-19",["Bursa'da bir iş insanı hakkında, sosyal medya hesabından yaptığı paylaşım nedeniyle halkı yanıltıcı bilgiyi alenen yayma suçlamasıyla dava açıldı.","Paylaşımda bir gıda üreticisinin ürünlerinin zehirli olduğu öne sürülmüştü.","İddianame Bursa 3. Asliye Ceza Mahkemesi tarafından kabul edildi. Uygulanan hüküm: Türk Ceza Kanunu 217/A (halkı yanıltıcı bilgiyi alenen yayma).","Sanık gazeteci değil, kendi adına bir tekstil firması işletiyor.","İlk duruşma Mayıs ayında yapılacak. Sanığın avukatı iddiaları reddediyor."]),
 ("Hafta sonu için kuvvetli yağış uyarısı","2026-01-10",["Meteoroloji, hafta sonu Ege kıyı şeridinde kuvvetli yağış beklendiğini duyurdu.","Sıcaklıkların beş derece düşmesi öngörülüyor.","Yetkililer vatandaşlara dere yataklarından uzak durmaları çağrısında bulundu.","Yağışın pazartesi günü etkisini kaybetmesi bekleniyor."]),
 ("Meclis üyesine hakaret davası","2026-05-06",["Antalya'da bir belediye meclis üyesi hakkında, bir kamu görevlisine hakaret ettiği iddiasıyla dava açıldı.","Uygulanan hüküm: Türk Ceza Kanunu 125 (hakaret). Antalya 4. Asliye Ceza Mahkemesi dosyayı kabul etti.","Olay, bir meclis toplantısında yaşanan tartışmadan kaynaklanıyor.","Sanık gazeteci değil. Avukatı, sözlerin eleştiri sınırları içinde kaldığını savunuyor."]),
]
ID_DIS = [
 ("Bintang Selatan FC menang telak","2026-03-02",["Bintang Selatan FC menang 3-1 atas lawannya pada laga kandang akhir pekan lalu.","Babak pertama berakhir tanpa gol. Tim tamu sempat unggul pada menit ke-52 sebelum tuan rumah membalas tiga kali.","Pelatih mengaku puas dengan semangat para pemainnya.","Pekan depan tim akan bertandang ke markas tim juru kunci."]),
 ("Pedagang keluhkan harga beras","2026-04-09",["Sejumlah pedagang pasar tradisional mengeluhkan kenaikan harga beras dalam dua pekan terakhir.","Ketua asosiasi pedagang meminta pemerintah daerah menggelar operasi pasar.","Pembeli mengaku mengurangi jumlah belanja harian.","Dinas perdagangan berjanji memeriksa pasokan di gudang."]),
 ("Pengguna media sosial didakwa sebarkan informasi bohong","2026-02-24",["Seorang pengguna media sosial di Surabaya didakwa menyebarkan informasi bohong yang menimbulkan keonaran.","Dakwaan memakai Pasal 28 ayat (3) UU ITE (informasi bohong yang menimbulkan keonaran).","Terdakwa bukan wartawan. Ia bekerja sebagai pedagang pakaian daring.","Sidang digelar di Pengadilan Negeri Surabaya dan ditunda hingga pekan depan.","Kuasa hukum terdakwa menyebut unggahan kliennya hanya candaan."]),
 ("Hujan lebat diprakirakan di wilayah barat","2026-01-18",["Badan prakiraan cuaca memperkirakan hujan lebat di wilayah barat selama tiga hari.","Warga di daerah rawan banjir diminta waspada.","Suhu udara diperkirakan turun beberapa derajat pada malam hari.","Cuaca diperkirakan membaik pada akhir pekan."]),
 ("Pengusaha dilaporkan atas tuduhan pencemaran nama baik","2026-05-12",["Seorang pengusaha di Bandung dilaporkan ke polisi atas tuduhan pencemaran nama baik terhadap mantan mitra bisnisnya.","Pelapor menggunakan Pasal 310 KUHP (pencemaran nama baik).","Terlapor bukan wartawan. Ia disebut menyebarkan tuduhan itu lewat pesan berantai.","Polisi sudah memeriksa dua saksi dan akan memanggil terlapor pekan depan."]),
]

def build_lang(lang, cases, builder, dis, prefix, seed):
    items=[]
    for c in cases:
        for ai,a in enumerate(c["arts"]):
            title,date,paras = builder(c,a,ai)
            items.append(dict(kind="case",case=c["k"],stage=a[0],art_i=ai,issue=a[4],title=title,date=date,paras=paras))
    for title,date,paras in dis:
        items.append(dict(kind="distractor",case=None,stage=None,art_i=None,issue=None,title=title,date=date,paras=paras))
    random.Random(seed).shuffle(items)
    docs=[]
    for i,it in enumerate(items,1):
        it["doc_id"]=f"{prefix}-{i:03d}"
        docs.append(it)
    return docs

def write_docs(docs, lang, folder):
    os.makedirs(folder, exist_ok=True)
    for d in docs:
        obj=dict(doc_id=d["doc_id"], lang=lang, title=d["title"], published=d["date"], synthetic=True, paragraphs=d["paras"])
        with open(os.path.join(folder,d["doc_id"]+".json"),"w",encoding="utf-8") as f:
            json.dump(obj,f,ensure_ascii=False,indent=1)

def pid(doc_id, idx): return f"{doc_id}#p{idx:03d}"

def main():
    if os.path.exists(OUT): shutil.rmtree(OUT)
    tr = build_lang("tr", TR_CASES, tr_doc, TR_DIS, "tr", 11)
    idn = build_lang("id", ID_CASES, id_doc, ID_DIS, "id", 22)
    write_docs(tr,"tr",os.path.join(OUT,"docs","tr")); write_docs(idn,"id",os.path.join(OUT,"docs","id"))
    alldocs = tr+idn
    cases = {c["k"]:c for c in TR_CASES+ID_CASES}

    def doc_of(case, art_i): 
        return next(d for d in alldocs if d["case"]==case and d["art_i"]==art_i)
    def case_docs(case): return [d for d in alldocs if d["case"]==case]
    def ev(case, art_is, idxs): return [pid(doc_of(case,i)["doc_id"],x) for i in art_is for x in idxs]
    def all_with(needle, idxs):
        r=[]
        for d in alldocs:
            if d["kind"]!="case": continue
            for x in idxs:
                if needle in d["paras"][x-1]: r.append(pid(d["doc_id"],x))
        return r
    def issue_paras(issue): return [pid(d["doc_id"],4) for d in alldocs if d["issue"]==issue]
    def topic_paras(case):
        t=cases[case]["topic"]; r=[]
        for d in case_docs(case):
            for x,p in enumerate(d["paras"],1):
                if t in p: r.append(pid(d["doc_id"],x))
        return r
    def para_text(p):
        did,x=p.split("#p"); d=next(d for d in alldocs if d["doc_id"]==did); return d["paras"][int(x)-1]

    Q=[]
    def add(facet,q,evid,needle=None):
        Q.append(dict(facet=facet,query=q,evidence=evid,needle=needle))
    # named-entity
    add("named-entity","Which court is hearing the case against Selin Karaoglu from Kıyı Haber?",ev("T1",[0,1],[3]),"İzmir 5. Asliye Ceza Mahkemesi")
    add("named-entity","Who is the defense lawyer of the journalist Zeynep Aydemir?",ev("T4",[0,1],[4]),"Selma Çakır")
    add("named-entity","Which news outlet does the journalist Dewi Anggraini work for, and in which city?",ev("I3",[0,1],[5]),"Kabar Tambang di Palu")
    add("named-entity","What did the lawyer of Mehmet Yıldız from the newspaper Doğu Postası complain about?",ev("T2",[0,1],[4]),"Hakan Demirtaş")
    add("named-entity","How many days has Ahmad Fauzi of Harian Borneo Raya been held in pretrial detention?",ev("I2",[0],[4]),"ditahan 120 hari")
    # legal-provision
    add("legal-provision","Which journalists are prosecuted under Article 217/A of the Turkish Penal Code on spreading misleading information?",all_with("Türk Ceza Kanunu 217/A",[2]),"Türk Ceza Kanunu 217/A")
    add("legal-provision","Who is on trial under Article 7/2 of the Anti-Terror Law because of a news report?",all_with("Terörle Mücadele Kanunu 7/2",[2]),"Terörle Mücadele Kanunu 7/2")
    add("legal-provision","Which reporters are charged under Article 28(3) of Indonesia's ITE Law for false information that causes unrest?",all_with("Pasal 28 ayat (3) UU ITE",[2]),"Pasal 28 ayat (3) UU ITE")
    add("legal-provision","Which journalist faces a defamation charge under Article 310 of the Indonesian Criminal Code?",all_with("Pasal 310 KUHP",[2]),"Pasal 310 KUHP")
    add("legal-provision","Is any journalist accused of breaching the confidentiality of an investigation?",all_with("Türk Ceza Kanunu 285",[2]),"Türk Ceza Kanunu 285")
    # procedural-event
    add("procedural-event","When is the next hearing in the case of Gülşen Tarhan?",ev("T6",[0],[3]),"21 Mayıs 2026")
    add("procedural-event","What was the outcome of the trial of Nilay Ertürk?",ev("T8",[1],[1]),"beraat")
    add("procedural-event","Which journalists had the announcement of their judgment deferred (HAGB)?",all_with("hükmün açıklanmasının geri bırakılması",[1]),"geri bırakılması")
    add("procedural-event","On what date did the court accept the indictment against Burak Sezer?",ev("T7",[0],[3]),"3 Mart 2026")
    add("procedural-event","Which journalist was found not guilty by the Medan District Court?",ev("I6",[1],[1,3]))
    # fair-trial-right
    add("fair-trial-right","Whose lawyer said the defense was denied access to documents in the case file?",issue_paras("file_access"))
    add("fair-trial-right","In which trials were observers kept out because the hearing was closed?",issue_paras("closed"))
    add("fair-trial-right","Which journalists were held in pretrial detention for longer than is reasonable?",issue_paras("pretrial"))
    add("fair-trial-right","Whose lawyer objected that defense witnesses were not allowed to testify?",issue_paras("witness"))
    add("fair-trial-right","In which cases did the defense say a request to replace the judge was rejected?",issue_paras("recusal"))
    # paraphrase
    add("paraphrase","A reporter is accused of misleading the public after writing about deaths in a hospital's critical care unit.",topic_paras("T4"))
    add("paraphrase","A journalist was charged after investigating licences for nickel extraction.",topic_paras("I3"))
    add("paraphrase","A newsroom employee is being prosecuted over reporting on how well school buildings were constructed.",topic_paras("I8"))
    add("paraphrase","A reporter faces trial for coverage of people who lost their lives in a town near the frontier.",topic_paras("T7"))
    # multi-doc
    add("multi-doc","Which journalists were acquitted?",ev("T3",[1],[1])+ev("T8",[1],[1])+ev("I3",[1],[1])+ev("I6",[1],[1]))
    add("multi-doc","Which journalists were sentenced to prison?",ev("T6",[1],[1])+ev("I2",[1],[1])+ev("I10",[1],[1]))
    add("multi-doc","Which Indonesian journalists received a suspended sentence?",ev("I4",[1],[1])+ev("I8",[1],[1]))
    # cross-lingual-pair
    add("cross-lingual-pair","Reporters charged after covering patient deaths in public hospitals, in Turkey and in Indonesia.",topic_paras("T4")+topic_paras("I2"))
    add("cross-lingual-pair","Journalists on trial for reporting on the distribution of disaster relief aid.",topic_paras("T3")+topic_paras("I7"))
    add("cross-lingual-pair","Journalists prosecuted over environmental reporting such as waste leaks, palm oil effluent or illegal logging.",topic_paras("T6")+topic_paras("I6")+topic_paras("I10"))

    # verify
    for i,q in enumerate(Q,1):
        assert q["evidence"], f"q{i} empty evidence"
        if q["needle"]:
            for p in q["evidence"]: assert q["needle"] in para_text(p), (i,p,q["needle"])
    with open(os.path.join(OUT,"queries.jsonl"),"w",encoding="utf-8") as f:
        for i,q in enumerate(Q,1):
            gold=sorted({p.split("#")[0] for p in q["evidence"]})
            f.write(json.dumps(dict(qid=f"q{i:02d}",query=q["query"],facet=q["facet"],gold_docs=gold,evidence=q["evidence"]),ensure_ascii=False)+"\n")
    # also a lookup of doc ids per case for inspection
    with open(os.path.join(os.path.dirname(OUT),"answer_key_case_index.json"),"w",encoding="utf-8") as f:
        json.dump({d["doc_id"]:dict(case=d["case"],stage=d["stage"],title=d["title"]) for d in alldocs},f,ensure_ascii=False,indent=1)
    from collections import Counter
    print("docs:",len(alldocs),Counter(d["doc_id"][:2] for d in alldocs))
    print("queries:",len(Q),Counter(q["facet"] for q in Q))
    print("evidence sizes:",[len(q["evidence"]) for q in Q])
if __name__=="__main__": main()
