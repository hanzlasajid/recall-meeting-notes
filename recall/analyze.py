"""Turn the transcript + screenshots into a meeting report with Claude (or a prompt file for manual use)."""
import base64
import io
from datetime import datetime
from pathlib import Path

from .transcribe import hms

PROMPT_FILE = Path(__file__).with_name("report_prompt.md")
REPORT_MODELS = {
    "sonnet": ("claude-sonnet-5-5", "Claude Sonnet - recommended: fast, low cost, very good"),
    "opus": ("claude-opus-5-5", "Claude Opus - deepest analysis, higher cost"),
    "local": (None, "Local AI on this computer - free and private, slower and less detailed (no key needed)"),
    "none": (None, "No AI report - just save a prompt file to paste into Claude yourself"),
}


def meeting_facts(video: Path, duration: float) -> str:
    try:
        when = datetime.fromtimestamp(video.stat().st_mtime).strftime("%d %b %Y, %H:%M")
    except OSError:
        when = "unknown"
    return f"File: {video.name}\nRecorded (file date): {when}\nLength: {hms(duration)}"


def _pick(frames, max_images):
    if len(frames) <= max_images:
        return frames
    step = (len(frames) - 1) / (max_images - 1)
    return [frames[round(i * step)] for i in range(max_images)]


def _image_b64(path: Path, width=1280):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _frame_list(frames):
    return "\n".join(f"- {f['file']}  ({f['start']}-{f['end']})  said: {f['said'][:400] or '(no speech)'}"
                     for f in frames)


def build_user_text(facts, transcript_txt, frames):
    return (f"# Meeting facts\n{facts}\n\n"
            f"# Screenshot list ({len(frames)} screenshots, attached as images in this order)\n"
            f"{_frame_list(frames)}\n\n"
            f"# Transcript (speech recognition, no speaker labels)\n{transcript_txt}\n\n"
            "Write the report now, following the output format exactly.")


def write_manual_prompt(out_dir: Path, facts, transcript_txt, frames):
    """A file the user can paste into Claude together with the screenshots."""
    text = ("<!-- Paste everything below into Claude and attach the images from the frames folder "
            "(or the most important ones). -->\n\n"
            + PROMPT_FILE.read_text(encoding="utf-8") + "\n\n---\n\n"
            + build_user_text(facts, transcript_txt, frames))
    p = out_dir / "analysis_prompt.md"
    p.write_text(text, encoding="utf-8")
    return p


def run_claude(out_dir: Path, facts, transcript_txt, frames, api_key, model_key="sonnet",
               max_images=40, log=print) -> str:
    import anthropic
    model = REPORT_MODELS[model_key][0]
    chosen = _pick(frames, max_images)
    content = [{"type": "text", "text": build_user_text(facts, transcript_txt, chosen)}]
    for f in chosen:
        p = out_dir / f["file"]
        if p.exists():
            content.append({"type": "text", "text": f"Screenshot {f['file']} ({f['start']})"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": _image_b64(p)}})
    log(f"Sending the transcript and {len(chosen)} screenshots to {model}...")
    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(model=model, max_tokens=16000,
                                system=PROMPT_FILE.read_text(encoding="utf-8"),
                                messages=[{"role": "user", "content": content}]) as stream:
        chars = 0
        for piece in stream.text_stream:
            chars += len(piece)
            if chars % 2000 < len(piece):
                print(f"\r  writing report... {chars:,} characters", end="", flush=True)
        final = stream.get_final_message()
    print()
    text = "".join(b.text for b in final.content if b.type == "text").strip()
    if text.startswith("```"):                       # strip an accidental outer code fence
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    u = final.usage
    log(f"Report written ({u.input_tokens:,} tokens in, {u.output_tokens:,} out).")
    return text
