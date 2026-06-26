"""Stage 4 — SCRIPT AGENT (local LLM via Ollama).

For each disposition it studies the flow analysis (where calls drop off, what
customers actually say) and writes an improved bot script designed to move more
calls toward a transfer (RAXFER). Runs fully locally against Ollama; if Ollama
or the model isn't available it falls back to a deterministic, rules-based
recommendation so the pipeline never blocks.
"""
import os
import sys
import json
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("SCRIPT_MODEL", "llama3.2:3b")

# Dispositions worth rewriting a recovery script for (the losing outcomes).
TARGET_DISPOS = ["NI", "DNQ", "LH", "DC", "NP", "N", "A", "BDNC"]


def ollama_generate(prompt, system=None, timeout=180):
    """Return model text, or None if Ollama is unavailable."""
    body = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 700},
    }
    if system:
        body["system"] = system
    data = json.dumps(body).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", "").strip()
    except Exception as e:  # noqa: BLE001
        print(f"  [script_agent] Ollama unavailable ({e}); using fallback")
        return None


SYSTEM = (
    "You are a senior outbound call-center script writer for a Medicare "
    "benefits qualification campaign. The bot's goal is to qualify the person "
    "(confirm Medicare Part A & Part B) and transfer them to a live licensed "
    "specialist. You write natural, compliant, friendly scripts. Never make "
    "false claims. Keep lines short and conversational."
)


def build_prompt(dispo, flow):
    label = flow["label"]
    funnel = "\n".join(
        f"  - {s['label']}: {s['pct']}% of calls reached this" for s in flow["funnel"])
    objections = "\n".join(
        f"  - \"{txt}\" (x{n})" for txt, n in flow["top_objections"][:6]) or "  (none captured)"
    customer = "\n".join(
        f"  - \"{txt}\" (x{n})" for txt, n in flow["top_customer_lines"][:8]) or "  (none captured)"
    return f"""Disposition: {dispo} = {label}  ({flow['count']} calls, avg {flow['avg_duration']}s)

How far these calls progressed through the pitch funnel:
{funnel}

What customers actually said on these calls:
{customer}

Detected objections:
{objections}

TASK:
1. In 2-3 sentences, diagnose WHY these calls ended in "{label}" and where the bot lost them.
2. Write an improved BOT SCRIPT (a short branching script with the bot's lines
   and how to respond to the objections above) that would recover more of these
   calls and move them toward a transfer to the specialist.
Format:
DIAGNOSIS:
<text>
IMPROVED SCRIPT:
<lines, using "Bot:" and "If customer says X -> Bot:" branches>
"""


def fallback_script(dispo, flow):
    label = flow["label"]
    tips = {
        "NI": "Acknowledge, give a one-line value hook, then ask a soft yes/no question instead of re-pitching.",
        "DNQ": "Confirm Part A & B earlier and more clearly before investing in the pitch; offer an alternative if not qualified.",
        "LH": "Shorten the opening; lead with the benefit and a quick question to keep them on the line.",
        "DC": "Add an early 'are you there?' re-engage line and slow the open so the line settles.",
        "NP": "Tighten the first 5 seconds so the pitch lands before they disengage.",
        "N": "Open with a short question that prompts a verbal response within 3 seconds.",
        "A": "Detect voicemail tone and either drop a 5-second callback message or hang up to save dial time.",
        "BDNC": "Honor do-not-call immediately and verify the number is valid before pitching.",
    }
    tip = tips.get(dispo, "Tighten the opening and confirm eligibility earlier.")
    return (f"DIAGNOSIS:\nCalls ending in {label} most often dropped before "
            f"reaching the qualify/transfer stages.\n\nIMPROVED SCRIPT (rules-based):\n"
            f"Bot: Hi, this is a quick call about your Medicare benefits — do you "
            f"have a moment?\nGuidance: {tip}\n"
            f"Bot (qualify early): Just to make sure I help the right way — do you "
            f"have both Part A and Part B?\n"
            f"If yes -> Bot: Great, let me connect you with a licensed specialist now, "
            f"please stay on the line.\n"
            f"If objection -> Bot: I completely understand — this is just to make sure "
            f"you don't miss benefits you're entitled to. Can I confirm one quick thing?")


def run():
    flows = C.load_json(os.path.join(C.ANALYSIS_DIR, "flows.json"))
    if not flows:
        print("[script_agent] no flows.json — run analyze first")
        return
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    results = {}
    for dispo in TARGET_DISPOS:
        flow = flows.get(dispo)
        if not flow:
            continue
        print(f"[script_agent] writing script for {dispo} ({flow['label']})...")
        out = ollama_generate(build_prompt(dispo, flow), system=SYSTEM)
        used = "ollama:" + MODEL
        if not out:
            out = fallback_script(dispo, flow)
            used = "fallback-rules"
        results[dispo] = {
            "dispo": dispo,
            "label": flow["label"],
            "count": flow["count"],
            "generated_at": now,
            "engine": used,
            "output": out,
        }
        C.save_json(os.path.join(C.SCRIPTS_DIR, f"{dispo}.json"), results[dispo])
    C.save_json(os.path.join(C.SCRIPTS_DIR, "index.json"),
                {"generated_at": now, "dispositions": list(results.keys())})
    print(f"[script_agent] done. Wrote {len(results)} scripts.")
    return results


if __name__ == "__main__":
    run()
