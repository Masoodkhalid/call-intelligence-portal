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
    "You are a call-center bot script writer. Write short, natural, spoken "
    "outbound bot scripts for Medicare outreach. "
    "STRICT RULES — never break these: "
    "1. NEVER mention 'licensed', 'insurance agency', 'insurance company', or any company name. "
    "2. NEVER say who you work for — the bot only gives its own first name. "
    "3. NEVER use formal phrases like 'We are reaching out' or 'I am calling from'. "
    "Use casual spoken language: 'I'm calling because...', 'So I wanted to...'. "
    "Match the tone of a real call center bot — short sentences, direct, conversational."
)

# Real lines found in actual calls — used to ground the style
_REAL_EXAMPLES = """
OPENING examples from real calls:
- "Good morning, my name is [Agent]. I'm reaching out because your Medicare profile hasn't been transferred into the national database for [Year] yet."
- "Hi, this is [Agent] and I'm calling because there are pending grocery and cash benefits worth up to $[Amount] available on your Medicare account."
- "Hi, I'm [Agent] and we pulled up your Medicare profile and there's a note showing your [Year] update hasn't been confirmed yet."

PITCH examples:
- "So I'm calling because there are pending grocery and cash benefits worth up to $[Amount] available on your Medicare account through the State Relief Program."
- "When that transfer is missing, it can cause delays in your coverage approvals."
- "We want to make sure your Part A and Part B are confirmed so you don't miss out on your 2026 benefits."

QUALIFY examples:
- "So you do have both Part A and Part B, right?"
- "So to get your file updated, do you have both Medicare Part A and Part B?"
- "Do you have both Part A and B of Medicare?"

TRANSFER examples:
- "Great, stay on the line — I'm going to transfer you to one of our specialists who can go over everything with you."
- "Perfect, I'm going to connect you with a specialist now who can walk you through the details."

DISQUALIFY examples:
- "Sorry, but you don't seem to qualify for the plans that we have. Have a great day."
- "You don't seem to qualify for the plans we have. Thank you for your time."
"""


def build_prompt(style_key, focus):
    res = load_research()
    facts = "\n".join(f"- {f['topic']}: {f['fact']}" for f in res.get("facts", []))
    style = STYLES.get(style_key, STYLES["warm"])
    return f"""Write a NEW 2026 Medicare outbound bot script. Use [Agent], [Year], [State], [$Amount] as placeholders.

STYLE: {style}
FOCUS / ANGLE: {focus}

ABSOLUTE DON'Ts — the script must NEVER contain:
- "licensed", "insurance agency", "insurance company", any company/agency name
- "We are reaching out", "I am calling from [company]", "on behalf of"
- Any phrase identifying who the bot works for

2026 Medicare facts (pick 2-3 most relevant):
{facts}

COPY THIS EXACT TONE — real lines from actual calls:
{_REAL_EXAMPLES}

What worked in past campaigns:
{winning_context()}

Write the full script:
TITLE: <short name>
OPENING: <1-2 lines — bot says its name and the reason, nothing else>
PITCH: <2-3 lines — the benefit/angle, short and direct>
QUALIFY: <one question confirming Part A & Part B>
OBJECTION HANDLING:
- Not interested -> <1 line>
- Who is this / is this a scam -> <1 line, no company name>
- I'm busy -> <1 line>
TRANSFER: <line connecting to specialist>
DID NOT QUALIFY: <short polite exit>
"""


import re as _re

# Patterns the LLM keeps inserting despite instructions — strip them from output.
_CLEAN_PATTERNS = [
    # "[Licensed Insurance Agency]" with leading preposition/verb
    (_re.compile(r'\b(with|from|at|for|represent(?:ing)?|I represent)\s+\[Licensed Insurance Agency\]', _re.I), ''),
    # "[Licensed Insurance Agency]" standalone
    (_re.compile(r'\[Licensed Insurance Agency\]', _re.I), ''),
    # "[Company Name], a licensed insurance agency" or "[Company Name]" standalone
    (_re.compile(r'\[Company Name\],?\s*(?:a licensed insurance agenc\w*)?', _re.I), ''),
    # "a/the licensed insurance agency/agent"
    (_re.compile(r',?\s*(?:a |the )?licensed insurance agenc\w*', _re.I), ''),
    # "licensed insurance" anywhere remaining
    (_re.compile(r'\blicensed insurance\b[^.!?]*', _re.I), ''),
    # dangling connectors left behind: "and .", "and I .", "this is ."
    (_re.compile(r'\b(and|or|but)\s*[,\.]'), '.'),
    (_re.compile(r'\bthis is\s*\.'), ''),
    (_re.compile(r'\bfrom\s*\.'), '.'),
    (_re.compile(r'\bfrom\s*$', _re.M), ''),
    # space before punctuation: "name ." → "name."
    (_re.compile(r'\s+([.,!?])'), r'\1'),
    # tidy double spaces and stray leading punctuation per line
    (_re.compile(r'[ \t]{2,}'), ' '),
    (_re.compile(r'^\s*[,\s]+', _re.M), ''),
    # trailing "calling." with nothing after is fine; "calling ." → "calling."
    (_re.compile(r'\bcalling\s*\.\s*$', _re.M), 'calling.'),
]


def _clean(text):
    for pat, repl in _CLEAN_PATTERNS:
        text = pat.sub(repl, text)
    # second pass: remove any remaining empty lines from removal
    lines = [l.strip() for l in text.splitlines()]
    text = '\n'.join(l for l in lines if l)
    return text.strip()


def generate(style_key="warm", focus="2026 Part D $2,100 out-of-pocket cap savings"):
    out = _clean(ollama_generate(build_prompt(style_key, focus), SYSTEM))
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
