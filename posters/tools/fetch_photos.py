#!/usr/bin/env python3
"""Find licence-safe landmark and boat photos for SailGP city posters.

Sources (in order): Wikimedia Commons API, Openverse API, then Unsplash/Pexels
when UNSPLASH_ACCESS_KEY / PEXELS_API_KEY are set. Only CC0, PDM, CC BY,
CC BY-SA, Unsplash and Pexels licences are accepted.

Usage (needs Python 3.9+, Pillow and numpy):
  python3 tools/fetch_photos.py search    # metadata only -> work/candidates.json
  python3 tools/fetch_photos.py boats     # downloads boat candidates -> work/boat_candidates/
  python3 tools/fetch_photos.py download  # scores landmarks, saves top 8 per city -> input/landmarks/candidates/
"""
import json, os, re, sys, time, io, urllib.parse, urllib.request, urllib.error, html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = "SailPosterPhotoFetch/1.0 (poster artwork; licence-checked reuse) python-urllib"

CITIES = {
 "hong-kong":     ["Victoria Harbour Hong Kong skyline", "Hong Kong skyline sunset harbour", "Hong Kong Island skyline from Tsim Sha Tsui"],
 "perth":         ["Perth skyline Swan River", "Perth city skyline from South Perth", "Perth skyline sunset"],
 "san-francisco": ["Golden Gate Bridge from the bay", "Golden Gate Bridge sunset", "San Francisco skyline from the bay"],
 "bermuda":       ["Hamilton Bermuda harbour", "Hamilton Bermuda waterfront", "Great Sound Bermuda"],
 "halifax":       ["Halifax waterfront harbour skyline", "Halifax Nova Scotia skyline Dartmouth", "Halifax harbour sunset"],
 "new-york":      ["Statue of Liberty harbor", "Lower Manhattan skyline from the harbor", "Manhattan skyline sunset Hudson"],
 "portsmouth":    ["Spinnaker Tower Portsmouth harbour", "Spinnaker Tower sunset", "Portsmouth harbour Gosport"],
 "sassnitz":      ["Sassnitz harbour", "Sassnitz Hafen", "Sassnitz Mole Leuchtturm"],
 "rome":          ["Tiber Castel Sant'Angelo", "St Peter's Basilica from the Tiber", "Ponte Sant'Angelo sunset"],
 "rio":           ["Sugarloaf Mountain Guanabara Bay", "Pão de Açúcar Baía de Guanabara", "Rio de Janeiro Botafogo bay sunset"],
 "dubai":         ["Dubai Marina skyline from sea", "Burj Al Arab sea sunset", "Dubai skyline from the water"],
}
BOAT_QUERIES = ["SailGP F50", "SailGP catamaran", "F50 foiling catamaran SailGP"]

OK_CC = {"cc0", "pdm", "by", "by-sa"}
BAD_RX = re.compile(r"\b(nc|nd|non-?commercial|no-?deriv|all rights reserved|fair use)\b", re.I)

def get_json(url, headers=None, tries=8):
    h = {"User-Agent": UA}; h.update(headers or {})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("retry-after") or 0) or min(120, 10 * 2 ** i)
                print(f"  {e.code}, waiting {wait}s", file=sys.stderr); time.sleep(wait + 1); continue
            raise
    raise RuntimeError(f"gave up: {url}")

def get_bytes(url, tries=6):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("retry-after") or 0) or min(120, 10 * 2 ** i)
                print(f"  {e.code} on image, waiting {wait}s", file=sys.stderr); time.sleep(wait + 1); continue
            raise
    raise RuntimeError(f"gave up: {url}")

def strip_html(s): return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()

def norm_cc(short):
    s = (short or "").lower().replace("cc-", "").replace("cc ", "").strip()
    if s in ("cc0", "cc0 1.0", "public domain", "pd", "pdm") or s.startswith("public domain"): return "cc0" if "cc0" in s else "pdm"
    m = re.match(r"(?:cc\s*)?(by(?:-sa)?)(?:\s*([\d.]+))?", s)
    return m.group(1) if m and not BAD_RX.search(s) else None

