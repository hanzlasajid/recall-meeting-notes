"""File picker + settings window (Tkinter), with a plain console fallback."""
from pathlib import Path

from . import local_llm
from .analyze import REPORT_MODELS

VIDEO_TYPES = [("Video files", "*.mp4 *.mkv *.mov *.m4v *.webm *.avi *.wmv"),
               ("Audio files", "*.mp3 *.m4a *.wav *.ogg *.flac"), ("All files", "*.*")]


def _bring_forward(w):
    """Started from Terminal (macOS) or a .bat (Windows), the window can open behind them."""
    w.lift()
    w.after(150, w.focus_force)


def _close(root):
    """Let Tk process the close before the long work starts, or the window stays painted on screen."""
    try:
        root.update()
        root.destroy()
    except Exception:
        pass


def _tk():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        root = tk.Tk()
        root.withdraw()
        return tk, ttk, filedialog, messagebox, root
    except Exception:
        return None


def _default_dir():
    for name in ("Videos", "Movies", "Desktop"):          # Windows: Videos, macOS: Movies
        if (Path.home() / name).is_dir():
            return str(Path.home() / name)
    return str(Path.home())


def clean_typed_path(raw: str, windows=None) -> str:
    """Turn a path typed or dragged into a terminal into a plain path.

    Windows drags add quotes ("C:\\a b\\x.mp4"); macOS Terminal escapes spaces (/a\\ b/x.mp4 )."""
    import sys
    p = raw.strip()
    if windows is None:
        windows = sys.platform == "win32"
    if not windows and p and not Path(p).exists():
        import shlex
        try:
            parts = shlex.split(p)
            if len(parts) == 1:
                return parts[0]
        except ValueError:
            pass
    return p.strip('"\'')


def pick_video(start_dir=None):
    t = _tk()
    if t is None:
        p = clean_typed_path(input("Path of the video file (drag it into this window, then press Enter): "))
        return Path(p) if p else None
    tk, ttk, filedialog, messagebox, root = t
    root.attributes("-topmost", True)
    _bring_forward(root)
    p = filedialog.askopenfilename(title="Choose a meeting recording", filetypes=VIDEO_TYPES,
                                   initialdir=start_dir or _default_dir())
    _close(root)
    return Path(p) if p else None


def _no_key_question(local_model):
    need = local_llm.missing(local_model)
    extra = (" It needs a one-time install of " + " and ".join(need) + ".") if need else ""
    return ("No Anthropic API key, so Claude can't write the report.\n\n"
            f"Write it with a local AI model on this computer instead? Free and private, "
            f"but slower and less detailed than Claude.{extra}")


def _install_question(local_model):
    need = local_llm.missing(local_model)
    return ("To write the report on this computer, Recall will install:\n- " + "\n- ".join(need)
            + "\n\nThis happens only once.") if need else ""


