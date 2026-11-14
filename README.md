# 🎬 Netflix NFToken Generator

Generate **link auto-login Netflix** (`nftoken`) dari session cookie `NetflixId`.
Single atau **bulk (banyak akun sekaligus)** + web UI + CLI + export.

Terinspirasi dari [`harshitkamboj/Netflix-NFToken-Generator`](https://github.com/harshitkamboj/Netflix-NFToken-Generator),
dikembangkan jadi tool lengkap: bulk GUI, deteksi hidup/mati, export ZIP/CSV/TXT, concurrent, proxy.

---

## Cara kerja (singkat)

```
cookie NetflixId  ──►  Argo iOS endpoint Netflix  ──►  token  ──►  link login
                       /iosui/user/15.48
                       operationName: createAutoLoginToken
```

Token berlaku ±30 hari. Link bentuknya:

```
https://netflix.com/?nftoken=<token>
```

Buka link itu di browser → **langsung login** tanpa password.

---

## Fitur

- ✅ **Alur 2 tahap otomatis**: cek valid → kalau hidup langsung generate token
- ✅ **Tampil durasi**: per akun (waktu cek & generate) + total proses
- ✅ **Bulk** — tempel/upload banyak akun sekaligus, jalan paralel (workers)
- ✅ **Auto-detect** hidup/mati + alasan mati
- ✅ **Dukung format**: Netscape (tab-separated), raw (`NetflixId=...; SecureNetflixId=...`), JSON
- ✅ **Upload** `.txt` / `.json` / `.zip` → diproses otomatis
- ✅ **Export**: ZIP (1 file per akun + all_links.txt + links.tsv), TXT, CSV, JSON
- ✅ **Web UI** (paste/upload) + **CLI** + **HTTP API**
- ✅ **Proxy** opsional + timeout & concurrency yang bisa diatur

### Alur 2 tahap (persis kayak yang diminta)

```
cookie masuk
   ↓
TAHAP 1: cek valid   → hit endpoint Netflix, cookie hidup/mati?   (≈0.3–0.5s)
   ↓ (kalau hidup)
TAHAP 2: generate    → createAutoLoginToken → link nftoken        (≈0.3–0.5s)
   ↓
HASIL: link + berlaku sampai + DURASI (per akun & total proses)
```

Tabel hasil punya kolom **"Tahap 1: Valid?"** → **"Tahap 2: Link NFToken"**,
plus **"Berlaku sampai"** dan **"Durasi"** (mis. `29 hari 6 jam`).
Di bawah tabel ada ringkasan: total proses, rata-rata cek, rata-rata generate,
per akun, tercepat, terlama.

---

## Jalankan

```bash
pip install -r requirements.txt
python3 -m uvicorn app:app --host 0.0.0.0 --port 8899
# atau
./run.sh 8899
```

Buka **http://127.0.0.1:8899**

### CLI

```bash
python3 cli.py cookies.txt 8
```

### API

```bash
curl -sX POST http://127.0.0.1:8899/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":".netflix.com\tTRUE\t/\tTRUE\t1815430833\tNetflixId\tct%3D...","workers":8}' | jq
```

---

## Format input cookie

### 1) Netscape (dari ekstensi Export Cookies)

```
.netflix.com	TRUE	/	TRUE	1815430833	NetflixId	ct%3D...
.netflix.com	TRUE	/	TRUE	1815430833	SecureNetflixId	v%3D3%26mac%3D...
```

### 2) Raw

```
NetflixId=ct%3D...; SecureNetflixId=v%3D3%26mac%3D...;
```

### 3) Banyak akun

Pisahkan tiap akun dengan **satu baris kosong** atau `----`:

```
.netflix.com	TRUE	/	TRUE	...	NetflixId	ct%3DAAA...
<baris kosong>
.netflix.com	TRUE	/	TRUE	...	NetflixId	ct%3DBBB...
```

---

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET | `/` | Web UI |
| POST | `/api/generate` | `{text, workers, proxy, timeout}` → hasil |
| POST | `/api/generate/zip` | upload file (multipart) → hasil |
| GET | `/api/last` | hasil terakhir |
| GET | `/export?fmt=json\|csv\|txt\|links&only=ALIVE\|ALL` | export |
| GET | `/export/zip?only=ALIVE` | ZIP hasil |

---

## Struktur

```
netflix_nftoken/
├── app.py            # FastAPI + Web UI
├── nftoken.py        # modul inti (parse cookie, generate token, bulk)
├── cli.py            # CLI
├── run.sh            # runner
├── requirements.txt
└── LICENSE
```

---

## Catatan

- Cookie harus **masih valid** (session belum logout). Kalau `NetflixId` expired → hasil MATI.
- Token = akses penuh ke akun. Simpan baik-baik, jangan share sembarangan.
- Pakai proxy kalau generate banyak akun dari satu IP agar tidak di-rate-limit.

---

## License

MIT