# ---------- Wikimedia Commons ----------
def commons(query, limit=40):
    p = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
         "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": limit, "prop": "imageinfo",
         "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2400}
    d = get_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(p))
    out = []
    for pg in (d.get("query", {}).get("pages", {}) or {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]; md = ii.get("extmetadata", {})
        lic_short = md.get("LicenseShortName", {}).get("value", "")
        lic = norm_cc(lic_short)
        if not lic or BAD_RX.search(lic_short) or ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        out.append(dict(source="wikimedia", id=pg["title"], title=pg["title"].removeprefix("File:"),
            width=ii.get("width", 0), height=ii.get("height", 0),
            download=ii.get("thumburl") if ii.get("width", 0) > 2400 else ii.get("url"),
            thumb=ii.get("url") if ii.get("width",0) <= 960 else re.sub(r"/\d+px-", "/960px-", ii.get("thumburl", "")),
            page=ii.get("descriptionurl"), author=strip_html(md.get("Artist", {}).get("value", "")) or "Unknown",
            licence=lic_short, licence_url=md.get("LicenseUrl", {}).get("value", "") or ("https://creativecommons.org/publicdomain/zero/1.0/" if lic=="cc0" else ""),
            desc=strip_html(md.get("ImageDescription", {}).get("value", ""))[:300]))
    return out

# ---------- Openverse ----------
def openverse(query, n=20):
    p = {"q": query, "page_size": n, "license": "cc0,pdm,by,by-sa", "mature": "false"}
    d = get_json("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(p))
    time.sleep(3.5)  # anon burst is 20/min
    out = []
    for r in d.get("results", []):
        if r.get("source") == "wikimedia": continue  # already covered by the Commons API
        if r["license"] not in OK_CC: continue
        lic = ("CC0 1.0" if r["license"] == "cc0" else "Public Domain Mark 1.0" if r["license"] == "pdm"
               else f"CC {r['license'].upper()} {r.get('license_version') or ''}".strip())
        out.append(dict(source=f"openverse/{r['source']}", id=r["id"], title=r.get("title") or "",
            width=r.get("width") or 0, height=r.get("height") or 0, download=r["url"], thumb=r["url"],
            page=r["foreign_landing_url"], author=r.get("creator") or "Unknown", licence=lic,
            licence_url=r.get("license_url") or "", desc=""))
    return out

# ---------- Unsplash / Pexels (only with keys) ----------
def unsplash(query):
    k = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not k: return []
    d = get_json("https://api.unsplash.com/search/photos?" + urllib.parse.urlencode({"query": query, "per_page": 20}),
                 {"Authorization": f"Client-ID {k}"})
    return [dict(source="unsplash", id=r["id"], title=r.get("alt_description") or "", width=r["width"], height=r["height"],
        download=r["urls"]["raw"] + "&w=2400&q=90&fm=jpg", thumb=r["urls"]["small"], page=r["links"]["html"],
        author=r["user"]["name"], licence="Unsplash License", licence_url="https://unsplash.com/license", desc="",
        dl_track=r["links"]["download_location"]) for r in d.get("results", [])]

def pexels(query):
    k = os.environ.get("PEXELS_API_KEY")
    if not k: return []
    d = get_json("https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": query, "per_page": 20}), {"Authorization": k})
    return [dict(source="pexels", id=str(r["id"]), title=r.get("alt") or "", width=r["width"], height=r["height"],
        download=r["src"]["original"] + "?auto=compress&w=2400", thumb=r["src"]["medium"], page=r["url"],
        author=r["photographer"], licence="Pexels License", licence_url="https://www.pexels.com/license/", desc="")
        for r in d.get("photos", [])]

SOURCES = [commons, openverse, unsplash, pexels]

def search_all(queries, keep):
    seen, out = set(), []
    for q in queries:
        for fn in SOURCES:
            cf = WORK / "cache" / f"{fn.__name__}-{safe(q)}.json"
            if cf.exists(): res = json.loads(cf.read_text())
            else:
                try:
                    res = fn(q)
                    if fn in (commons, openverse) or res: cf.parent.mkdir(parents=True, exist_ok=True); cf.write_text(json.dumps(res))
                except Exception as e: print(f"  {fn.__name__} failed for {q!r}: {e}", file=sys.stderr); res = []
            for r in res:
                key = (r["source"].split("/")[-1], r["page"])
                if key in seen or not keep(r): continue
                seen.add(key); r["query"] = q; out.append(r)
    return out

TEXTY = re.compile(r"\b(logo|map|poster|diagram|plan|sign|ticket|night view panorama 360|aerial|drone|interior|museum)\b", re.I)

def cmd_search():
    WORK.mkdir(exist_ok=True)
    cand = {}
    for city, qs in CITIES.items():
        print(f"[{city}]", file=sys.stderr)
        cand[city] = search_all(qs, lambda r: r["width"] >= 2000 and r["width"] > r["height"] * 1.2 and not TEXTY.search(r["title"]))
        print(f"  {len(cand[city])} landscape >=2000px", file=sys.stderr)
    print("[boats]", file=sys.stderr)
    cand["_boats"] = search_all(BOAT_QUERIES, lambda r: r["height"] >= 1000 or r["source"].startswith("openverse"))
    print(f"  {len(cand['_boats'])} boat candidates", file=sys.stderr)
    (WORK / "candidates.json").write_text(json.dumps(cand, indent=1, ensure_ascii=False))


# ---------- download + scoring ----------
def to_rgb_small(data, w=480):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    im.thumbnail((w, w * 2)); return im

