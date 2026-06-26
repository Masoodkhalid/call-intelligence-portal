"""Stage 3b — SCRIPT & FLOW DISCOVERY.

Answers two questions over the whole corpus:
  * How many DISTINCT SCRIPTS is the bot running? (e.g. the "Medicare profile /
    national database" pitch vs the "$300 grocery & cash benefits" pitch).
    Agent name and state are treated as variables, so the same script with
    different fillers collapses into one.
  * How many DISTINCT FLOWS occur? (the path a call takes through the funnel,
    e.g. greeting->pitch->qualify->transfer vs greeting->pitch->hangup).

Writes scripts_detected.json and flows_detected.json for the portal.
"""
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

PITCH_RE = re.compile(r"\b(calling because|pending|grocery|cash benefit|"
                      r"medicare member profile|national database|relief program|"
                      r"new benefits|coverage)\b", re.I)
QUALIFY_RE = re.compile(r"\b(part a|part b|both part|qualify)\b", re.I)
NAME_RE = re.compile(r"\b(?:my name is|this is|i'?m)\s+([a-z]+)", re.I)


def bot_text(turns):
    return " ".join(t["text"] for t in turns if t["speaker"] == "BOT")


PITCH_START_RE = re.compile(
    r"(calling because.*|we pulled up.*|pulled up your.*|there are pending.*|"
    r"your medicare member profile.*)", re.I)


def _trim_to_pitch(s):
    """Drop the greeting/name prefix so we cluster on the pitch clause itself."""
    m = PITCH_START_RE.search(s)
    clause = m.group(1) if m else s
    return clause[:160]


def best_pitch_line(turns):
    """The bot's pitch clause (greeting/name prefix trimmed off)."""
    cands = []
    for t in turns:
        if t["speaker"] != "BOT":
            continue
        for s in C.split_sentences(t["text"]):
            if PITCH_RE.search(s):
                cands.append(_trim_to_pitch(s))
    if not cands:
        return ""
    return max(cands, key=len)


