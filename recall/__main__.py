"""Recall - run with:  python -m recall [video ...] [--no-gui] [--model KEY] [--report sonnet|opus|local|none]"""
import argparse
import sys
import time
from pathlib import Path

from . import config, hardware, ui
from . import analyze, frames as frames_mod, local_llm, render, transcribe


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def process(video: Path, s: dict, cfg: dict):
    out_dir = video.with_name(video.stem + "_notes")
    out_dir.mkdir(exist_ok=True)
    t0 = time.time()

    # 1. Transcript + subtitles
    segments, duration = transcribe.load_transcript(out_dir) if s["reuse"] else (None, 0)
    if segments:
        log(f"Step 1/3  Reusing the existing transcript ({len(segments)} lines).")
    else:
        log(f"Step 1/3  Transcribing with {s['choice'].label}")
        segments, duration = transcribe.transcribe(video, s["choice"], s["language"], s["vocabulary"], log)
        n = transcribe.write_outputs(segments, duration, video, out_dir, s["choice"])
        log(f"          {len(segments)} transcript lines, {n} subtitles.")

    # 2. Key screenshots
    shots = frames_mod.load_frames(out_dir) if s["reuse"] else None
    if shots:
        log(f"Step 2/3  Reusing {len(shots)} existing screenshots.")
    else:
        log("Step 2/3  Picking key screenshots")
        try:
            shots = frames_mod.extract(video, out_dir, segments, cfg.get("max_frames", 70), log)
        except Exception as e:                      # audio-only files etc.
            log(f"          No screenshots ({e}).")
            shots = []

    # 3. Report (screenshots the user deleted from frames/ are left out)
    shots = [f for f in (shots or []) if (out_dir / f["file"]).exists()]
    facts = analyze.meeting_facts(video, duration)
    transcript_txt = (out_dir / "transcript.txt").read_text(encoding="utf-8")
    prompt_file = analyze.write_manual_prompt(out_dir, facts, transcript_txt, shots)
    report_html, md = None, None
    if s["report_model"] == "none":
        log("Step 3/3  Skipped the AI report. analysis_prompt.md is ready to paste into Claude.")
    elif s["report_model"] == "local":
        log("Step 3/3  Writing the meeting report with a local AI model")
        try:
            md = local_llm.run_local(out_dir, facts, transcript_txt, shots, s["local_model"], log)
        except Exception as e:
            log(f"          The local report failed: {e}")
            log("          analysis_prompt.md is ready to paste into Claude instead.")
    else:
        log("Step 3/3  Writing the meeting report")
        md = analyze.run_claude(out_dir, facts, transcript_txt, shots, s["api_key"], s["report_model"],
                                cfg.get("max_images", 40), log)
    if md:
        (out_dir / "report.md").write_text(md, encoding="utf-8")
        report_html = out_dir / "report.html"
        report_html.write_text(render.to_html(md, out_dir), encoding="utf-8")

    mins = (time.time() - t0) / 60
    ui.done(f"Done in {mins:.1f} min. Everything is in: {out_dir}"
            + (f"\nOpen report.html for the report." if report_html else f"\nPrompt file: {prompt_file}"),
            out_dir, report_html)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="recall", description=__doc__)
    ap.add_argument("videos", nargs="*", help="recording(s); omit to choose with a file picker")
    ap.add_argument("--no-gui", action="store_true", help="use recommended settings without asking")
    ap.add_argument("--model", help="transcription model key, e.g. cuda:large-v3-turbo, mlx:large-v3-turbo, cpu:small")
    ap.add_argument("--report", choices=["sonnet", "opus", "local", "none"],
                    help="local = write the report on this computer with Ollama (installs it if needed)")
    ap.add_argument("--language", help="e.g. en, de (default: auto-detect)")
    ap.add_argument("--fresh", action="store_true", help="redo transcript and screenshots even if they exist")
    ap.add_argument("--hardware", action="store_true", help="only show hardware and the recommended model")
    a = ap.parse_args(argv)

    cfg = config.load()
    log("Checking this computer's processor, memory and graphics card...")
    hw = hardware.detect()
    opts, rec_key = hardware.choices(hw)
    local_model = cfg.get("local_model") or local_llm.recommend(hw)
    if a.hardware:
        print("\n".join(hw.lines()))
        print("Recommended:", rec_key, "-", hardware.explain(hw, {o.key: o for o in opts}[rec_key]))
        print("Local report model (when there is no API key):", local_llm.describe(local_model))
        return 0

    videos = [Path(v) for v in a.videos] or [ui.pick_video()]
    videos = [v for v in videos if v]
    if not videos:
        print("No file chosen.")
        return 1

    for video in videos:
        if not video.exists():
            print(f"File not found: {video}")
            continue
        has_outputs = (video.with_name(video.stem + "_notes") / "transcript.json").exists()
        if a.no_gui or a.model:
            by_key = {o.key: o for o in opts}
            choice = by_key.get(a.model or rec_key) or by_key[rec_key]
            rep = a.report or cfg.get("report_model", "sonnet")
            if rep in ("sonnet", "opus") and not cfg.get("api_key"):
                log("No Anthropic API key, so no Claude report. Add --report local to write it on this computer.")
                rep = "none"
            s = dict(choice=choice, language=a.language or cfg.get("language", ""),
                     vocabulary=cfg.get("vocabulary", ""), report_model=rep, local_model=local_model,
                     api_key=cfg.get("api_key", ""), remember=False, reuse=has_outputs and not a.fresh)
        else:
            s = ui.settings(video, hw, opts, rec_key, cfg, has_outputs and not a.fresh, local_model)
            if not s:
                print("Cancelled.")
                continue
            s["local_model"] = local_model
            cfg.update(language=s["language"], vocabulary=s["vocabulary"], report_model=s["report_model"],
                       api_key=s["api_key"])
            config.save(cfg, remember_key=s["remember"])
        if a.language:
            s["language"] = a.language
        process(video, s, cfg)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(130)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nSomething went wrong: {e}")
        sys.exit(1)