def score_image(im):
    """Heuristic 0-100: landscape, smooth water in lower third, detailed skyline band, warm light."""
    import numpy as np
    a = np.asarray(im, dtype=np.float32) / 255.0; h, w, _ = a.shape
    g = a.mean(2); gy = np.abs(np.diff(g, axis=0))[:, :-1]; gx = np.abs(np.diff(g, axis=1))[:-1, :]
    t = h // 3
    low, mid = slice(2 * t, h - 1), slice(int(h * .3), int(h * .66))
    tex_low, tex_mid = (gx + gy)[low].mean(), (gx + gy)[mid].mean()
    r, gch, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(2), a.min(2); sat = (mx - mn) / (mx + 1e-6)
    # water: smooth, horizontal ripples (gy>gx), bluish/grey or reflecting warm sky, little vertical structure
    water = 0
    water += 25 * max(0, 1 - tex_low / max(tex_mid, 1e-3))          # smoother than skyline band
    water += 10 * min(1, (gy[low].mean() / (gx[low].mean() + 1e-6) - 0.8) / 0.6) if gy[low].mean() > gx[low].mean() * .8 else 0
    water += 10 * float(((b[low] >= r[low] - .05) | (sat[low] < .25)).mean())
    # landmark: detail in the middle band
    land = 20 * min(1, tex_mid / 0.08)
    # golden hour / dusk: warm, saturated sky in the top third
    top = slice(0, t)
    warm = float(np.clip((r[top] - b[top]).mean() / .25, 0, 1)) * 15 + float(np.clip(sat[top].mean() / .45, 0, 1)) * 5
    ratio = w / h; orient = 15 if 1.3 <= ratio <= 2.1 else 8 if ratio > 1.15 else 0
    # penalise blown-out or very dark frames
    lum = g.mean(); expo = -10 if lum < .12 or lum > .85 else 0
    parts = dict(water=round(water, 1), landmark=round(land, 1), warm=round(warm, 1), orient=orient, expo=expo)
    return round(sum(parts.values()), 1), parts

META_BONUS = re.compile(r"sunset|dusk|golden|evening|twilight|sunrise|harbou?r|bay|river|skyline|waterfront|from the|across", re.I)
META_BAD = re.compile(r"watermark|night|construction|crowd|parade|festival|fireworks|interior|bw|black and white|monochrome|1[89]\d\d", re.I)

def wm_url(r, kind):
    """Map a Commons record to a standard-size URL (960px for scoring, 3840px or original for download)."""
    u = r[kind]
    if r["source"] != "wikimedia" or "/thumb/" not in u: return u
    if kind == "thumb": return re.sub(r"/\d+px-", "/960px-", u)
    return re.sub(r"/\d+px-", "/3840px-", u) if r["width"] > 3840 else re.sub(r"/thumb(/.+)/[^/]+$", r"\1", u)

def safe(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]

def cmd_download():
    from PIL import Image
    cand = json.loads((WORK / "candidates.json").read_text())
    report = {}
    for city, items in cand.items():
        if city == "_boats": continue
        for r in items:
            txt = f"{r['title']} {r.get('desc','')}"
            r["meta"] = 6 * len(set(m.lower() for m in META_BONUS.findall(txt))) - 25 * bool(META_BAD.search(txt))
        pool = sorted(items, key=lambda r: -r["meta"])[:18]
        print(f"[{city}] scoring {len(pool)} of {len(items)}", file=sys.stderr)
        scored = []
        for r in pool:
            try: im = to_rgb_small(get_bytes(wm_url(r, "thumb") if r["source"] == "wikimedia" else r["download"]))
            except Exception as e: print("  thumb fail", e, file=sys.stderr); continue
            s, parts = score_image(im); r["score"] = round(s + r["meta"] * .5, 1); r["parts"] = parts
            scored.append(r); time.sleep(.5)
        top = sorted(scored, key=lambda r: -r["score"])[:8]
        cdir = ROOT / "input/landmarks/candidates" / city; cdir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(top, 1):
            fn = cdir / f"{i:02d}-{safe(r['title'].rsplit('.',1)[0])}.jpg"
            if not fn.exists():
                data = get_bytes(wm_url(r, "download"))
                im = Image.open(io.BytesIO(data)).convert("RGB")
                if im.width > 2400: im = im.resize((2400, round(im.height * 2400 / im.width)), Image.LANCZOS)
                im.save(fn, quality=92); time.sleep(1)
            r["file"] = str(fn.relative_to(ROOT))
            print(f"  {r['score']:5.1f} {r['parts']} {r['title'][:70]}", file=sys.stderr)
        report[city] = top
    (WORK / "landmark_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))

def cmd_boats():
    from PIL import Image
    cand = json.loads((WORK / "candidates.json").read_text())["_boats"]
    d = WORK / "boat_candidates"; d.mkdir(exist_ok=True); out = []
    for i, r in enumerate(cand):
        fn = d / f"{i:02d}-{safe(r['title'].rsplit('.',1)[0])}.jpg"
        if not fn.exists():
            try: data = get_bytes(wm_url(r, "download"))
            except Exception as e: print("fail", e, file=sys.stderr); continue
            im = Image.open(io.BytesIO(data)).convert("RGB"); im.save(fn, quality=92); time.sleep(.5)
        im = Image.open(fn); r["file"] = str(fn.relative_to(ROOT)); r["actual"] = im.size; out.append(r)
        print(f"{fn.name} {im.size} {r['licence']} {r['source']}", file=sys.stderr)
    (WORK / "boat_report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))

if __name__ == "__main__":
    {"search": cmd_search, "download": cmd_download, "boats": cmd_boats}[sys.argv[1]]()