def settings(video: Path, hw, opts, rec_key, cfg, has_outputs, local_model=None):
    """Show hardware + recommendation and let the user adjust. Returns dict or None if cancelled."""
    local_model = local_model or local_llm.recommend(hw)
    t = _tk()
    if t is None:
        return _settings_console(video, hw, opts, rec_key, cfg, has_outputs, local_model)
    tk, ttk, filedialog, messagebox, root = t
    from .hardware import explain
    by_key = {o.key: o for o in opts}
    result = {}

    win = tk.Toplevel(root)
    win.title("Recall")
    win.resizable(False, False)
    win.attributes("-topmost", True)
    _bring_forward(win)
    f = ttk.Frame(win, padding=16)
    f.grid()
    row = 0

    def label(text, bold=False, wrap=520, pad=(0, 2)):
        nonlocal row
        ttk.Label(f, text=text, wraplength=wrap, font=("TkDefaultFont", 10, "bold") if bold else None
                  ).grid(row=row, column=0, columnspan=2, sticky="w", pady=pad)
        row += 1

    label(f"Recording: {video.name}", bold=True, pad=(0, 8))
    label("This computer", bold=True)
    for line in hw.lines():
        label(line)
    label(explain(hw, by_key[rec_key]), pad=(4, 12))

    label("Transcription model (recommended one is preselected)", bold=True)
    labels = [o.label + ("   (recommended)" if o.key == rec_key else "") for o in opts]
    model_var = tk.StringVar(value=labels[[o.key for o in opts].index(rec_key)])
    ttk.Combobox(f, textvariable=model_var, values=labels, state="readonly", width=70
                 ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
    row += 1

    label("Language (empty = detect automatically, e.g. en, de)")
    lang_var = tk.StringVar(value=cfg.get("language", ""))
    ttk.Entry(f, textvariable=lang_var, width=12).grid(row=row, column=0, sticky="w", pady=(0, 8))
    row += 1
    label("Names and terms to spell correctly (optional, comma-separated)")
    vocab_var = tk.StringVar(value=cfg.get("vocabulary", ""))
    ttk.Entry(f, textvariable=vocab_var, width=72).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 12))
    row += 1

    label("Meeting report", bold=True)
    rep_labels = {k: v[1] for k, v in REPORT_MODELS.items()}
    rep_var = tk.StringVar(value=rep_labels.get(cfg.get("report_model", "sonnet"), rep_labels["sonnet"]))
    ttk.Combobox(f, textvariable=rep_var, values=list(rep_labels.values()), state="readonly", width=70
                 ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
    row += 1
    label(f"Local AI for this computer: {local_llm.describe(local_model)}", pad=(0, 6))
    key_note = "(from ANTHROPIC_API_KEY)" if cfg.get("api_key_env") else "(console.anthropic.com > API keys)"
    label(f"Anthropic API key {key_note}")
    key_var = tk.StringVar(value=cfg.get("api_key", ""))
    ttk.Entry(f, textvariable=key_var, width=72, show="•").grid(row=row, column=0, columnspan=2, sticky="w")
    row += 1
    remember_var = tk.BooleanVar(value=bool(cfg.get("api_key")) and not cfg.get("api_key_env"))
    ttk.Checkbutton(f, text="Remember the key on this computer", variable=remember_var
                    ).grid(row=row, column=0, sticky="w", pady=(2, 8))
    row += 1
    reuse_var = tk.BooleanVar(value=cfg.get("reuse", True) and has_outputs)
    if has_outputs:
        ttk.Checkbutton(f, text="Reuse the transcript and screenshots already made for this recording",
                        variable=reuse_var).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        row += 1

    def start():
        choice = opts[labels.index(model_var.get())]
        rep_key = next(k for k, v in rep_labels.items() if v == rep_var.get())
        if rep_key in ("sonnet", "opus") and not key_var.get().strip():
            ans = messagebox.askyesnocancel(
                "No API key", _no_key_question(local_model) + "\n\nYes: use the local AI.\n"
                "No: skip the report and only save a prompt file you can paste into Claude.\n"
                "Cancel: go back and enter a key.", parent=win)
            if ans is None:
                return
            rep_key = "local" if ans else "none"
        elif rep_key == "local" and (q := _install_question(local_model)):
            if not messagebox.askokcancel("Install local AI", q + " Continue?", parent=win):
                return
        result.update(choice=choice, language=lang_var.get().strip(), vocabulary=vocab_var.get().strip(),
                      report_model=rep_key, api_key=key_var.get().strip(), remember=remember_var.get(),
                      reuse=bool(reuse_var.get()) and has_outputs)
        win.destroy()

    btns = ttk.Frame(f)
    btns.grid(row=row, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(btns, text="Cancel", command=win.destroy).grid(row=0, column=0, padx=4)
    ttk.Button(btns, text="Start", command=start).grid(row=0, column=1)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.wait_window()
    _close(root)
    return result or None


def _yes(question):
    return input(question + " [Y/n]: ").strip().lower()[:1] != "n"


def _settings_console(video, hw, opts, rec_key, cfg, has_outputs, local_model):
    from .hardware import explain
    by_key = {o.key: o for o in opts}
    print(f"\nRecording: {video.name}\n")
    print("\n".join(hw.lines()))
    print("\n" + explain(hw, by_key[rec_key]) + "\n")
    for i, o in enumerate(opts, 1):
        print(f"  {i:2}. {o.label}{'   <- recommended' if o.key == rec_key else ''}")
    a = input("Model number (Enter = recommended): ").strip()
    choice = opts[int(a) - 1] if a.isdigit() and 0 < int(a) <= len(opts) else by_key[rec_key]
    print(f"\nLocal AI for this computer: {local_llm.describe(local_model)}")
    rep = input("Report: [s]onnet (default), [o]pus, [l]ocal AI, [n]one: ").strip().lower()[:1]
    rep_key = {"o": "opus", "l": "local", "n": "none"}.get(rep, "sonnet")
    key = cfg.get("api_key", "")
    if rep_key in ("sonnet", "opus") and not key:
        key = input("Anthropic API key (Enter = no key): ").strip()
        if not key:
            rep_key = "local" if _yes(_no_key_question(local_model).replace("\n\n", "\n")) else "none"
    elif rep_key == "local" and (q := _install_question(local_model)):
        if not _yes(q + " Continue?"):
            rep_key = "none"
    reuse = has_outputs and input("Reuse existing transcript/screenshots? [Y/n]: ").strip().lower() != "n"
    return dict(choice=choice, language=cfg.get("language", ""), vocabulary=cfg.get("vocabulary", ""),
                report_model=rep_key, api_key=key, remember=False, reuse=reuse)


def done(message, folder: Path, report: Path = None):
    print("\n" + message)
    import os
    import subprocess
    import sys
    target = report if report and report.exists() else folder
    try:
        if sys.platform == "win32":
            os.startfile(target)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)])
    except Exception:
        pass
