"""Write the report with a local vision model through Ollama (no API key, nothing leaves the computer).

Works the same on Windows and macOS: Ollama is installed with winget (Windows) or Homebrew (macOS),
its server is started if needed, the model is pulled once, then the report is written over
Ollama's local HTTP API (http://127.0.0.1:11434). Only the standard library is used.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not HOST.startswith("http"):
    HOST = "http://" + HOST
DOWNLOAD_PAGE = "https://ollama.com/download"

# Vision models, smallest to largest. Download sizes from ollama.com/library (Nov 2026).
MODELS = {
    "qwen3-vl:2b-instruct": (1.9, "basic - for machines with little memory"),
    "qwen3-vl:4b-instruct": (3.3, "fair"),
    "qwen3-vl:8b-instruct": (6.2, "good"),
    "qwen3-vl:30b-a3b-instruct": (20.0, "very good - needs a lot of memory"),
}
IMAGES = {"2b": 6, "4b": 8, "8b": 12, "30b": 16}      # screenshots sent, by model size


def recommend(hw) -> str:
    """Pick the strongest model that runs well on this machine."""
    if hw.apple_silicon:                                   # unified memory, GPU can use about 70 %
        usable = hw.ram_gb * 0.7
        if usable >= 28:
            return "qwen3-vl:30b-a3b-instruct"
        if usable >= 10:
            return "qwen3-vl:8b-instruct"
        return "qwen3-vl:4b-instruct" if usable >= 5 else "qwen3-vl:2b-instruct"
    if hw.gpu and hw.vram_gb:                              # NVIDIA: Ollama brings its own CUDA runtime
        if hw.vram_gb >= 24:
            return "qwen3-vl:30b-a3b-instruct"
        if hw.vram_gb >= 6 and hw.ram_gb >= 16:            # spills the rest into RAM
            return "qwen3-vl:8b-instruct"
        if hw.vram_gb >= 4:
            return "qwen3-vl:4b-instruct"
    return "qwen3-vl:4b-instruct" if hw.ram_gb >= 16 else "qwen3-vl:2b-instruct"   # processor only


def describe(model: str) -> str:
    gb, quality = MODELS.get(model, (0, ""))
    return f"{model} ({gb:g} GB download, {quality})" if gb else model


# ---------------------------------------------------------------- Ollama install / server

def find_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    if sys.platform == "win32":
        cands = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                 Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"]
    else:
        cands = [Path("/opt/homebrew/bin/ollama"), Path("/usr/local/bin/ollama"),
                 Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    return next((str(p) for p in cands if p.is_file()), None)


def _api(path, body=None, timeout=10):
    req = urllib.request.Request(HOST + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def running() -> bool:
    try:
        with _api("/api/version", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def installed_models():
    try:
        with _api("/api/tags") as r:
            return {m["name"] for m in json.load(r).get("models", [])}
    except (urllib.error.URLError, OSError, ValueError):
        return set()


def _on_disk(model):
    """True if the model was downloaded before (works while Ollama is not running)."""
    root = Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")
    name, _, tag = model.partition(":")
    return (root / "manifests" / "registry.ollama.ai" / "library" / name / (tag or "latest")).is_file()


def missing(model):
    """What still has to be installed or downloaded for `model`: a list of short descriptions."""
    need = []
    up = running()
    if not up and not find_exe():
        need.append("Ollama (the free app that runs local AI models)")
    if not (model in installed_models() if up else _on_disk(model)):
        need.append(f"the model {describe(model)}")
    return need


def _install(log):
    if sys.platform == "win32":
        if not shutil.which("winget"):
            return False
        log("Installing Ollama with winget...")
        r = subprocess.run(["winget", "install", "-e", "--id", "Ollama.Ollama", "--silent",
                            "--accept-package-agreements", "--accept-source-agreements"],
                           stdin=subprocess.DEVNULL)
        return r.returncode == 0 or find_exe() is not None
    if sys.platform == "darwin":
        brew = shutil.which("brew") or next((b for b in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
                                             if Path(b).exists()), None)
        if not brew:
            return False
        log("Installing the Ollama app with Homebrew...")
        env = dict(os.environ, HOMEBREW_NO_ASK="1", HOMEBREW_NO_AUTO_UPDATE="1")   # Homebrew 7 asks y/n
        return subprocess.run([brew, "install", "--cask", "ollama-app"], env=env,
                              stdin=subprocess.DEVNULL).returncode == 0
    return False


def start(log):
    """Install Ollama if needed and make sure its server runs. Returns the server we started (or None)."""
    if running():
        return None
    exe = find_exe()
    if not exe:
        if not _install(log) or not (exe := find_exe()):
            raise RuntimeError(f"Could not install Ollama automatically. Install it from {DOWNLOAD_PAGE}, "
                               "then run Recall again.")
    if running():                     # the Windows installer starts Ollama by itself
        return None
    log("Starting Ollama...")
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if sys.platform == "win32" else 0
    proc = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=flags, start_new_session=sys.platform != "win32")
    for _ in range(60):
        if running():
            return proc
        time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Ollama did not start. Open the Ollama app once, then run Recall again.")


def pull(model, log):
    if model in installed_models():
        return
    log(f"Downloading {describe(model)} - only the first time...")
    with _api("/api/pull", {"model": model, "stream": True}, timeout=None) as r:
        last = ""
        for line in r:
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(f"Ollama could not download {model}: {msg['error']}")
            if msg.get("total"):
                pct = 100 * msg.get("completed", 0) / msg["total"]
                text = f"  {msg['status'][:30]}: {pct:5.1f}% of {msg['total'] / 1e9:.1f} GB"
            else:
                text = f"  {msg.get('status', '')}"
            if text != last:
                print("\r" + text.ljust(60), end="", flush=True)
                last = text
    print()


# ---------------------------------------------------------------- report

def run_local(out_dir: Path, facts, transcript_txt, frames, model, log=print) -> str:
    from . import analyze
    server = start(log)
    try:
        pull(model, log)
        size = next((k for k in IMAGES if f":{k}" in model), "8b")
        chosen = analyze._pick(frames, IMAGES[size])
        images = [analyze._image_b64(out_dir / f["file"], width=1024) for f in chosen
                  if (out_dir / f["file"]).exists()]
        user = analyze.build_user_text(facts, transcript_txt, chosen)
        system = analyze.PROMPT_FILE.read_text(encoding="utf-8")
        est = (len(system) + len(user)) / 3.5 + 1000 * len(images) + 8000    # prompt + images + answer
        num_ctx = int(min(65536, max(16384, -(-est // 4096) * 4096)))
        log(f"Writing the report on this computer with {model} ({len(images)} screenshots). "
            "This can take several minutes...")
        body = {"model": model, "stream": True, "keep_alive": "2m",
                "options": {"num_ctx": num_ctx, "temperature": 0.3},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user, "images": images}]}
        parts, chars, stats = [], 0, {}
        with _api("/api/chat", body, timeout=None) as r:
            for line in r:
                msg = json.loads(line)
                if msg.get("error"):
                    raise RuntimeError(f"Local model error: {msg['error']}")
                piece = msg.get("message", {}).get("content", "")
                parts.append(piece)
                chars += len(piece)
                if piece and chars % 1000 < len(piece):
                    print(f"\r  writing report... {chars:,} characters", end="", flush=True)
                if msg.get("done"):
                    stats = msg
        print()
        text = "".join(parts).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        secs = stats.get("total_duration", 0) / 1e9
        log(f"Report written locally ({stats.get('prompt_eval_count', 0):,} tokens in, "
            f"{stats.get('eval_count', 0):,} out, {secs / 60:.1f} min).")
        return text
    finally:
        if server:                                  # we started Ollama, so stop it again to free memory
            server.terminate()

