# Call Intelligence Portal — Concept & Architecture

A local, private system that turns your raw bot-call recordings into daily,
actionable intelligence: **transcripts → flow maps per disposition → improved
bot scripts**, produced by a chain of cooperating agents.

Everything runs **on your Mac**. No call audio leaves the machine.

---

## The agent team (assembly line)

Each agent does one job and hands off to the next. An **Orchestrator** runs the
whole chain once a day.

| # | Agent | Job | Tech (local) |
|---|-------|-----|--------------|
| 1 | **Ingest** | Watch `mcc/…/<disposition>/*.mp3`, read date/time/phone/campaign/disposition from each filename. | `pipeline/common.py` |
| 2 | **Transcriber** | Speech → text for every new call. Incremental — only new audio. | whisper.cpp (`ggml-base.en`) |
| 3 | **Flow-Analyst** | Separate BOT vs CUSTOMER speech, map each call onto a stage funnel, find drop-off points + common objections per disposition. | `pipeline/analyze.py` |
| 4 | **Script Agent** | For each losing disposition, diagnose *why* and write an improved bot script to recover more transfers. | Ollama `llama3.2:3b` |
| 5 | **QA / Scorer** | (extensible) compare new vs old outcomes, flag risky changes. | rules + LLM |
| — | **Portal (UI)** | Dashboard, transcript browser + audio, flow maps, Script Studio, daily report. | Flask web app |

```
recordings ─▶ Ingest ─▶ Transcriber ─▶ Flow-Analyst ─▶ Script Agent ─▶ Portal
                                  └──────── Orchestrator runs daily ────────┘
```

## How "speaker separation" works without diarization
The bot's lines are scripted, so they **repeat across many calls** in a campaign.
The Flow-Analyst counts how often each sentence recurs; high-frequency sentences
are labelled **BOT**, the rest **CUSTOMER**. This is fully offline and needs no
model — and as a bonus it reconstructs the canonical bot script.

## The disposition funnel
Every call is mapped onto these stages, so "the flow of a disposition" is simply
*how far calls of that disposition typically get before they end*:

`Greeting → Pitch → Qualify (Part A & B) → Transfer → (or) Disqualified`

A **DNQ** call reaches Qualify then stops; an **LH** call dies at Pitch; a
**RAXFER** call completes the funnel. The Flow Maps tab shows this for each code.

## Daily operation
1. New recordings land in `mcc/…`.
2. `pipeline/run_daily.py` runs (manually or via the scheduled job).
3. Portal shows: new transcripts, refreshed flow maps, new script suggestions.

See `README.md` for run + schedule instructions.

## Disposition glossary (confirmed from the audio)
| Code | Meaning |
|------|---------|
| A | Answering machine / voicemail |
| N | No response |
| NP | No pitch (cut before pitch finished) |
| LH | Live hangup during pitch |
| NI | Not interested |
| DNQ | Did not qualify |
| DC | Disconnected mid-flow |
| BDNC | Bad number / do-not-call |
| DAIR (deadair) | Dead air |
| **RAXFER** | **Transferred to live agent — the win** |
