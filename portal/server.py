"""Call Intelligence Portal — local Flask web app.

Run:  python3 portal/server.py   then open http://127.0.0.1:5000
"""
import os
import sys
import json
import threading
import datetime

from flask import (Flask, render_template, jsonify, send_file,
                   request, abort)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "pipeline"))
import common as C  # noqa: E402

app = Flask(__name__)

# ---- Background sync state -------------------------------------------------
_sync_lock = threading.Lock()
_sync_state = {"status": "idle", "log": [], "started_at": None, "finished_at": None}


def _sync_log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    _sync_state["log"].append(line)


def _run_sync():
    import fetch_sheet
    import transcribe
    import analyze
    import discover
    with _sync_lock:
        _sync_state.update({"status": "running", "log": [],
                             "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                             "finished_at": None})
    try:
        _sync_log("Fetching Google Sheet recordings…")
        result = fetch_sheet.run()
        new_dl = (result or {}).get("downloaded", 0)
        _sync_log(f"Sheet fetch done — {new_dl} new files downloaded.")

        _sync_log("Transcribing new recordings (Whisper)…")
        new_tx = transcribe.run()
        _sync_log(f"Transcription done — {new_tx} new transcripts.")

        _sync_log("Analysing all transcripts…")
        summary = analyze.run()
        total = (summary or {}).get("total_calls", "?")
        xfer  = (summary or {}).get("transfer_rate", "?")
        _sync_log(f"Analysis done — {total} calls, {xfer}% transfer rate.")

        _sync_log("Detecting scripts and flows…")
        discover.run()
        _sync_log("All done! Refresh the Dashboard to see updated data.")
        _sync_state["status"] = "done"
    except Exception as e:  # noqa: BLE001
        _sync_log(f"ERROR: {e}")
        _sync_state["status"] = "error"
    finally:
        _sync_state["finished_at"] = datetime.datetime.now().isoformat(timespec="seconds")


def _summary():
    return C.load_json(os.path.join(C.ANALYSIS_DIR, "summary.json"), {}) or {}


def _flows():
    return C.load_json(os.path.join(C.ANALYSIS_DIR, "flows.json"), {}) or {}


@app.route("/")
def index():
    return render_template("index.html")


# ---- API -------------------------------------------------------------------
@app.route("/api/summary")
def api_summary():
    s = _summary()
    s["last_run"] = C.load_json(os.path.join(C.ANALYSIS_DIR, "last_run.json"), {})
    return jsonify(s)


@app.route("/api/flows")
def api_flows():
    return jsonify(_flows())


@app.route("/api/calls")
def api_calls():
    """List transcripts with ?company=&bot_company=&campaign=&dispo=&phone= filters."""
    company     = request.args.get("company", "").strip()
    bot_company = request.args.get("bot_company", "").strip()
    campaign    = request.args.get("campaign", "").strip()
    dispo       = request.args.get("dispo", "").strip()
    phone       = request.args.get("phone", "").strip()
    out = []
    for fn in sorted(os.listdir(C.TRANSCRIPTS_DIR)):
        if not fn.endswith(".json"):
            continue
        t = C.load_json(os.path.join(C.TRANSCRIPTS_DIR, fn))
        if not t:
            continue
        if company     and t.get("company", "")       != company:
            continue
        if bot_company and t.get("bot_company", "")   != bot_company:
            continue
        if campaign    and t.get("campaign_name", "")  != campaign:
            continue
        if dispo       and t.get("dispo", "")           != dispo:
            continue
        if phone       and phone not in t.get("phone", ""):
            continue
        out.append({
            "id":            t["id"],
            "company":       t.get("company", t["campaign"]),
            "bot_company":   t.get("bot_company", "—"),
            "campaign_name": t.get("campaign_name", "Medicare"),
            "campaign":      t["campaign"],
            "dispo":         t["dispo"],
            "dispo_label":   t.get("dispo_label", ""),
            "date":          t["date"],
            "time":          t["time"],
            "phone":         t["phone"],
            "duration":      t["duration"],
            "preview":       (t.get("text", "")[:160]),
        })
    out.sort(key=lambda x: (x["date"], x["time"]))
    return jsonify({"count": len(out), "calls": out})


@app.route("/api/call/<cid>")
def api_call(cid):
    t = C.load_json(os.path.join(C.TRANSCRIPTS_DIR, cid + ".json"))
    if not t:
        abort(404)
    return jsonify(t)


@app.route("/api/audio/<cid>")
def api_audio(cid):
    t = C.load_json(os.path.join(C.TRANSCRIPTS_DIR, cid + ".json"))
    if not t:
        abort(404)
    path = os.path.join(C.ROOT, t["rel_path"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/mpeg")


@app.route("/api/scripts")
def api_scripts():
    out = {}
    idx = C.load_json(os.path.join(C.SCRIPTS_DIR, "index.json"), {})
    for dispo in (idx.get("dispositions") or []):
        s = C.load_json(os.path.join(C.SCRIPTS_DIR, f"{dispo}.json"))
        if s:
            out[dispo] = s
    return jsonify({"index": idx, "scripts": out})


@app.route("/api/scripts_detected")
def api_scripts_detected():
    return jsonify(C.load_json(os.path.join(C.ANALYSIS_DIR, "scripts_detected.json"), {}))


@app.route("/api/flows_detected")
def api_flows_detected():
    return jsonify(C.load_json(os.path.join(C.ANALYSIS_DIR, "flows_detected.json"), {}))


@app.route("/api/research")
def api_research():
    path = os.path.join(C.DATA_DIR, "research", "medicare_2026.json")
    return jsonify(C.load_json(path, {}))


@app.route("/api/generate", methods=["POST"])
def api_generate():
    import generator
    body = request.get_json(force=True, silent=True) or {}
    style = body.get("style", "warm")
    focus = body.get("focus") or "2026 Part D $2,100 out-of-pocket cap savings"
    rec = generator.generate(style_key=style, focus=focus)
    return jsonify(rec)


@app.route("/api/generated")
def api_generated():
    import generator
    return jsonify({"styles": generator.STYLES, "items": generator.list_generated()})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    if _sync_state["status"] == "running":
        return jsonify({"ok": False, "message": "Sync already running."})
    t = threading.Thread(target=_run_sync, daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "Sync started."})


@app.route("/api/sync_status")
def api_sync_status():
    return jsonify(_sync_state)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"Call Intelligence Portal -> http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
