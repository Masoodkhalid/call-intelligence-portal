"""Shared helpers for the Call Intelligence pipeline."""
import os
import re
import json

# ---- Paths -----------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.path.dirname(HERE)
ROOT = os.path.dirname(PORTAL)

RECORDINGS_DIR = os.path.join(ROOT, "mcc")
DATA_DIR = os.path.join(PORTAL, "data")
TRANSCRIPTS_DIR = os.path.join(DATA_DIR, "transcripts")
ANALYSIS_DIR = os.path.join(DATA_DIR, "analysis")
SCRIPTS_DIR = os.path.join(DATA_DIR, "scripts")
MODELS_DIR = os.path.join(PORTAL, "models")
WHISPER_MODEL = os.path.join(MODELS_DIR, "ggml-base.en.bin")

for d in (TRANSCRIPTS_DIR, ANALYSIS_DIR, SCRIPTS_DIR):
    os.makedirs(d, exist_ok=True)

# ---- Disposition glossary --------------------------------------------------
# Normalised code -> (label, is_good_outcome)
DISPOSITIONS = {
    "A":       ("Answering Machine", False),
    "N":       ("No Answer", False),
    "NP":      ("No Pitch (cut early)", False),
    "LH":      ("Live Hangup", False),
    "NI":      ("Not Interested", False),
    "DNQ":     ("Did Not Qualify", False),
    "DC":      ("Disconnected", False),
    "BDNC":    ("Bad / Do-Not-Call", False),
    "DAIR":    ("Dead Air", False),
    "BN":      ("Business Number", False),
    "LB":      ("Left Blank / No Response", False),
    "RI":      ("Re-Inquiry", False),
    "RAXFER":  ("Transferred to Agent", True),
}

# Folder-name fragments -> normalised code
_DISPO_ALIASES = {
    "DEADAIR": "DAIR",
    "DAIR":    "DAIR",
    "RAXFER":  "RAXFER",
    "BNDC":    "BDNC",
    "BDNC":    "BDNC",
    "RAXFER":  "RAXFER",
}


def normalize_dispo(folder_name):
    """Extract the disposition code from any folder naming convention.

    Handles both old-style (mcc3-A, mcc3DNQ, mcc3-deadair) and new-style
    (AICONTACT_MEDICARE-LB, EMPAXCO3_SOLAR-RAXFER) by taking the segment
    after the LAST hyphen, then mapping through aliases.
    """
    name = folder_name.strip()
    if "-" in name:
        # take everything after the last hyphen
        code = name.rsplit("-", 1)[-1].upper()
    else:
        # old style with no hyphen: mcc3DNQ -> DNQ
        code = re.sub(r"^mcc\d+", "", name).upper()
    return _DISPO_ALIASES.get(code, code)


def dispo_label(code):
    return DISPOSITIONS.get(code, (code, False))[0]


def dispo_is_win(code):
    return DISPOSITIONS.get(code, (code, False))[1]


# ---- Filename metadata -----------------------------------------------------
_FNAME_RE = re.compile(r"(\d{8})-(\d{6})_(\d+)")


def parse_filename(path):
    """20260623-103358_4346373582-all.mp3 -> date/time/phone."""
    base = os.path.basename(path)
    m = _FNAME_RE.search(base)
    date = time = phone = ""
    if m:
        d, t, phone = m.group(1), m.group(2), m.group(3)
        date = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        time = f"{t[0:2]}:{t[2:4]}:{t[4:6]}"
    return {"date": date, "time": time, "phone": phone, "filename": base}


def call_id(campaign, dispo, filename):
    """Stable id used for the transcript json filename."""
    stem = os.path.splitext(filename)[0]
    return f"{campaign}__{dispo}__{stem}"


# ---- Company / Campaign / Bot inference ------------------------------------
# Definitive per-folder metadata — sourced from the Google Sheet (ground truth).
# Key = exact folder name under mcc/; values override any heuristic parsing.
_FOLDER_META = {
    # ---- existing clients ------------------------------------------------
    "HALINK_HIHALINK_FE": {
        "company":      "Halink(Hihalink)",
        "bot_company":  "Confinality",
        "campaign_name":"FE",
    },
    "AICONTACT_MEDICARE": {
        "company":      "aicontact",
        "bot_company":  "Confinality",
        "campaign_name":"Medicare",
    },
    "EMPAXCO3_SOLAR": {       # legacy folder name — same client as EMPAXCO3_FE
        "company":      "empaxco3",
        "bot_company":  "REEV",
        "campaign_name":"FE",
    },
    "EMPAXCO3_FE": {
        "company":      "empaxco3",
        "bot_company":  "REEV",
        "campaign_name":"FE",
    },
    # ---- new clients added to sheet -------------------------------------
    "BALITECH_BT1_MEDICARE": {
        "company":      "balitech-bt1",
        "bot_company":  "Confinality",
        "campaign_name":"Medicare",
    },
    "ERRANDS4_MEDICAL_SUPPLIES": {
        "company":      "errands4",
        "bot_company":  "ISPER",
        "campaign_name":"Medical Supplies",
    },
}

# Fallback: mcc* folders are all Medicare / Confinality
_KNOWN_CAMPAIGNS = {"FE", "MEDICARE", "SOLAR"}


