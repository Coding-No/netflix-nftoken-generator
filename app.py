"""
app.py — Netflix NFToken Generator (web UI, FastAPI).

Fitur:
- Paste / upload banyak cookie (Netscape, raw, JSON, ZIP) -> generate masal
- Tabel hasil: status, link nftoken (klik-copy), expiry
- Export: JSON, CSV, TXT (satu link per baris), ZIP
- Proxy opsional + concurrency
- Endpoint API untuk otomasi
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import zipfile
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

import nftoken as N

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(APP_DIR, "out")
os.makedirs(OUT_DIR, exist_ok=True)
LAST_FILE = os.path.join(APP_DIR, "last_run.json")

app = FastAPI(title="Netflix NFToken Generator")


# ------------------------------------------------------------------ helpers
def _split_items(text: str) -> list[dict]:
    """Pecah blok input jadi item per akun.

    Aturan: item dipisah baris kosong ganda ATAU garis '----'.
    Tiap item = satu blok cookie (Netscape multi-baris / raw / JSON satu baris).
    """
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    # JSON langsung (list/dict)
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and isinstance(data[0], dict) and "NetflixId" in data[0]:
            return [{"label": f"item{i+1}", "raw": json.dumps(d)} for i, d in enumerate(data)]
    except Exception:
        pass
    raw_items = [b.strip() for b in text.split("\n\n") if b.strip()]
    if len(raw_items) == 1:
        raw_items = [b.strip() for b in text.split("\n----") if b.strip()]
    out = []
    for i, blk in enumerate(raw_items):
        # label dari NetflixId yang kebaca (dipotong) kalau ada
        ck = N.extract_cookie_dict(blk)
        label = (ck.get("NetflixId", "")[:18] or f"item{i+1}")
        out.append({"label": label, "raw": blk})
    return out


def _save_last(items, results, meta=None):
    try:
        with open(LAST_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": int(time.time()), "meta": meta or {},
                       "results": results}, f, ensure_ascii=False)
    except Exception:
        pass


def _read_last():
    try:
        return json.load(open(LAST_FILE, encoding="utf-8"))
    except Exception:
        return {"ts": 0, "results": []}


# ------------------------------------------------------------------ models
class GenIn(BaseModel):
    text: str = ""
    workers: int = 8
    proxy: Optional[str] = None
    timeout: int = 30


# ------------------------------------------------------------------ routes
@app.get("/", response_class=HTMLResponse)
def home():
    return HTML_PAGE


@app.post("/api/generate")
def api_generate(inp: GenIn):
    items = _split_items(inp.text)
    if not items:
        return JSONResponse({"ok": False, "error": "Tidak ada cookie terdeteksi"}, status_code=400)
    t0 = time.time()
    results = N.process_bulk(items, workers=inp.workers, proxy=inp.proxy, timeout=inp.timeout)
    summary = _summarize(results, t0, inp.workers)
    _save_last(items, results, summary)
    return {"ok": True, "summary": summary, "results": results}


def _summarize(results, t0, workers):
    alive = sum(1 for r in results if r.get("alive"))
    tok = sum(1 for r in results if r.get("ok") and r.get("token"))
    dead = len(results) - alive
    scan_times = [r.get("scan_elapsed") or 0 for r in results]
    chk_times = [r.get("check_elapsed") or r.get("elapsed") or 0 for r in results if r.get("check_elapsed") or r.get("elapsed")]
    gen_times = [r.get("gen_elapsed") or 0 for r in results if (r.get("gen_elapsed") or 0) > 0]
    avg = lambda a: round(sum(a) / len(a), 2) if a else 0
    return {
        "total": len(results), "alive": alive, "dead": dead, "tokens": tok,
        "elapsed": round(time.time() - t0, 2), "workers": workers,
        "avg_check": avg(chk_times), "avg_gen": avg(gen_times),
        "avg_scan": avg(scan_times),
        "slowest": round(max(scan_times), 2) if scan_times else 0,
        "fastest": round(min([t for t in scan_times if t > 0]), 2) if any(scan_times) else 0,
    }


@app.post("/api/generate/zip")
async def api_generate_zip(file: UploadFile = File(...), workers: int = Form(8),
                           proxy: str = Form(""), timeout: int = Form(30)):
    raw = await file.read()
    items: list[dict] = []
    if file.filename.lower().endswith(".zip") or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                try:
                    body = z.read(name).decode("utf-8", "ignore")
                except Exception:
                    continue
                if "NetflixId" not in body:
                    continue
                items.extend(_split_items(body))
    else:
        items = _split_items(raw.decode("utf-8", "ignore"))

    if not items:
        return JSONResponse({"ok": False, "error": "Tidak ada cookie Netflix di file"}, status_code=400)
    t0 = time.time()
    results = N.process_bulk(items, workers=workers, proxy=proxy or None, timeout=timeout)
    summary = _summarize(results, t0, workers)
    _save_last(items, results, summary)
    return {"ok": True, "summary": summary, "results": results}


@app.get("/api/last")
def api_last():
    return _read_last()


@app.get("/export")
def export(fmt: str = "json", only: str = "ALL"):
    d = _read_last()
    rows = d.get("results", [])
    if only.upper() == "ALIVE":
        rows = [r for r in rows if r.get("ok")]
    if fmt == "json":
        return JSONResponse({"ts": d.get("ts"), "results": rows})
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["label", "status", "valid", "ok", "token", "link", "expires_str", "validity_days", "validity_str", "check_elapsed", "gen_elapsed", "error", "cookie_keys"])
        for r in rows:
            w.writerow([r.get("label", ""), r.get("status", ""), r.get("alive"),
                        r.get("ok"), r.get("token", ""), r.get("link", ""),
                        r.get("expires_str", ""), r.get("validity_days", ""), r.get("validity_str", ""),
                        r.get("check_elapsed", ""), r.get("gen_elapsed", ""),
                        r.get("error", ""), ",".join(r.get("cookie_keys", []))])
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=nftokens.csv"})
    if fmt == "txt":
        lines = [r["link"] for r in rows if r.get("ok") and r.get("link")]
        return PlainTextResponse("\n".join(lines) + ("\n" if lines else ""),
                                 headers={"Content-Disposition": "attachment; filename=nftokens.txt"})
    if fmt == "links":
        # label<TAB>link, buat copy-paste spreadsheet
        lines = [f'{r.get("label","")}\t{r["link"]}' for r in rows if r.get("ok") and r.get("link")]
        return PlainTextResponse("\n".join(lines) + ("\n" if lines else ""),
                                 headers={"Content-Disposition": "attachment; filename=nftokens.tsv"})
    return JSONResponse({"error": "fmt tidak dikenal (json/csv/txt/links)"}, status_code=400)


@app.get("/export/zip")
def export_zip(only: str = "ALIVE"):
    d = _read_last()
    rows = d.get("results", [])
    if only.upper() == "ALIVE":
        rows = [r for r in rows if r.get("ok")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_readme.txt",
                   "Netflix NFToken — hasil generate\n\n"
                   "Tiap file .txt isi 1 link login nftoken.\n"
                   "Buka link di browser (sudah login otomatis).\n"
                   "File all_links.txt = semua link, 1 per baris.\n"
                   "File links.tsv = label<TAB>link (buat spreadsheet).\n")
        all_links = []
        for i, r in enumerate(rows, 1):
            if not (r.get("ok") and r.get("link")):
                continue
            label = (r.get("label") or f"item{i}").replace("/", "_")[:60]
            dur = r.get("validity_str") or (f"{r.get('validity_days')} hari" if r.get("validity_days") is not None else "-")
            body = (f"LINK LOGIN NETFLIX (nftoken)\n"
                    f"===========================\n"
                    f"{r['link']}\n\n"
                    f"Berlaku sampai : {r.get('expires_str') or '-'}\n"
                    f"Durasi         : {dur}\n"
                    f"Valid?         : {'YA' if r.get('alive') else 'TIDAK'}\n"
                    f"Waktu cek      : {r.get('check_elapsed', '-')}s\n"
                    f"Waktu generate : {r.get('gen_elapsed', '-')}s\n")
            z.writestr(f"{i:03d}_{label}.txt", body)
            all_links.append(r["link"])
        z.writestr("all_links.txt", "\n".join(all_links) + ("\n" if all_links else ""))
        tsv = "\n".join(f'{r.get("label","")}\t{r["link"]}' for r in rows if r.get("ok") and r.get("link"))
        z.writestr("links.tsv", tsv + ("\n" if tsv else ""))
    buf.seek(0)
    return PlainTextResponse(buf.read(), media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=nftokens.zip"})


HTML_PAGE = r"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Netflix NFToken Generator</title>
<style>
:root{--bg:#0b0d12;--card:#141821;--bd:#232a37;--tx:#e6edf3;--mut:#8b98a9;--ac:#e50914;--ok:#2ecc71;--bad:#e74c3c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:16px 18px;background:linear-gradient(90deg,#e50914,#8b0000);font-weight:700;font-size:20px}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px;margin-bottom:14px}
textarea{width:100%;min-height:170px;background:#0d1017;color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:10px;font:13px/1.45 ui-monospace,Menlo,monospace}
input,button{font:inherit}
input[type=text],input[type=number]{background:#0d1017;color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:8px 10px}
button{background:var(--ac);color:#fff;border:0;border-radius:8px;padding:9px 14px;cursor:pointer;font-weight:600}
button.alt{background:#2a3341}
button.mini{padding:5px 9px;font-size:12px}
button:disabled{opacity:.55;cursor:not-allowed}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.muted{color:var(--mut);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid var(--bd);padding:7px 8px;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
.pill{padding:2px 8px;border-radius:999px;font-size:11.5px;font-weight:700}
.ok{background:rgba(46,204,113,.15);color:var(--ok);border:1px solid rgba(46,204,113,.4)}
.bad{background:rgba(231,76,60,.15);color:var(--bad);border:1px solid rgba(231,76,60,.4)}
.link{color:#4da3ff;text-decoration:none;word-break:break-all;font-family:ui-monospace,monospace;font-size:12px}
.bar{height:8px;background:#1b2230;border-radius:6px;overflow:hidden}
.bar>i{display:block;height:100%;width:0;background:var(--ac);transition:width .2s}
.stat{font-size:22px;font-weight:800}
.stat.ok{color:var(--ok);background:none;border:0;padding:0}
.stat.bad{color:var(--bad);background:none;border:0;padding:0}
.mono{font-family:ui-monospace,monospace}
details summary{cursor:pointer;color:var(--mut)}
#toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#1f2733;border:1px solid var(--bd);padding:10px 16px;border-radius:10px;display:none;z-index:99}
</style></head><body>
<header>🎬 Netflix NFToken Generator</header>
<div class="wrap">

  <div class="card">
    <b>1. Tempel cookie Netflix kamu</b>
    <div class="muted" style="margin:6px 0 8px">
      Dukung: <b>Netscape</b> (tab-separated, yang kamu punya) · <b>raw</b>
      (<span class="mono">NetflixId=xxx; SecureNetflixId=yyy</span>) · <b>JSON</b>.
      Banyak akun sekaligus: <b>pisahkan tiap akun dengan 1 baris kosong</b> atau <span class="mono">----</span>.
    </div>
    <textarea id="in" placeholder=".netflix.com&#9;TRUE&#9;/&#9;TRUE&#9;1815430833&#9;NetflixId&#9;ct%3D...

(kosongkan 1 baris untuk akun berikutnya)

.netflix.com&#9;TRUE&#9;/&#9;TRUE&#9;1815430833&#9;NetflixId&#9;ct%3D..."></textarea>
    <div class="row" style="margin-top:10px">
      <label class="muted">Workers <input id="wk" type="number" value="8" min="1" max="32" style="width:70px"></label>
      <label class="muted">Timeout(s) <input id="to" type="number" value="30" min="5" max="120" style="width:70px"></label>
      <label class="muted" style="flex:1;min-width:200px">Proxy (opsional)
        <input id="px" type="text" placeholder="http://user:pass@ip:port" style="width:100%"></label>
    </div>
    <div class="row" style="margin-top:10px">
      <button id="go">🚀 Generate NFToken</button>
      <button class="alt" id="clr">Bersihkan</button>
      <span id="msg" class="muted"></span>
    </div>
  </div>

  <div class="card">
    <b>2. Upload file (opsional)</b>
    <div class="muted" style="margin:6px 0 8px">File <b>.txt</b> / <b>.json</b> / <b>.zip</b> berisi banyak cookie. Otomatis diproses.</div>
    <div class="row">
      <input type="file" id="file" accept=".txt,.json,.zip,.csv">
      <button class="alt" id="upgo">📦 Proses file</button>
    </div>
  </div>

  <div class="card" id="rescard" style="display:none">
    <div class="row" style="justify-content:space-between">
      <div>
        <span class="stat ok" id="s_alive">0</span> <span class="muted">hidup</span>
        &nbsp;·&nbsp;
        <span class="stat bad" id="s_dead">0</span> <span class="muted">mati</span>
        &nbsp;·&nbsp;
        <span class="stat ok" id="s_tok">0</span> <span class="muted">token jadi</span>
        &nbsp;·&nbsp; <span class="muted" id="s_meta"></span>
      </div>
      <div class="row">
        <a id="dl_zip" href="/export/zip?only=ALIVE"><button class="alt mini">⬇️ ZIP (hidup)</button></a>
        <a id="dl_txt" href="/export?fmt=txt&only=ALIVE"><button class="alt mini">⬇️ TXT</button></a>
        <a id="dl_csv" href="/export?fmt=csv&only=ALL"><button class="alt mini">⬇️ CSV</button></a>
        <a id="dl_json" href="/export?fmt=json&only=ALL"><button class="alt mini">⬇️ JSON</button></a>
      </div>
    </div>
    <div class="row muted" id="s_timing" style="margin:8px 0;gap:16px"></div>
    <div class="bar" style="margin:12px 0"><i id="bar"></i></div>
    <div style="overflow:auto;max-height:60vh">
      <table id="tb"><thead><tr>
        <th>#</th><th>Tahap 1: Valid?</th><th>Tahap 2: Link NFToken</th>
        <th>Berlaku sampai</th><th>Durasi</th><th>Cookie</th>
      </tr></thead><tbody></tbody></table>
    </div>
    <div class="muted" style="margin-top:8px">
      Alur otomatis: <b>cek valid</b> → kalau valid <b>langsung generate token</b> → tampil <b>durasinya</b>.
      Klik "Salin" buat ambil link. Link = login otomatis (buka di incognito kalau mau akun terpisah).
    </div>
  </div>

  <div class="card muted">
    Cara kerja: cookie <span class="mono">NetflixId</span> dikirim ke endpoint Argo iOS Netflix
    (<span class="mono">/iosui/user/15.48</span>) → token <span class="mono">createAutoLoginToken</span> →
    link <span class="mono">https://netflix.com/?nftoken=...</span>. Token berlaku ±30 hari.
  </div>
</div>
<div id="toast"></div>
<script>
const $=s=>document.querySelector(s);
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',1800);}
function copy(t){navigator.clipboard.writeText(t).then(()=>toast('Disalin ✓'));}
function render(d){
  const rows=d.results||[];const s=d.summary||{};
  $('#rescard').style.display='block';
  $('#s_alive').textContent=s.alive??rows.filter(r=>r.alive).length;
  $('#s_dead').textContent=s.dead??rows.filter(r=>!r.alive).length;
  $('#s_tok').textContent=s.tokens??rows.filter(r=>r.token).length;
  $('#s_meta').textContent=(s.total||rows.length)+' total · '+(s.elapsed||'?')+'s · '+(s.workers||8)+' workers';
  if(s.avg_check!==undefined){
    $('#s_timing').innerHTML=
      '⏱️ total proses: <b>'+(s.elapsed||0)+'s</b>'+
      ' · rata-rata cek valid: <b>'+(s.avg_check||0)+'s</b>'+
      ' · rata-rata generate token: <b>'+(s.avg_gen||0)+'s</b>'+
      ' · per akun: <b>'+(s.avg_scan||0)+'s</b>'+
      ' · tercepat: <b>'+(s.fastest||0)+'s</b> · terlama: <b>'+(s.slowest||0)+'s</b>';
  }
  $('#bar').style.width='100%';
  const tb=$('#tb tbody');tb.innerHTML='';
  rows.forEach((r,i)=>{
    const tr=document.createElement('tr');
    const t1=r.state||''; 
    const validPill = r.alive ? '<span class="pill ok">VALID</span>'
                              : '<span class="pill bad">MATI</span>';
    let dur='-', exp=r.expires_str||'-';
    if(r.validity_str){dur='<b>'+r.validity_str+'</b>';}
    else if(r.validity_days!==undefined && r.validity_days!==null){dur='<b>'+r.validity_days+' hari</b>';}
    let t2;
    if(r.token&&r.link){
      t2='<a class="link" href="'+r.link+'" target="_blank">'+r.link.slice(0,70)+'…</a> '
       +'<button class="mini alt" data-c="'+encodeURIComponent(r.link)+'">Salin</button> '
       +'<a target="_blank" href="'+r.link+'"><button class="mini">Buka</button></a>';
    }else if(r.alive){
      t2='<span class="muted">valid tapi token gagal: '+((r.error||'')+'')+'</span>';
    }else{
      t2='<span class="muted">'+((r.error||'cookie mati'))+'</span>';
    }
    const cookieTxt=(r.cookie_keys||[]).join(', ')||'-';
    tr.innerHTML='<td>'+(i+1)+'</td>'
      +'<td>'+validPill+((r.check_elapsed)?' <span class="muted">'+(r.check_elapsed)+'s</span>':'')+'</td>'
      +'<td>'+t2+'</td>'
      +'<td class="mono">'+exp+'</td>'
      +'<td>'+dur+'</td>'
      +'<td class="muted">'+cookieTxt+'</td>';
    tb.appendChild(tr);
  });
  tb.querySelectorAll('button[data-c]').forEach(b=>b.onclick=()=>copy(decodeURIComponent(b.dataset.c)));
  toast('Selesai: '+(s.tokens??0)+' token dari '+(s.alive??0)+' akun hidup');
}
async function generate(){
  const text=$('#in').value.trim();
  if(!text){toast('Tempel cookie dulu');return;}
  $('#go').disabled=true;$('#msg').textContent='Memproses…';$('#bar').style.width='25%';
  try{
    const body={text,workers:+$('#wk').value||8,timeout:+$('#to').value||30,proxy:$('#px').value.trim()||null};
    const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(!d.ok){toast(d.error||'Gagal');$('#msg').textContent=d.error||'';}
    else render(d);
  }catch(e){toast('Error: '+e);}finally{$('#go').disabled=false;$('#msg').textContent='';}
}
async function genFile(){
  const f=$('#file').files[0];if(!f){toast('Pilih file dulu');return;}
  $('#upgo').disabled=true;$('#bar').style.width='25%';
  try{
    const fd=new FormData();fd.append('file',f);fd.append('workers',$('#wk').value||'8');
    fd.append('proxy',$('#px').value.trim());fd.append('timeout',$('#to').value||'30');
    const r=await fetch('/api/generate/zip',{method:'POST',body:fd});
    const d=await r.json();
    if(!d.ok)toast(d.error||'Gagal');else render(d);
  }catch(e){toast('Error: '+e);}finally{$('#upgo').disabled=false;}
}
$('#go').onclick=generate;$('#upgo').onclick=genFile;$('#clr').onclick=()=>{$('#in').value='';};
// muat hasil terakhir kalau ada
fetch('/api/last').then(r=>r.json()).then(d=>{if(d.results&&d.results.length)render({results:d.results,summary:null});}).catch(()=>{});
</script></body></html>"""
