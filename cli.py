#!/usr/bin/env python3
"""CLI: python3 cli.py cookies.txt  -> cetak link nftoken tiap akun.

cookies.txt bisa berisi 1 atau banyak akun (pisah baris kosong).
"""
import sys, json, time
import nftoken as N

def main():
    path = sys.argv[1] if sys.argv[1:] else None
    if not path:
        print("pemakaian: python3 cli.py <file-cookie> [workers]"); sys.exit(1)
    text = open(path, encoding="utf-8").read()
    blocks = [b.strip() for b in text.replace("\r\n","\n").split("\n\n") if b.strip()] or [text]
    items = [{"label": N.extract_cookie_dict(b).get("NetflixId","")[:18] or f"item{i+1}", "raw": b}
             for i,b in enumerate(blocks)]
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    t0=time.time()
    res = N.generate_bulk(items, workers=w)
    alive=0
    for r in res:
        if r.get("ok"):
            alive+=1; print(f"[HIDUP] {r['link']}  (exp {r.get('expires_str')})")
        else:
            print(f"[MATI ] {r.get('label','')} -> {r.get('error')}")
    print(f"\n{alive}/{len(res)} hidup  ({time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
