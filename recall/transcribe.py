"""Speech to text: faster-whisper (NVIDIA GPU / CPU) or mlx-whisper (Apple Silicon GPU)."""
import glob
import json
import os
import site
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

_prepared = False


def prepare_environment():
    """Make pip-installed CUDA DLLs findable on Windows and smooth over library quirks."""
    global _prepared
    if _prepared:
        return
    _prepared = True
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    dirs = []
    try:
        dirs = site.getsitepackages() + [site.getusersitepackages()]
    except Exception:
        pass
    for sp in dirs:
        for bin_dir in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    # PyAV 15+ removed `metadata_errors`, which faster-whisper still passes to av.open().
    try:
        import av
        if not getattr(av.open, "_recall_patched", False):
            original = av.open

            def compat_open(*args, **kwargs):
                kwargs.pop("metadata_errors", None)
                return original(*args, **kwargs)
            compat_open._recall_patched = True
            av.open = compat_open
    except ImportError:
        pass


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)


def ts(sec: float, comma=True) -> str:
    ms = int(round(max(sec, 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{',' if comma else '.'}{ms:03}"


def hms(sec: float) -> str:
    return ts(sec)[:8]


# ---------------------------------------------------------------------------------------------
def _run_faster_whisper(video, choice, language, vocab, log):
    from faster_whisper import WhisperModel
    log(f"Loading {choice.model} on {choice.device.upper()} ({choice.compute_type})...")
    extra = {"cpu_threads": os.cpu_count() or 4} if choice.device == "cpu" else {}
    model = WhisperModel(choice.model, device=choice.device, compute_type=choice.compute_type, **extra)
    segments, info = model.transcribe(
        str(video), language=language or None, beam_size=5, vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500), condition_on_previous_text=False,
        word_timestamps=True, initial_prompt=vocab or None)
    if not language:
        log(f"Detected language: {info.language}")
    out, t0 = [], time.time()
    for seg in segments:                      # transcription happens while iterating
        out.append(Segment(seg.start, seg.end, seg.text.strip(),
                           [Word(w.word, w.start, w.end) for w in (seg.words or [])]))
        print(f"\r  {hms(seg.end)} / {hms(info.duration)}  ({time.time() - t0:.0f}s)", end="", flush=True)
    print()
    return out, info.duration


def _run_mlx(video, choice, language, vocab, log):
    import mlx_whisper
    from faster_whisper.audio import decode_audio   # decodes with PyAV, so no ffmpeg install needed
    log("Decoding audio...")
    audio = decode_audio(str(video), sampling_rate=16000)
    log(f"Transcribing with {choice.model} on the Apple GPU...")
    r = mlx_whisper.transcribe(audio, path_or_hf_repo=choice.model, language=language or None,
                               word_timestamps=True, initial_prompt=vocab or None,
                               condition_on_previous_text=False, verbose=False)
    out = [Segment(s["start"], s["end"], s["text"].strip(),
                   [Word(w["word"], w["start"], w["end"]) for w in s.get("words", [])])
           for s in r["segments"]]
    return out, len(audio) / 16000


def transcribe(video: Path, choice, language: str, vocab: str, log=print):
    prepare_environment()
    try:
        if choice.backend == "mlx":
            return _run_mlx(video, choice, language, vocab, log)
        return _run_faster_whisper(video, choice, language, vocab, log)
    except Exception as e:
        if choice.device == "cpu":
            raise
        from .hardware import Choice
        log(f"GPU transcription failed ({e}). Falling back to the processor (medium model).")
        fallback = Choice("cpu:medium", "medium on processor", "faster-whisper", "medium", "cpu", "int8")
        return _run_faster_whisper(video, fallback, language, vocab, log)


# ---------------------------------------------------------------------------------------------
MAX_LINE, MAX_LINES, MAX_CUE_SECONDS = 42, 2, 6.0


def _wrap(text: str) -> str:
    if len(text) <= MAX_LINE:
        return text
    mid = len(text) // 2
    left, right = text.rfind(" ", 0, mid + 1), text.find(" ", mid)
    cut = left if right == -1 or (left != -1 and mid - left <= right - mid) else right
    if cut <= 0:
        return text
    return text[:cut].strip() + "\n" + text[cut:].strip()


def build_cues(segments):
    """Readable subtitles: <= 2 lines x 42 chars, <= 6 s, break after sentence ends."""
    cues, words = [], []
    limit = MAX_LINE * MAX_LINES

    def flush():
        if words:
            cues.append((words[0].start, words[-1].end, _wrap("".join(w.word for w in words).strip())))
            words.clear()

    for seg in segments:
        if not seg.words:                                  # no word timings: one cue per segment
            flush()
            cues.append((seg.start, seg.end, _wrap(seg.text)))
            continue
        for w in seg.words:
            if words:
                if (len("".join(x.word for x in words) + w.word) > limit
                        or w.end - words[0].start > MAX_CUE_SECONDS):
                    flush()
            words.append(w)
            if w.word.strip().endswith((".", "?", "!")) and w.end - words[0].start > 1.0:
                flush()
        flush()
    return cues


def write_outputs(segments, duration, video: Path, out_dir: Path, choice):
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = build_cues(segments)
    srt = "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(cues, 1))
    (out_dir / "subtitles.srt").write_text(srt, encoding="utf-8")
    try:                                   # a copy next to the video so players load it automatically
        video.with_suffix(".srt").write_text(srt, encoding="utf-8")
    except OSError:
        pass
    txt = "\n".join(f"[{hms(s.start)}] {s.text}" for s in segments)
    (out_dir / "transcript.txt").write_text(txt, encoding="utf-8")
    (out_dir / "transcript.json").write_text(json.dumps({
        "video": video.name, "duration": duration, "model": choice.model, "device": choice.device,
        "segments": [asdict(s) for s in segments]}, ensure_ascii=False), encoding="utf-8")
    return len(cues)


def load_transcript(out_dir: Path):
    p = out_dir / "transcript.json"
    if not p.exists():
        return None, 0.0
    d = json.loads(p.read_text(encoding="utf-8"))
    segs = [Segment(s["start"], s["end"], s["text"], [Word(**w) for w in s.get("words", [])])
            for s in d["segments"]]
    return segs, d.get("duration", segs[-1].end if segs else 0.0)
