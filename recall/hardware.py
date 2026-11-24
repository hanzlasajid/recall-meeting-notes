"""Detect CPU / RAM / GPU and recommend the strongest Whisper model the machine can run well."""
import importlib.util
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass
class Hardware:
    os_name: str
    cpu: str
    cores: int
    threads: int
    ram_gb: float
    gpu: str = ""
    vram_gb: float = 0.0
    cuda_ok: bool = False          # faster-whisper can actually use the NVIDIA GPU
    apple_silicon: bool = False
    mlx_ok: bool = False           # mlx-whisper installed (Apple Silicon GPU)

    def lines(self):
        out = [f"System:     {self.os_name}",
               f"Processor:  {self.cpu} ({self.cores} cores / {self.threads} threads)",
               f"Memory:     {self.ram_gb:.0f} GB RAM"]
        if self.gpu:
            usable = "usable for transcription" if (self.cuda_ok or self.mlx_ok) else "not usable (libraries missing)"
            vram = f", {self.vram_gb:.0f} GB" if self.vram_gb else ""
            out.append(f"Graphics:   {self.gpu}{vram} - {usable}")
        else:
            out.append("Graphics:   no supported GPU found - processor only")
        return out


@dataclass
class Choice:
    key: str
    label: str
    backend: str        # "faster-whisper" or "mlx"
    model: str
    device: str         # "cuda", "cpu" or "metal"
    compute_type: str = "default"
    note: str = ""


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
    except Exception:
        return ""


def _cpu_name():
    system = platform.system()
    if system == "Windows":
        name = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
    elif system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    else:
        name = ""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        name = line.split(":", 1)[1]
                        break
        except OSError:
            pass
    return (name or platform.processor() or "Unknown processor").strip().splitlines()[0]


def _nvidia():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return "", 0.0
    out = _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out:
        return "", 0.0
    name, _, mib = out.splitlines()[0].rpartition(",")
    try:
        return name.strip(), float(mib) / 1024
    except ValueError:
        return out.splitlines()[0].strip(), 0.0


def detect() -> Hardware:
    import psutil
    system = platform.system()
    hw = Hardware(
        os_name=f"{'macOS' if system == 'Darwin' else system} {platform.release()} ({platform.machine()})",
        cpu=_cpu_name(),
        cores=psutil.cpu_count(logical=False) or os.cpu_count() or 1,
        threads=psutil.cpu_count(logical=True) or os.cpu_count() or 1,
        ram_gb=psutil.virtual_memory().total / 1024 ** 3,
    )
    if system == "Darwin" and platform.machine() == "arm64":
        hw.apple_silicon = True
        hw.gpu = f"{hw.cpu} integrated GPU (shares {hw.ram_gb:.0f} GB RAM)"
        hw.mlx_ok = importlib.util.find_spec("mlx_whisper") is not None
    else:
        hw.gpu, hw.vram_gb = _nvidia()
        if hw.gpu:
            try:
                from .transcribe import prepare_environment
                prepare_environment()
                import ctranslate2
                hw.cuda_ok = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                hw.cuda_ok = False
    return hw


FW_MODELS = [
    ("large-v3", "best accuracy, slowest"),
    ("large-v3-turbo", "near-best accuracy, much faster"),
    ("medium", "good accuracy"),
    ("small", "fair accuracy, fast"),
    ("base", "rough draft, fastest"),
]
MLX_REPOS = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}


def choices(hw: Hardware):
    """Return (list of Choice, key of the recommended one) for this machine."""
    opts, rec = [], None

    if hw.cuda_ok:
        ct = "float16" if hw.vram_gb >= 4.5 or hw.vram_gb == 0 else "int8_float16"
        for m, note in FW_MODELS:
            opts.append(Choice(f"cuda:{m}", f"{m} on NVIDIA GPU - {note}", "faster-whisper", m, "cuda", ct, note))
        if hw.vram_gb >= 10:
            rec = "cuda:large-v3"
        elif hw.vram_gb >= 2.5 or hw.vram_gb == 0:
            rec = "cuda:large-v3-turbo"
        else:
            rec = "cuda:small"

    if hw.apple_silicon and hw.mlx_ok:
        for m, note in FW_MODELS:
            if m in MLX_REPOS:
                opts.append(Choice(f"mlx:{m}", f"{m} on Apple GPU - {note}", "mlx", MLX_REPOS[m], "metal", note=note))
        if rec is None:
            rec = "mlx:large-v3-turbo" if hw.ram_gb >= 8 else "mlx:small"

    for m, note in FW_MODELS:
        opts.append(Choice(f"cpu:{m}", f"{m} on processor - {note}", "faster-whisper", m, "cpu", "int8", note))
    if rec is None:
        if hw.ram_gb >= 16 and hw.cores >= 8:
            rec = "cpu:medium"
        elif hw.ram_gb >= 8 and hw.cores >= 4:
            rec = "cpu:small"
        else:
            rec = "cpu:base"
    return opts, rec


def explain(hw: Hardware, rec: Choice) -> str:
    if rec.device == "cuda":
        return (f"Your NVIDIA GPU ({hw.vram_gb:.0f} GB) can run '{rec.model}' quickly; "
                "a 45-minute call takes a few minutes.")
    if rec.device == "metal":
        return f"Apple Silicon with {hw.ram_gb:.0f} GB RAM runs '{rec.model.split('/')[-1]}' on the GPU."
    tip = ""
    if hw.gpu and not hw.cuda_ok and not hw.apple_silicon:
        tip = " An NVIDIA GPU was found but can't be used yet - re-run setup to install its libraries."
    return (f"No usable GPU, so '{rec.model}' on the {hw.cores}-core processor is the best balance "
            f"of speed and accuracy.{tip}")
