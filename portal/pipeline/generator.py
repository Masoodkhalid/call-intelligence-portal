"""SCRIPT GENERATOR — creates brand-new 2026 Medicare bot scripts on demand.

Grounded in verified 2026 facts (data/research/medicare_2026.json) and CMS
compliance rules, and informed by which existing scripts actually earned
transfers. Runs on the local LLM (Ollama). Exposed via the portal's
"Script Generator" page — press a style button and it writes a fresh script.
"""
import os
import sys
import json
import datetime
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("SCRIPT_MODEL", "llama3.2:3b")
RESEARCH = os.path.join(C.DATA_DIR, "research", "medicare_2026.json")
GEN_DIR = os.path.join(C.DATA_DIR, "generated")
os.makedirs(GEN_DIR, exist_ok=True)

STYLES = {
    "warm":        "Warm & empathetic — friendly neighbour tone, lots of acknowledgement.",
    "direct":      "Direct & efficient — short lines, gets to the point fast, respects their time.",
    "consultative":"Consultative advisor — asks questions first, positions as a helpful expert.",
    "benefit_led": "Benefit-led — opens with a concrete 2026 benefit/saving, then qualifies.",
    "permission":  "Permission-based — asks for a moment of their time before pitching, low pressure.",
}


def load_research():
    return C.load_json(RESEARCH, {}) or {}


def winning_context():
    """Summarise which discovered scripts earned the most transfers, to guide style."""
    sd = C.load_json(os.path.join(C.ANALYSIS_DIR, "scripts_detected.json"), {}) or {}
    lines = []
    for s in (sd.get("scripts") or [])[:3]:
        lines.append(f"- \"{s['template'][:80]}\" — {s['calls']} calls, "
                     f"{s['transfer_rate']}% transferred")
    return "\n".join(lines) or "(no prior data)"


def ollama_generate(prompt, system, timeout=240):
    body = {"model": MODEL, "prompt": prompt, "system": system, "stream": False,
            "options": {"temperature": 0.7, "num_predict": 900}}
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()).get("response", "").strip()
    except Exception as e:  # noqa: BLE001
        return f"[generator] LLM unavailable: {e}"


SYSTEM = (
    "You are an expert outbound call-center script writer for a LICENSED "
    "Medicare insurance agency (not the government). You write natural, spoken, "
    "branching bot scripts for 2026 Medicare outreach. You are strictly "
    "compliant: you never pretend to be Medicare/CMS, never use fake urgency, "
    "and never promise benefits the person may not qualify for. Scripts are "
    "warm, honest, and designed to qualify (confirm Part A & B) and transfer "
    "interested people to a licensed specialist."
)


def build_prompt(style_key, focus):
    res = load_research()
    facts = "\n".join(f"- {f['topic']}: {f['fact']}" for f in res.get("facts", []))
    rules = "\n".join(f"- {r}" for r in res.get("compliance_rules", []))
    style = STYLES.get(style_key, STYLES["warm"])
    return f"""Write a NEW 2026 Medicare outbound bot script.

STYLE: {style}
FOCUS OF THE PITCH: {focus}

Use ONLY these verified 2026 facts (do not invent benefits):
{facts}

COMPLIANCE RULES (must follow):
{rules}

For context, here is what worked in past campaigns (learn the structure, but be compliant):
{winning_context()}

Produce the script in this exact format:
TITLE: <catchy short name>
OPENING: <bot's first 1-2 lines, including honest identification>
PITCH: <2-3 lines using a real 2026 fact>
QUALIFY: <the question that confirms Part A & Part B>
OBJECTION HANDLING:
- If "not interested" -> <bot line>
- If "is this a scam / who are you" -> <bot line>
- If "I'm busy" -> <bot line>
TRANSFER: <line that hands off to a licensed specialist>
CLOSE (not interested): <polite exit + honors do-not-call>
"""


def generate(style_key="warm", focus="2026 Part D $2,100 out-of-pocket cap savings"):
    out = ollama_generate(build_prompt(style_key, focus), SYSTEM)
    rec = {
        "id": datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "style": style_key, "style_desc": STYLES.get(style_key, ""),
        "focus": focus, "engine": "ollama:" + MODEL, "output": out,
    }
    C.save_json(os.path.join(GEN_DIR, rec["id"] + ".json"), rec)
    return rec


def list_generated():
    out = []
    for fn in sorted(os.listdir(GEN_DIR), reverse=True):
        if fn.endswith(".json"):
            r = C.load_json(os.path.join(GEN_DIR, fn))
            if r:
                out.append(r)
    return out


if __name__ == "__main__":
    style = sys.argv[1] if len(sys.argv) > 1 else "warm"
    r = generate(style)
    print(r["output"])
