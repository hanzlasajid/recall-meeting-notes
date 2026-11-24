"""Small per-user settings file (~/.recall/config.json)."""
import json
import os
from pathlib import Path

PATH = Path.home() / ".recall" / "config.json"
OLD_PATH = Path.home() / ".meetingnotes" / "config.json"     # before the rename to Recall
DEFAULTS = {
    "api_key": "",            # Anthropic API key; ANTHROPIC_API_KEY environment variable wins if set
    "report_model": "sonnet", # sonnet | opus | local | none
    "language": "",           # "" = auto-detect, or e.g. "en", "de"
    "vocabulary": "",         # names and terms to help speech recognition spell them right
    "local_model": "",        # Ollama model for the local report; "" = pick from the hardware
    "max_images": 40,         # screenshots sent to Claude for the report
    "max_frames": 70,         # screenshots kept from the video
    "reuse": True,            # reuse transcript/screenshots already made for this video
}


def load():
    cfg = dict(DEFAULTS)
    src = PATH if PATH.exists() or not OLD_PATH.exists() else OLD_PATH
    try:
        cfg.update(json.loads(src.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg["api_key_env"] = True
        cfg["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    return cfg


def save(cfg, remember_key=True):
    data = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    if not remember_key or cfg.get("api_key_env"):
        data["api_key"] = ""
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass
