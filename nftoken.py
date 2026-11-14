"""
nftoken.py — Netflix NFToken generator (single + bulk).

NFToken = link auto-login Netflix yang dihasilkan dari session cookie
(NetflixId) lewat endpoint iOS Argo GraphQL `createAutoLoginToken`.

Format hasil: https://netflix.com/?nftoken=<TOKEN>

Mendukung input cookie: Netscape, raw "Name=Value; ...", JSON (list/dict),
dan otomatis unquote (%3D -> =) untuk NetflixId/SecureNetflixId.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

# ------------------------------------------------------------------ config
API_URL = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"

QUERY_PARAMS = {
    "appVersion": "15.48.1",
    "config": (
        '{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false",'
        '"cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true",'
        '"addHorizontalBoxArtToVideoSummariesEnabled":"false","skOverlayTestEnabled":"false",'
        '"homeFeedTestTVMovieListsEnabled":"false","baselineOnIpadEnabled":"true",'
        '"trailersVideoIdLoggingFixEnabled":"true","postPlayPreviewsEnabled":"false",'
        '"bypassContextualAssetsEnabled":"false","roarEnabled":"false",'
        '"useSeason1AltLabelEnabled":"false",'
        '"disableCDSSearchPaginationSectionKinds":["searchVideoCarousel"],'
        '"cdsSearchHorizontalPaginationEnabled":"true","searchPreQueryGamesEnabled":"true",'
        '"kidsMyListEnabled":"true","billboardEnabled":"true","useCDSGalleryEnabled":"true",'
        '"contentWarningEnabled":"true","videosInPopularGamesEnabled":"true",'
        '"avifFormatEnabled":"false","sharksEnabled":"true"}'
    ),
    "device_type": "NFAPPL-02-",
    "esn": ("NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200"),
    "idiom": "phone",
    "iosVersion": "15.8.5",
    "isTablet": "false",
    "languages": "en-US",
    "locale": "en-US",
    "maxDeviceWidth": "375",
    "model": "saget",
    "modelType": "IPHONE8-1",
    "odpAware": "true",
    "path": '["account","token","default"]',
    "pathFormat": "graph",
    "pixelDensity": "2.0",
    "progressive": "false",
    "responseFormat": "json",
}

ESN_PLAIN = ("NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200")

BASE_HEADERS = {
    "User-Agent": "Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.attempt": "1",
    "x-netflix.request.client.user.guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.context.profile-guid": "A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.request.routing": '{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.context.app-version": "15.48.1",
    "x-netflix.argo.translated": "true",
    "x-netflix.context.form-factor": "phone",
    "x-netflix.context.sdk-version": "2012.4",
    "x-netflix.client.appversion": "15.48.1",
    "x-netflix.context.max-device-width": "375",
    "x-netflix.context.ab-tests": "",
    "x-netflix.tracing.cl.useractionid": "4DC655F2-9C3C-4343-8229-CA1B003C3053",
    "x-netflix.client.type": "argo",
    "x-netflix.client.ftl.esn": ESN_PLAIN,
    "x-netflix.context.locales": "en-US",
    "x-netflix.context.top-level-uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.client.iosversion": "15.8.5",
    "accept-language": "en-US;q=1",
    "x-netflix.argo.abtests": "",
    "x-netflix.context.os-version": "15.8.5",
    "x-netflix.request.client.context": '{"appState":"foreground"}',
    "x-netflix.context.ui-flavor": "argo",
    "x-netflix.argo.nfnsm": "9",
    "x-netflix.context.pixel-density": "2.0",
    "x-netflix.request.toplevel.uuid": "90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.request.client.timezoneid": "Asia/Dhaka",
}

COOKIE_KEYS = ("NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent")
REQUIRED_COOKIE = "NetflixId"


# ------------------------------------------------------------------ parsing
def parse_netscape_cookie_line(line: str) -> dict:
    parts = line.strip().split("\t")
    if len(parts) >= 7:
        return {parts[5]: parts[6]}
    return {}


def _decode(value):
    if isinstance(value, str) and "%" in value:
        try:
            return urllib.parse.unquote(value)
        except Exception:
            return value
    return value


def extract_cookie_dict(text: str) -> dict:
    """Ambil cookie Netflix dari teks apa pun (Netscape / raw / JSON)."""
    cookie_dict: dict[str, str] = {}

    # Netscape (tab-separated)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            cookie_dict.update(parse_netscape_cookie_line(line))

    # JSON
    try:
        data = json.loads(text)
    except Exception:
        data = None

    if isinstance(data, list):
        for c in data:
            if isinstance(c, dict) and c.get("name") in COOKIE_KEYS and isinstance(c.get("value"), str):
                cookie_dict[c["name"]] = _decode(c["value"])
    elif isinstance(data, dict):
        if any(k in data for k in COOKIE_KEYS):
            for k in COOKIE_KEYS:
                v = data.get(k)
                if isinstance(v, str):
                    cookie_dict[k] = _decode(v)
        elif isinstance(data.get("cookies"), list):
            for c in data["cookies"]:
                if isinstance(c, dict) and c.get("name") in COOKIE_KEYS and isinstance(c.get("value"), str):
                    cookie_dict[c["name"]] = _decode(c["value"])

    # raw Name=Value; Name2=Value2  (fallback regex)
    for k in COOKIE_KEYS:
        if k in cookie_dict:
            continue
        m = re.search(rf"(?<!\w){re.escape(k)}=([^;,\s]+)", text)
        if m:
            cookie_dict[k] = _decode(m.group(1))

    return cookie_dict


def build_nftoken_link(token: str) -> str:
    return "https://netflix.com/?nftoken=" + token


# ------------------------------------------------------------------ fetch
def fetch_nftoken(cookie_dict: dict, timeout: int = 30, proxy: str | None = None,
                  retries: int = 2) -> dict:
    """Kembalikan dict hasil: ok, token, link, expires, error, status."""
    nid = cookie_dict.get(REQUIRED_COOKIE)
    if not nid:
        return {"ok": False, "error": "Missing required cookie: NetflixId", "status": 0}

    headers = dict(BASE_HEADERS)
    headers["Cookie"] = f"NetflixId={nid}"
    proxies = {"http": proxy, "https": proxy} if proxy else None

    last = ""
    for attempt in range(retries + 1):
        try:
            r = requests.get(API_URL, params=QUERY_PARAMS, headers=headers,
                             timeout=timeout, verify=False, proxies=proxies)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.2 * (attempt + 1))
            continue

        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            # 401/403 = cookie mati (nggak perlu retry banyak)
            if r.status_code in (401, 403):
                return {"ok": False, "error": f"HTTP {r.status_code} (cookie mati/expired)",
                        "status": r.status_code}
            time.sleep(1.0 * (attempt + 1))
            continue

        try:
            data = r.json()
        except Exception:
            return {"ok": False, "error": "Response bukan JSON", "status": r.status_code,
                    "raw": r.text[:200]}

        tok = (((((data.get("value") or {}).get("account") or {}).get("token") or {})
                .get("default")) or {})
        token = tok.get("token")
        expires = tok.get("expires")
        if not token:
            return {"ok": False, "error": "No token in response (cookie invalid/expired)",
                    "status": r.status_code, "raw": json.dumps(data)[:200]}
        if isinstance(expires, int) and len(str(expires)) == 13:
            expires //= 1000
        return {"ok": True, "token": token, "link": build_nftoken_link(token),
                "expires": expires, "expires_str": fmt_expiry(expires),
                "status": r.status_code, "error": ""}

    return {"ok": False, "error": last or "unknown error", "status": 0}


def fmt_expiry(expires) -> str:
    if not isinstance(expires, (int, float)):
        return "Unknown"
    try:
        return datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(expires)


def generate(raw_cookie: str, label: str = "", proxy: str | None = None,
             timeout: int = 30) -> dict:
    """High-level: teks cookie -> hasil lengkap."""
    ck = extract_cookie_dict(raw_cookie)
    if not ck:
        return {"ok": False, "label": label, "error": "No valid cookie found", "status": 0,
                "cookie_keys": []}
    res = fetch_nftoken(ck, timeout=timeout, proxy=proxy)
    res["label"] = label or ck.get("NetflixId", "")[:16]
    res["cookie_keys"] = sorted(ck.keys())
    res["ts"] = int(time.time())
    return res


def generate_bulk(items: list[dict], workers: int = 8, proxy: str | None = None,
                  timeout: int = 30) -> list[dict]:
    """items: [{'label':..., 'raw':...}] -> list hasil (urutan sama dgn input)."""
    out: list[dict | None] = [None] * len(items)

    def work(i, it):
        return i, generate(it.get("raw", ""), it.get("label", ""), proxy=proxy, timeout=timeout)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(work, i, it) for i, it in enumerate(items)]
        for f in as_completed(futs):
            try:
                i, res = f.result()
                out[i] = res
            except Exception as e:
                pass
    return [r or {"ok": False, "error": "worker crashed"} for r in out]


# ------------------------------------------------------------------ cli
if __name__ == "__main__":
    import sys
    txt = sys.stdin.read() if not sys.argv[1:] else open(sys.argv[1], encoding="utf-8").read()
    r = generate(txt, label="cli")
    print(json.dumps(r, indent=2, ensure_ascii=False))
