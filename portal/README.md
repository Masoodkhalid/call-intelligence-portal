# Call Intelligence Portal

Local, private pipeline + web portal that transcribes bot↔customer call
recordings, maps the conversation flow of every disposition, and uses a local
LLM to write improved bot scripts. See **CONCEPT.md** for the architecture.

## One-time setup (already done on this machine)
- `brew install whisper-cpp ffmpeg`
- Whisper model at `portal/models/ggml-base.en.bin`
- `ollama pull llama3.2:3b`  (local script-writing model)
- Python `Flask` (installed)

## Run the daily pipeline
Transcribe new calls → analyze flows → write scripts:
```bash
python3 portal/pipeline/run_daily.py
```
Individual stages:
```bash
python3 portal/pipeline/transcribe.py        # add --force to re-do all
python3 portal/pipeline/analyze.py
python3 portal/pipeline/script_agent.py
```

## Open the portal
```bash
python3 portal/server.py
# open http://127.0.0.1:5000
```
Tabs: **Dashboard** (KPIs, dispositions, campaigns) · **Transcripts** (search +
audio playback + BOT/CUSTOMER turns) · **Flow Maps** (funnel per disposition +
objections) · **Script Studio** (LLM-improved scripts per disposition).

## Schedule it daily (macOS launchd)
A starter agent is in `portal/com.callintel.daily.plist`. Install with:
```bash
cp portal/com.callintel.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.callintel.daily.plist
```
Edit the `<string>` paths inside the plist first if you move the project. It runs
`run_daily.py` every morning at 08:00; output goes to `portal/data/daily.log`.

## Data layout
```
portal/data/transcripts/  one JSON per call (text, segments, turns, stages)
portal/data/analysis/     summary.json, flows.json, last_run.json
portal/data/scripts/      <DISPO>.json improved scripts
```

## Adding new recordings
Drop new `*.mp3` into the same `mcc/<campaign>/<disposition>/` structure and
re-run the pipeline — transcription is incremental, only new files are processed.
