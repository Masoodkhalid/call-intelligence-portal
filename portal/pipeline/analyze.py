"""Stage 3 — FLOW-ANALYST AGENT.

Reads all transcripts and produces:
  * speaker-labelled turns (BOT vs CUSTOMER) using a corpus-built BOT line bank
    + fuzzy matching (templatised), which is far more accurate than per-call
    frequency because the bot's lines repeat across the whole corpus.
  * a per-disposition flow analysis (stage funnel + objections).
  * overall summary stats for the dashboard.

The BOT line bank is also reused by discover.py to count distinct scripts/flows.
"""
import os
import sys
import json
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# ---- Funnel stages ---------------------------------------------------------
STAGES = [
    ("greeting", "Greeting",
     r"\b(hello|good morning|good afternoon|good evening|my name is|this is)\b"),
    ("pitch", "Pitch / reason for call",
     r"\b(calling because|medicare|benefits?|profile|coverage|grocery|cash|"
     r"relief program|national database|eligible)\b"),
    ("qualify", "Qualify (Part A & B)",
     r"\b(part a|part b|do you have|qualify|both part)\b"),
    ("transfer", "Transfer to agent",
     r"\b(stay on the line|transfer you|specialist|take over|hold on|"
     r"connect you|one moment|please hold)\b"),
    ("disqualify", "Disqualified",
     r"\b(don'?t seem to qualify|not qualify|do not qualify|have a great day)\b"),
]

import re  # noqa: E402
OBJECTION_RE = re.compile(
    r"\b(not interested|no thank|take me off|stop calling|don'?t call|"
    r"remove me|scam|busy|hang up|already have|leave me alone|who is this|"
    r"why are you|don'?t want)\b", re.I)

BANK_MIN_DF = None  # computed at runtime


def build_bank(transcripts):
    """Return a list of (template, df) for lines that recur across calls —
    these are the scripted BOT lines."""
    df = Counter()
    n = len(transcripts)
    for t in transcripts:
        seen = set()
        for s in C.split_sentences(C.bot_portion(t["text"])):
            tpl = C.templatize(s)
            if len(tpl) < 10:
                continue
            if tpl not in seen:
                df[tpl] += 1
                seen.add(tpl)
    thresh = max(4, int(0.012 * n))   # appears in >=1.2% of calls (or 4)
    bank = [(tpl, c) for tpl, c in df.items() if c >= thresh]
    bank.sort(key=lambda x: -x[1])
    return bank, thresh


def label_turns(text, bank_templates):
    """Label each sentence BOT/CUSTOMER by fuzzy match against the BOT bank."""
    turns = []
    for s in C.split_sentences(text):
        tpl = C.templatize(s)
        speaker = "CUSTOMER"
        if len(tpl) >= 6:
            best = max((C.fuzzy(tpl, b) for b in bank_templates), default=0)
            if best >= 0.70:
                speaker = "BOT"
        # very short scripted cues
        if speaker == "CUSTOMER" and re.fullmatch(
                r"(hello|hi|good morning|good afternoon|are you there|"
                r"can you hear me|please hold on|one moment)", tpl):
            speaker = "BOT"
        turns.append({"speaker": speaker, "text": s})
    # merge consecutive same-speaker turns
    merged = []
    for t in turns:
        if merged and merged[-1]["speaker"] == t["speaker"]:
            merged[-1]["text"] += " " + t["text"]
        else:
            merged.append(dict(t))
    return merged


def stages_reached(text):
    low = (text or "").lower()
    return {key: bool(re.search(pat, low, re.I)) for key, _l, pat in STAGES}


def run():
    transcripts = C.all_transcripts()
    if not transcripts:
        print("[analyze] no transcripts yet — run transcribe first")
        return
    print(f"[analyze] analysing {len(transcripts)} transcripts")

    bank, thresh = build_bank(transcripts)
    bank_templates = [b[0] for b in bank]
    print(f"[analyze] BOT line bank: {len(bank)} scripted lines (df>={thresh})")
    C.save_json(os.path.join(C.ANALYSIS_DIR, "bot_bank.json"),
                {"threshold": thresh, "lines": bank})

    by_dispo = defaultdict(list)
    by_campaign = defaultdict(list)
    for t in transcripts:
        # analyse only the bot-led portion (ignore post-transfer human agent talk)
        bt = C.bot_portion(t["text"])
        t["bot_text"] = bt
        t["post_transfer_trimmed"] = (len(bt) < len(t["text"]))
        t["turns"] = label_turns(bt, bank_templates)
        t["stages"] = stages_reached(bt)
        t["bot_word_count"] = len(bt.split())
        C.save_json(os.path.join(C.TRANSCRIPTS_DIR, t["id"] + ".json"), t)
        by_dispo[t["dispo"]].append(t)
        by_campaign[t["campaign"]].append(t)

    flows = {}
    for dispo, items in by_dispo.items():
        n = len(items)
        funnel = []
        for key, label, _ in STAGES:
            hit = sum(1 for t in items if t["stages"].get(key))
            funnel.append({"key": key, "label": label,
                           "count": hit, "pct": round(100 * hit / n, 1)})
        cust = Counter()
        objections = Counter()
        for t in items:
            for turn in t["turns"]:
                if turn["speaker"] == "CUSTOMER":
                    cl = turn["text"].strip()
                    if len(cl) > 2:
                        cust[cl.lower()[:80]] += 1
                    if OBJECTION_RE.search(cl):
                        objections[cl.lower()[:80]] += 1
        flows[dispo] = {
            "dispo": dispo, "label": C.dispo_label(dispo),
            "is_win": C.dispo_is_win(dispo), "count": n,
            "avg_duration": round(sum(t["duration"] for t in items) / n, 1),
            "avg_words": round(sum(t.get("bot_word_count", t["word_count"]) for t in items) / n, 1),
            "funnel": funnel,
            "top_customer_lines": cust.most_common(12),
            "top_objections": objections.most_common(10),
            "example_ids": [t["id"] for t in items[:5]],
        }
    C.save_json(os.path.join(C.ANALYSIS_DIR, "flows.json"), flows)

    total = len(transcripts)
    wins = sum(1 for t in transcripts if C.dispo_is_win(t["dispo"]))
    dispo_counts = Counter(t["dispo"] for t in transcripts)
    campaign_stats = {}
    for camp, items in by_campaign.items():
        cn = len(items)
        cw = sum(1 for t in items if C.dispo_is_win(t["dispo"]))
        campaign_stats[camp] = {
            "count": cn, "wins": cw,
            "transfer_rate": round(100 * cw / cn, 1),
            "dispo_counts": dict(Counter(t["dispo"] for t in items)),
        }
    summary = {
        "total_calls": total, "transfers": wins,
        "transfer_rate": round(100 * wins / total, 1),
        "dispo_counts": dict(dispo_counts),
        "dispo_labels": {k: C.dispo_label(k) for k in dispo_counts},
        "campaigns": campaign_stats,
        "avg_duration": round(sum(t["duration"] for t in transcripts) / total, 1),
    }
    C.save_json(os.path.join(C.ANALYSIS_DIR, "summary.json"), summary)
    print(f"[analyze] done. {total} calls, {wins} transfers "
          f"({summary['transfer_rate']}%).")
    return summary


if __name__ == "__main__":
    run()
