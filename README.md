# Call Intelligence Portal

A local, private AI pipeline that turns Medicare bot call recordings into daily intelligence:
transcripts → speaker labels → flow maps → script detection → improved scripts → new script generation.

**Everything runs on your Mac. No audio or transcript data leaves your machine.**

---

## What's inside

| Tab | What it shows |
|-----|---------------|
| **Dashboard** | KPIs — total calls, transfers, transfer rate by campaign & disposition |
| **Transcripts** | Search & filter all 800+ calls, click to read BOT/CUSTOMER turns + play audio |
| **Scripts Detected** | The distinct bot scripts found in the recordings (pitch, qualify, transfer lines) |
| **Flow Maps** | How far each disposition gets through the funnel; top customer objections |
| **Recovery Scripts** | AI-improved scripts per losing disposition (NI, DNQ, LH, etc.) |
| **Script Generator** | Press a button → local AI writes a brand-new 2026 Medicare script |

---

## Requirements

| Tool | Purpose | macOS install |
|------|---------|---------------|
| macOS 12+ | OS | — |
| [Homebrew](https://brew.sh) | Package manager | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |
| Python 3.9+ | Pipeline & server | `brew install python` |
| ffmpeg | Audio conversion | `brew install ffmpeg` |
| whisper.cpp | Local speech-to-text | `brew install whisper-cpp` |
| Ollama | Local LLM runtime | `brew install ollama` |
| llama3.2:3b | Script-writing model (~2 GB) | `ollama pull llama3.2:3b` |
| Flask 3.x | Web server | `pip3 install flask` |

---

## Installation (step by step)

### Option A — One command (recommended)

```bash
git clone https://github.com/Masoodkhalid/call-intelligence-portal.git
cd call-intelligence-portal
bash setup.sh
```

The script installs every dependency, downloads the Whisper model, and tells you exactly what to do next.

---

### Option B — Manual steps

**1. Clone the repo**
```bash
git clone https://github.com/Masoodkhalid/call-intelligence-portal.git
cd call-intelligence-portal
```

**2. Install system tools**
```bash
brew install ffmpeg whisper-cpp ollama
```

**3. Install the local LLM model (~2 GB download)**
```bash
ollama serve &          # start Ollama in background
ollama pull llama3.2:3b
```

**4. Install Python dependencies**
```bash
pip3 install -r requirements.txt
```

**5. Download the Whisper speech model (~141 MB)**
```bash
mkdir -p portal/models
curl -L -o portal/models/ggml-base.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
```

**6. Add the recordings**

The `mcc/` folder is not in the repo (files are too large). Copy it from the shared drive or ask your team lead.

Expected structure:
```
mcc/
├── mcc3/
│   ├── mcc3-A/          ← Answering Machine calls
│   ├── mcc3-raxfer/     ← Transferred calls (wins)
│   ├── mcc3-NI/         ← Not Interested
│   └── ...
├── mcc5/
├── mcc7/
└── mcc11/
```

Each file is named: `YYYYMMDD-HHMMSS_<phone>-all.mp3`

---

## Running the pipeline

**First time (or when new recordings arrive):**
```bash
python3 portal/pipeline/run_daily.py
```

This runs all 5 agents in sequence:
1. **Ingest** — reads filename metadata (date/time/phone/campaign/disposition)
2. **Transcriber** — speech → text via local Whisper (incremental, skips already-done files)
3. **Flow-Analyst** — labels BOT vs CUSTOMER, maps each call onto the funnel stages
4. **Script Discovery** — finds distinct bot scripts + flow paths across the corpus
5. **Script Agent** — writes AI-improved recovery scripts per losing disposition

> First run on 800+ calls takes ~15–20 minutes. Daily incremental runs take seconds.

**Run individual stages:**
```bash
python3 portal/pipeline/transcribe.py       # transcribe new calls only
python3 portal/pipeline/analyze.py          # re-analyse all transcripts
python3 portal/pipeline/discover.py         # re-detect scripts & flows
python3 portal/pipeline/script_agent.py     # regenerate recovery scripts
```

---

## Starting the portal

```bash
python3 portal/server.py
```

Then open **http://127.0.0.1:5000** in your browser.

To run in background:
```bash
nohup python3 portal/server.py > portal/data/server.log 2>&1 &
```

To stop it:
```bash
pkill -f "portal/server.py"
```

---

## Schedule daily automation (macOS)

To automatically process new recordings every morning at 8:00 AM:

```bash
# Edit the plist to confirm paths are correct for your machine
nano portal/com.callintel.daily.plist

# Install
cp portal/com.callintel.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.callintel.daily.plist
```

Output is logged to `portal/data/daily.log`.

---

## Disposition codes

| Code | Meaning |
|------|---------|
| **RAXFER** | Transferred to live agent ✅ (the win) |
| A | Answering Machine |
| N | No Answer |
| NP | No Pitch — call ended before pitch finished |
| LH | Live Hangup during pitch |
| NI | Not Interested |
| DNQ | Did Not Qualify |
| DC | Disconnected |
| BDNC | Bad number / Do Not Call |
| DAIR / deadair | Dead air |

---

## Project structure

```
call-intelligence-portal/
├── setup.sh                          ← one-command setup
├── requirements.txt
├── README.md
├── mcc/                              ← recordings (NOT in repo, copy manually)
└── portal/
    ├── server.py                     ← Flask web server
    ├── templates/index.html          ← full single-page UI
    ├── CONCEPT.md                    ← multi-agent architecture explained
    ├── com.callintel.daily.plist     ← macOS daily schedule
    ├── models/
    │   └── ggml-base.en.bin          ← Whisper model (downloaded by setup.sh)
    ├── pipeline/
    │   ├── run_daily.py              ← orchestrator (runs all agents)
    │   ├── common.py                 ← shared helpers + constants
    │   ├── transcribe.py             ← Agent 2: Whisper transcription
    │   ├── analyze.py                ← Agent 3: flow analysis + speaker labels
    │   ├── discover.py               ← Agent 3b: script + flow discovery
    │   ├── script_agent.py           ← Agent 4: LLM recovery scripts
    │   └── generator.py              ← Script Generator (on-demand)
    └── data/
        ├── transcripts/              ← one JSON per call
        ├── analysis/                 ← flows.json, summary.json, etc.
        ├── scripts/                  ← recovery scripts per disposition
        ├── generated/                ← generator history
        └── research/
            └── medicare_2026.json    ← verified 2026 Medicare facts
```

---

## Troubleshooting

**`whisper-cli: command not found`**
```bash
brew install whisper-cpp
```

**`ollama: connection refused`**
```bash
ollama serve &    # start Ollama first, then retry
```

**`No module named flask`**
```bash
pip3 install flask
```

**Portal shows "no transcripts yet"**
- Make sure `mcc/` is in the project root
- Run `python3 portal/pipeline/run_daily.py` first

**Whisper model missing**
```bash
curl -L -o portal/models/ggml-base.en.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
```

---

## Team access

The repo is private. To add a team member:
1. Go to [github.com/Masoodkhalid/call-intelligence-portal](https://github.com/Masoodkhalid/call-intelligence-portal)
2. **Settings → Collaborators → Add people**
3. Enter their GitHub username or email
