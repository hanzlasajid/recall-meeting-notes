"""Pick one screenshot per distinct screen in a recording and line it up with the transcript."""
import json
from pathlib import Path

import numpy as np

from .transcribe import hms, prepare_environment

SAMPLE_EVERY = 1.0      # seconds between frames compared
MIN_GAP = 8.0           # never two screenshots closer than this
SETTLE = 0.004          # "settled" = under 0.4% of pixels changed over 2 s (no scrolling)
FORCE_EVERY = 180.0     # keep a screenshot at least this often if anything changed
SMALL = (192, 108)
OUT_WIDTH = 1600


def _changed(a, b):
    return float((np.abs(a - b) > 18).mean())


def _sample(path, log):
    import av
    times, imgs = [], []
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        dur = float(c.duration / av.time_base) if c.duration else 0.0
        nxt = 0.0
        for fr in c.decode(s):
            if fr.time is None or fr.time < nxt:
                continue
            g = fr.reformat(width=SMALL[0], height=SMALL[1], format="gray").to_ndarray()
            times.append(fr.time)
            imgs.append(g.astype(np.int16))
            nxt = fr.time + SAMPLE_EVERY
            if len(times) % 120 == 0:
                print(f"\r  scanning {hms(fr.time)} / {hms(dur)}", end="", flush=True)
    print()
    if not times:
        raise RuntimeError("No video frames found - is this an audio-only file?")
    return np.array(times), np.stack(imgs)


def _select(times, imgs, thr):
    kept = [0]
    for i in range(2, len(times)):
        t = times[i]
        if t - times[kept[-1]] < MIN_GAP:
            continue
        if _changed(imgs[i], imgs[i - 2]) > SETTLE:
            continue
        d = _changed(imgs[i], imgs[kept[-1]])
        if d > thr or (d > 0.002 and t - times[kept[-1]] > FORCE_EVERY):
            kept.append(i)
    return kept


def _grab(path, stamps):
    import av
    out = {}
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        for t in stamps:
            c.seek(int(max(t - 0.5, 0) / s.time_base), stream=s, backward=True)
            for fr in c.decode(s):
                if fr.time is not None and fr.time >= t - 0.05:
                    img = fr.to_image()
                    if img.width > OUT_WIDTH:
                        img = img.resize((OUT_WIDTH, round(img.height * OUT_WIDTH / img.width)))
                    out[t] = img
                    break
    return out


def extract(video: Path, out_dir: Path, segments, max_frames=70, log=print):
    prepare_environment()
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f*.jpg"):
        old.unlink()

    log("Scanning the video for screen changes...")
    times, imgs = _sample(video, log)
    for thr in (0.01, 0.02, 0.035, 0.05, 0.08, 0.12, 0.2):
        kept = _select(times, imgs, thr)
        if len(kept) <= max_frames:
            break
    stamps = [float(times[i]) for i in kept]
    log(f"{len(stamps)} distinct screens. Saving screenshots...")
    full = _grab(video, stamps)

    index, md = [], [f"# Key screens: {video.name}\n"]
    for n, t in enumerate(stamps, 1):
        end = stamps[n] if n < len(stamps) else float("inf")
        name = f"f{n:03}_{hms(t).replace(':', '-')}.jpg"
        if t in full:
            full[t].save(frames_dir / name, quality=82)
        said = " ".join(s.text for s in (segments or []) if t - 2 <= s.start < end - 2)
        index.append({"file": f"frames/{name}", "start": hms(t), "start_s": round(t, 1),
                      "end": hms(end) if end != float("inf") else "end", "said": said})
        md.append(f"## {n}. {index[-1]['start']} - {index[-1]['end']}\n\n"
                  f"![](frames/{name})\n\n{said or '(no speech)'}\n")
    (out_dir / "frames.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "frames.md").write_text("\n".join(md), encoding="utf-8")
    return index


def load_frames(out_dir: Path):
    p = out_dir / "frames.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
