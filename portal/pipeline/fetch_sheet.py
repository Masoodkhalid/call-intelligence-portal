"""INGEST AGENT — Google Sheet Fetcher.

Reads the public Google Sheet CSV, downloads every recording MP3 into the
correct mcc/<client_campaign>/<client_campaign>-<disposition>/ folder,
then hands off to the daily pipeline.

Usage:
    python3 portal/pipeline/fetch_sheet.py
    python3 portal/pipeline/fetch_sheet.py --dry-run   # show what would download
    python3 portal/pipeline/fetch_sheet.py --workers=8 # parallel downloads
"""
import os
import re
import sys
import csv
import time
import urllib.request
import urllib.error
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1T8s0aqrWaU9ZDludC_kvbjbwR0A8E_mYHzdnl7hrMrU"
    "/gviz/tq?tqx=out:csv&sheet=Sheet1"
)

_WS = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+\.mp3", re.I)


def clean(s):
    return _WS.sub(" ", (s or "").strip()).strip()


def safe_folder(s):
    """Turn a client/campaign/dispo string into a safe folder name."""
    s = clean(s).upper()
    s = re.sub(r"[^A-Z0-9_]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def fetch_csv():
    req = urllib.request.Request(SHEET_CSV_URL,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_rows(csv_text):
    """Parse the sheet into a list of dicts with url/client/campaign/dispo/date.

    The sheet uses section-header rows (e.g. a row where col0 is "  BDNC" and
    col3 is empty) to group recordings. We track the running disposition and
    fill it forward.
    """
    rows = []
    reader = csv.reader(StringIO(csv_text))
    header_seen = False
    cur_client = cur_campaign = cur_dispo = cur_bot = ""
    for row in reader:
        if not any(clean(c) for c in row):
            continue                         # blank row
        if not header_seen:
            header_seen = True
            continue                         # skip header

        url   = clean(row[0]) if len(row) > 0 else ""
        client= clean(row[1]) if len(row) > 1 else ""
        bot   = clean(row[2]) if len(row) > 2 else ""
        dispo = clean(row[3]) if len(row) > 3 else ""
        camp  = clean(row[4]) if len(row) > 4 else ""
        date  = clean(row[5]) if len(row) > 5 else ""

        # carry client/campaign/bot forward
        if client:  cur_client   = client
        if bot:     cur_bot      = bot
        if camp:    cur_campaign = camp

        # section header row — update running disposition
        if not _URL_RE.match(url) and url and not url.startswith("http"):
            # col0 holds the disposition label (e.g. "  RAXFER")
            candidate = re.sub(r"[^A-Z0-9]", "", url.upper())
            if candidate:
                cur_dispo = candidate
            continue

        # skip rows without a real URL
        if not _URL_RE.match(url):
            continue

        # if dispo is in col3 use it, otherwise use running dispo
        effective_dispo = re.sub(r"[^A-Z0-9]", "", dispo.upper()) if dispo else cur_dispo

        rows.append({
            "url":      url,
            "client":   cur_client,
            "bot":      cur_bot,
            "campaign": cur_campaign,
            "dispo":    effective_dispo or "UNKNOWN",
            "date":     date,
            "filename": os.path.basename(url.split("?")[0]),
        })
    return rows


def dest_path(rec):
    """Build the local mp3 path under mcc/."""
    client_tag  = safe_folder(rec["client"])   # e.g. HALINK_HIHALINK_
    camp_tag    = safe_folder(rec["campaign"])  # e.g. FE
    folder_name = f"{client_tag}_{camp_tag}" if camp_tag else client_tag
    dispo       = rec["dispo"].upper()
    folder      = os.path.join(C.RECORDINGS_DIR,
                               folder_name,
                               f"{folder_name}-{dispo}")
    return os.path.join(folder, rec["filename"])


def download_one(rec, dry_run=False):
    path = dest_path(rec)
    if os.path.exists(path):
        return "skip", rec["filename"]
    if dry_run:
        return "dry", path
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    tmp = path + ".tmp"
    try:
        req = urllib.request.Request(rec["url"],
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            f.write(r.read())
        os.replace(tmp, path)
        return "ok", rec["filename"]
    except Exception as e:  # noqa: BLE001
        if os.path.exists(tmp):
            os.remove(tmp)
        return "err", f"{rec['filename']} — {e}"


def run(dry_run=False, workers=6):
    print("[fetch_sheet] reading Google Sheet…")
    try:
        csv_text = fetch_csv()
    except Exception as e:
        print(f"[fetch_sheet] ERROR fetching sheet: {e}")
        sys.exit(1)

    rows = parse_rows(csv_text)
    print(f"[fetch_sheet] {len(rows)} recording URLs found")

    # show breakdown
    from collections import Counter
    camps = Counter(f"{r['client']} / {r['campaign']}" for r in rows)
    for k, n in camps.most_common():
        print(f"  {n:4d}  {k}")

    if dry_run:
        print("\n[fetch_sheet] DRY RUN — would download:")
        for r in rows[:20]:
            print(f"  {dest_path(r)}")
        if len(rows) > 20:
            print(f"  … and {len(rows)-20} more")
        return

    t0 = time.time()
    ok = skip = err = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, r, dry_run): r for r in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            status, msg = fut.result()
            if status == "ok":    ok   += 1
            elif status == "skip":skip += 1
            else:                 err  += 1; print(f"  ! {msg}")
            if i % 50 == 0:
                print(f"  {i}/{len(rows)} — {ok} downloaded, {skip} skipped, {err} errors")

    elapsed = time.time() - t0
    print(f"\n[fetch_sheet] done in {elapsed:.0f}s — "
          f"{ok} new, {skip} already had, {err} errors")
    return {"downloaded": ok, "skipped": skip, "errors": err}


if __name__ == "__main__":
    args = sys.argv[1:]
    dry  = "--dry-run" in args
    w    = 6
    for a in args:
        if a.startswith("--workers="):
            w = int(a.split("=")[1])
    run(dry_run=dry, workers=w)