def _prettify(s):
    s = re.sub(r"\b(" + "|".join(C.AGENT_NAMES) + r")\b", "[Agent]", s, flags=re.I)
    s = re.sub(C.US_STATES, "[State]", s, flags=re.I)
    s = re.sub(r"\b(19|20)\d\d\b", "[Year]", s)
    s = re.sub(r"\$?\b\d+\b", "[amount]", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    return (s[0].upper() + s[1:]) if s else s


# --- script-line role classifier -------------------------------------------
_ROLE_PATTERNS = [
    # Order matters: first match wins. DISQUALIFY & QUALIFY beat PITCH.
    ("DISQUALIFY",re.compile(
        r"\b(don'?t seem to qualify|not qualify|do not qualify|don'?t qualify|"
        r"it looks like you don'?t|sorry you don'?t)\b", re.I)),
    # QUALIFY: any line mentioning Part A or Part B → always QUALIFY
    ("QUALIFY",   re.compile(
        r"\b(part a|part b|both part|do you have (both|medicare)|"
        r"part a and part b|medicare part a|medicare part b|have both medicare)\b", re.I)),
    ("IDENTIFY",  re.compile(
        r"\b(my name is|this is [a-z]+|i'?m calling from|licensed|insurance agency)\b", re.I)),
    ("PITCH",     re.compile(
        r"\b(calling because|pending grocery|cash benefit|medicare member profile|"
        r"national database|pulled up your medicare|relief program|"
        r"coverage approvals|hasn'?t been transferred|delay your coverage|"
        r"file updated|profile is showing|note showing|pending credits|"
        r"notified about|received.{0,20}notification)\b", re.I)),
    ("TRANSFER",  re.compile(
        r"\b(stay on the line|transfer you|i'?ll transfer|specialist|"
        r"connect you|please hold|hold on the line|take over|bear with me|one moment)\b", re.I)),
]

_NOISE_RE = re.compile(
    r"^(hello|hi|hey|good morning|good afternoon|good evening|"
    r"are you there|can you hear me|hey are you|have a great day|"
    r"thank you|no worries|just a moment|blank.?audio|"
    r"just confirm for me|of course|absolutely|okay|alright|"
    r"i understand|i see|i hear you)[\s.?!]*$", re.I)


def classify_role(line):
    """Return the script role of a line, or None if it is noise."""
    low = line.lower().strip()
    if _NOISE_RE.match(low) and len(low) < 40:
        return None
    for role, pat in _ROLE_PATTERNS:
        if pat.search(line):
            return role
    return None  # filler / noise — drop it


def reconstruct_script(members):
    """Rebuild the full canonical bot script for a cluster: the bot lines that
    recur across its calls, ordered by where they typically occur."""
    from collections import defaultdict
    n = len(members)
    df = Counter()
    positions = defaultdict(list)
    raw = defaultdict(Counter)
    for t in members:
        # use the original punctuated bot portion so sentence boundaries survive
        src = t.get("bot_text") or t.get("text", "")
        sents = C.split_sentences(src)
        seen = set()
        for i, s in enumerate(sents):
            tpl = C.templatize(s)
            if len(tpl) < 8:
                continue
            raw[tpl][s.strip()] += 1
            positions[tpl].append(i / max(1, len(sents) - 1))
            if tpl not in seen:
                df[tpl] += 1
                seen.add(tpl)
    thresh = max(2, int(0.07 * n))   # 7% of calls must say the line for it to survive
    cand = [(tpl, df[tpl], sum(positions[tpl]) / len(positions[tpl]))
            for tpl in df if df[tpl] >= thresh]
    cand.sort(key=lambda x: -x[1])
    kept = []
    for tpl, d, p in cand:
        if any(C.fuzzy(tpl, k[0]) >= 0.8 for k in kept):
            continue
        kept.append((tpl, d, p))
    kept.sort(key=lambda x: x[2])           # chronological order in the call
    script = []
    seen_roles = {}  # dedupe: only keep best (highest df) per near-duplicate role+content
    for tpl, d, p in kept:
        rep = raw[tpl].most_common(1)[0][0]
        pretty = _prettify(rep)
        role = classify_role(pretty)
        if role is None:
            continue
        # deduplicate near-identical lines within the same role
        duplicate = False
        for existing in script:
            if existing["role"] == role and C.fuzzy(C.norm(pretty), C.norm(existing["line"])) >= 0.72:
                if d > existing["df"]:
                    existing["line"] = pretty
                    existing["df"] = d
                    existing["pct"] = round(100 * d / n, 1)
                duplicate = True
                break
        if not duplicate:
            script.append({"line": pretty, "role": role,
                           "df": d, "pct": round(100 * d / n, 1)})
    # final sort by position
    return script


def cluster(items, sim=0.62):
    """Greedy fuzzy clustering of (template, weight) -> list of clusters."""
    clusters = []  # each: {rep, members:[(tpl,w)], weight}
    for tpl, w in sorted(items, key=lambda x: -x[1]):
        placed = False
        for cl in clusters:
            if C.fuzzy(tpl, cl["rep"]) >= sim:
                cl["members"].append((tpl, w))
                cl["weight"] += w
                placed = True
                break
        if not placed:
            clusters.append({"rep": tpl, "members": [(tpl, w)], "weight": w})
    clusters.sort(key=lambda c: -c["weight"])
    return clusters


def discover_scripts(transcripts):
    # one pitch template per call
    per_call = {}
    pitch_counter = Counter()
    for t in transcripts:
        line = best_pitch_line(t.get("turns", []))
        if not line:
            continue
        tpl = C.templatize(line)
        per_call[t["id"]] = tpl
        pitch_counter[tpl] += 1

    clusters = cluster(list(pitch_counter.items()), sim=0.55)

    # map each call to its cluster index
    rep_to_idx = {}
    for i, cl in enumerate(clusters):
        for tpl, _ in cl["members"]:
            rep_to_idx[tpl] = i

    scripts = []
    for i, cl in enumerate(clusters):
        names = Counter()
        states = Counter()
        qual = Counter()
        dispos = Counter()
        campaigns = Counter()
        examples = []
        members = []
        for t in transcripts:
            if per_call.get(t["id"]) is None or rep_to_idx.get(per_call[t["id"]]) != i:
                continue
            members.append(t)
            bt = bot_text(t.get("turns", []))
            for m in NAME_RE.finditer(bt):
                nm = m.group(1).lower()
                if nm in C.AGENT_NAMES:
                    names[nm.title()] += 1
            for st in re.finditer(C.US_STATES, bt.lower()):
                states[st.group(1).title()] += 1
            for q in C.split_sentences(bt):
                if QUALIFY_RE.search(q):
                    qual[C.templatize(q)[:70]] += 1
            dispos[t["dispo"]] += 1
            campaigns[t["campaign"]] += 1
            if len(examples) < 4:
                examples.append({"id": t["id"], "text": best_pitch_line(t["turns"])})
        readable = (cl["rep"].replace("<NAME>", "[name]")
                    .replace("<STATE>", "[state]")
                    .replace("<YEAR>", "[year]").replace("<NUM>", "[#]"))
        wins = sum(c for d, c in dispos.items() if C.dispo_is_win(d))
        total = sum(dispos.values())
        scripts.append({
            "id": i + 1,
            "template": readable,
            "full_script": reconstruct_script(members),
            "calls": cl["weight"],
            "variants": len(cl["members"]),
            "agent_names": names.most_common(),
            "states": states.most_common(),
            "qualify_variants": qual.most_common(5),
            "dispo_breakdown": dispos.most_common(),
            "campaigns": campaigns.most_common(),
            "transfer_rate": round(100 * wins / total, 1) if total else 0,
            "examples": examples,
        })
    out = {"count": len(scripts), "scripts": scripts}
    C.save_json(os.path.join(C.ANALYSIS_DIR, "scripts_detected.json"), out)
    return out


def flow_signature(t):
    st = t.get("stages", {})
    seq = [k for k, _l, _p in
           [("greeting", 0, 0), ("pitch", 0, 0), ("qualify", 0, 0),
            ("transfer", 0, 0), ("disqualify", 0, 0)] if st.get(k)]
    # did the customer object?
    objected = any(re.search(r"not interested|stop calling|take me off|don'?t call|"
                             r"who is this|why are you", tr["text"], re.I)
                   for tr in t.get("turns", []) if tr["speaker"] == "CUSTOMER")
    if objected:
        seq.append("objection")
    return " → ".join(seq) if seq else "(no speech)"


def discover_flows(transcripts):
    sigs = Counter()
    sig_examples = defaultdict(list)
    sig_dispos = defaultdict(Counter)
    for t in transcripts:
        sig = flow_signature(t)
        sigs[sig] += 1
        sig_dispos[sig][t["dispo"]] += 1
        if len(sig_examples[sig]) < 4:
            sig_examples[sig].append(t["id"])
    flows = []
    for sig, n in sigs.most_common():
        dispos = sig_dispos[sig]
        wins = sum(c for d, c in dispos.items() if C.dispo_is_win(d))
        flows.append({
            "signature": sig, "calls": n,
            "pct": round(100 * n / len(transcripts), 1),
            "dispo_breakdown": dispos.most_common(),
            "transfer_rate": round(100 * wins / n, 1),
            "examples": sig_examples[sig],
        })
    out = {"count": len(flows), "flows": flows}
    C.save_json(os.path.join(C.ANALYSIS_DIR, "flows_detected.json"), out)
    return out


def run():
    transcripts = C.all_transcripts()
    if not transcripts:
        print("[discover] no transcripts")
        return
    s = discover_scripts(transcripts)
    f = discover_flows(transcripts)
    print(f"[discover] {s['count']} distinct scripts, {f['count']} distinct flows")
    for sc in s["scripts"]:
        print(f"  Script {sc['id']}: {sc['calls']} calls | {sc['template'][:70]}")
    return s, f


if __name__ == "__main__":
    run()
