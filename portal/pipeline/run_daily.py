"""ORCHESTRATOR — runs the full agent chain once.

  ingest (implicit) -> transcribe (incremental) -> analyze -> script_agent

Wire this to a daily schedule (cron / launchd) and every morning the portal
shows freshly transcribed calls, updated flow maps, and new script suggestions.
"""
import os
import sys
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C       # noqa: E402
import transcribe        # noqa: E402
import analyze           # noqa: E402
import discover          # noqa: E402
import script_agent      # noqa: E402


def run(skip_scripts=False):
    t0 = time.time()
    print("=" * 60)
    print(f"DAILY RUN @ {datetime.datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60)

    new = transcribe.run()
    summary = analyze.run()
    discover.run()
    if not skip_scripts:
        script_agent.run()

    report = {
        "ran_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "new_transcripts": new,
        "elapsed_sec": round(time.time() - t0, 1),
        "summary": summary,
    }
    C.save_json(os.path.join(C.ANALYSIS_DIR, "last_run.json"), report)
    print(f"\nDONE in {report['elapsed_sec']}s. {new} new calls processed.")
    return report


if __name__ == "__main__":
    run(skip_scripts="--no-scripts" in sys.argv[1:])