def folder_meta(folder_name):
    """Return (company, bot_company, campaign_name) for a recordings folder."""
    if folder_name in _FOLDER_META:
        m = _FOLDER_META[folder_name]
        return m["company"], m["bot_company"], m["campaign_name"]
    if re.match(r"^mcc\d+$", folder_name, re.I):
        return folder_name, "Confinality", "Medicare"
    # generic fallback
    up = folder_name.upper()
    for camp in sorted(_KNOWN_CAMPAIGNS, key=len, reverse=True):
        if up.endswith("_" + camp):
            company = folder_name[:-(len(camp) + 1)].split("_")[0].capitalize()
            return company, "Unknown", camp.title()
    return folder_name, "Unknown", "Unknown"


def parse_company_campaign(folder_name):
    company, _, campaign_name = folder_meta(folder_name)
    return company, campaign_name


def parse_bot_company(company_name):
    """Look up bot company by client company name (for back-fill on old transcripts)."""
    low = company_name.lower().strip()
    for meta in _FOLDER_META.values():
        if meta["company"].lower() == low:
            return meta["bot_company"]
    # mcc* → Confinality
    if re.match(r"^mcc\d+$", low):
        return "Confinality"
    return "Unknown"


def iter_recordings():
    """Yield (mp3_path, campaign_folder, dispo_code, meta) for every recording."""
    if not os.path.isdir(RECORDINGS_DIR):
        return
    for folder in sorted(os.listdir(RECORDINGS_DIR)):
        cdir = os.path.join(RECORDINGS_DIR, folder)
        if not os.path.isdir(cdir):
            continue
        company, bot_company, campaign_name = folder_meta(folder)
        for dfolder in sorted(os.listdir(cdir)):
            ddir = os.path.join(cdir, dfolder)
            if not os.path.isdir(ddir):
                continue
            dispo = normalize_dispo(dfolder)
            for fn in sorted(os.listdir(ddir)):
                if not fn.lower().endswith(".mp3"):
                    continue
                path = os.path.join(ddir, fn)
                meta = parse_filename(path)
                meta["campaign"]      = folder          # raw folder key
                meta["company"]       = company         # client company (from sheet)
                meta["bot_company"]   = bot_company     # bot platform (from sheet)
                meta["campaign_name"] = campaign_name   # campaign (from sheet)
                meta["dispo"]         = dispo
                meta["dispo_label"]   = dispo_label(dispo)
                meta["path"]          = path
                meta["rel_path"]      = os.path.relpath(path, ROOT)
                yield path, folder, dispo, meta


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def all_transcripts():
    """Load every transcript json."""
    out = []
    for fn in sorted(os.listdir(TRANSCRIPTS_DIR)):
        if fn.endswith(".json"):
            t = load_json(os.path.join(TRANSCRIPTS_DIR, fn))
            if t:
                out.append(t)
    return out


# ---- Text normalisation / templatisation -----------------------------------
import difflib  # noqa: E402

_WS = re.compile(r"\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

US_STATES = (r"(alabama|alaska|arizona|arkansas|california|colorado|connecticut|"
             r"delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|"
             r"kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
             r"mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
             r"new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|"
             r"pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|"
             r"utah|vermont|virginia|washington|west virginia|wisconsin|wyoming)")

# Agent names that appear after "this is" / "my name is" (filled live).
AGENT_NAMES = ["cassie", "evelyn", "alyssa", "jacob", "rachel", "elena",
               "sophia", "emily", "ashley", "olivia", "rebecca", "jessica",
               "sarah", "laura", "amanda", "natalie", "hannah", "grace"]


def norm(s):
    return _WS.sub(" ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def templatize(s):
    """Replace the variable bits (name, state, year, money, numbers) with tokens
    so the same script said with different fillers collapses to one template."""
    s = norm(s)
    s = re.sub(r"\b(my name is|this is|i'?m|i am)\s+(" + "|".join(AGENT_NAMES) + r")\b",
               r"\1 <NAME>", s)
    s = re.sub(US_STATES, "<STATE>", s)
    s = re.sub(r"\b(19|20)\d\d\b", "<YEAR>", s)
    s = re.sub(r"\b\d+\b", "<NUM>", s)
    s = _WS.sub(" ", s).strip()
    return s


def split_sentences(text):
    out = []
    for chunk in _SENT_SPLIT.split(text or ""):
        chunk = chunk.replace(">>", " ").strip(" .-")
        chunk = _WS.sub(" ", chunk).strip()
        if chunk:
            out.append(chunk)
    return out


def fuzzy(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


# The bot's job ends when it hands off to a live specialist. Everything spoken
# after that is the human agent <-> customer and must NOT be treated as bot
# script. We cut the transcript shortly after the first transfer cue.
_TRANSFER_CUE = re.compile(
    r"(stay on the line|transfer you|i'?ll transfer|connect you|please hold|"
    r"hold on the line|take over (shortly|now)|bear with me|one moment please)",
    re.I)


def bot_portion(text):
    """Return only the bot-led portion of the call (up to ~1 sentence past the
    transfer hand-off). For non-transferred calls this returns the text mostly
    unchanged."""
    sents = split_sentences(text)
    cut = None
    for i, s in enumerate(sents):
        if _TRANSFER_CUE.search(s):
            cut = i + 1            # keep the hand-off line itself
            break
    if cut is None:
        return text
    return " ".join(sents[:cut + 1])
