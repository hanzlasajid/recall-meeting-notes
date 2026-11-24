"""Offline tests: no GPU, no video, no API key needed.  Run:  python tests/run_tests.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE = Path(__file__).resolve().parent / "fake_anthropic_pkg"
sys.path[:0] = [str(FAKE), str(ROOT)]

from recall import analyze, hardware, render, transcribe          # noqa: E402
from recall.hardware import Hardware                              # noqa: E402

failures = 0


def check(name, cond, detail=""):
    global failures
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    failures += 0 if cond else 1


def test_recommendations():
    cases = {
        "cuda:large-v3-turbo": Hardware("Windows", "Core Ultra 7", 16, 16, 31.5, "RTX PRO 1000", 8.0, True),
        "cuda:large-v3": Hardware("Windows", "i9", 24, 32, 64, "RTX 4080", 12.0, True),
        "cpu:small": Hardware("Windows", "i5", 4, 8, 8, "", 0, False),
        "cpu:medium": Hardware("Windows", "i7", 8, 16, 16, "RTX 3060", 6, False),   # GPU but no CUDA libs
        "mlx:large-v3-turbo": Hardware("macOS", "Apple M2 Pro", 10, 10, 16, "M2 GPU", 0, False, True, True),
        "cpu:base": Hardware("Linux", "Xeon", 2, 2, 4, "", 0, False),
    }
    for want, hw in cases.items():
        opts, rec = hardware.choices(hw)
        check(f"recommend {want}", rec == want, rec)
        check(f"  {want}: CPU fallbacks listed", any(o.device == "cpu" for o in opts))


def test_cues():
    S, W = transcribe.Segment, transcribe.Word
    words = [W(f" word{i}", i * 0.3, i * 0.3 + 0.25) for i in range(40)]
    cues = transcribe.build_cues([S(0, 12, "x", words), S(12, 14, "No word timings.", [])])
    check("cues: max 2 lines", all(t.count("\n") <= 1 for _, _, t in cues))
    check("cues: max 6 s", all(b - a <= 6.01 for a, b, _ in cues))
    check("cues: segment without words kept", cues[-1][2] == "No word timings.")


def _fixture(tmp: Path):
    from PIL import Image
    video = tmp / "call.mp4"
    video.write_bytes(b"not a real video")
    out = tmp / "call_notes"
    (out / "frames").mkdir(parents=True)
    frames, segs = [], []
    for i in range(50):
        name = f"frames/f{i + 1:03}_00-{i // 60:02}-{i % 60:02}.jpg"
        Image.new("RGB", (1600, 900), (40 * (i % 6), 90, 160)).save(out / name)
        frames.append({"file": name, "start": f"00:00:{i:02}", "start_s": i, "end": "end", "said": f"line {i}"})
        segs.append({"start": i * 10, "end": i * 10 + 5, "text": f"Sentence number {i}.", "words": []})
    (out / "frames" / "f003_00-00-02.jpg").unlink()            # user deleted a private screenshot
    (out / "frames.json").write_text(json.dumps(frames))
    (out / "transcript.json").write_text(json.dumps({"duration": 500, "segments": segs}))
    (out / "transcript.txt").write_text("\n".join(f"[00:00:{i:02}] Sentence number {i}." for i in range(50)))
    return video, out


def test_report_path():
    with tempfile.TemporaryDirectory() as d:
        video, out = _fixture(Path(d))
        frames = json.loads((out / "frames.json").read_text())
        facts = analyze.meeting_facts(video, 500)
        txt = (out / "transcript.txt").read_text()
        p = analyze.write_manual_prompt(out, facts, txt, frames)
        check("manual prompt contains the format spec", "## Output format" in p.read_text(encoding="utf-8"))
        md = analyze.run_claude(out, facts, txt, frames, "sk-test", "sonnet", max_images=40, log=lambda *_: None)
        import anthropic
        req = anthropic.LAST
        n_img = sum(1 for c in req["messages"][0]["content"] if c["type"] == "image")
        check("report: model id", req["model"] == "claude-sonnet-5-5", req["model"])
        check("report: at most 40 images", n_img <= 40, n_img)
        html = render.to_html(md, out)
        check("html: mermaid", 'class="mermaid"' in html)
        check("html: task boxes", 'type="checkbox"' in html)
        check("html: tables", "<table>" in html)


def test_cli_reuse():
    with tempfile.TemporaryDirectory() as d:
        video, out = _fixture(Path(d))
        env = dict(os.environ, ANTHROPIC_API_KEY="sk-test", HOME=d, USERPROFILE=d,
                   PYTHONPATH=os.pathsep.join([str(FAKE), str(ROOT)]))
        r = subprocess.run([sys.executable, "-m", "recall", str(video), "--no-gui", "--report", "sonnet"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        check("cli: exit code 0", r.returncode == 0, r.stdout[-500:] + r.stderr[-500:])
        check("cli: report.html written", (out / "report.html").exists())
        prompt = (out / "analysis_prompt.md").read_text(encoding="utf-8")
        check("cli: deleted screenshot left out", "f003_00-00-02" not in prompt)


def test_local_recommendations():
    from recall import local_llm
    cases = {
        "qwen3-vl:8b-instruct": Hardware("Windows", "Core Ultra 7", 16, 16, 31.5, "RTX PRO 1000", 8.0, True),
        "qwen3-vl:30b-a3b-instruct": Hardware("Windows", "i9", 24, 32, 64, "RTX 4090", 24.0, True),
        "qwen3-vl:2b-instruct": Hardware("Windows", "i5", 4, 8, 8, "", 0, False),
        "qwen3-vl:4b-instruct": Hardware("Windows", "i7", 8, 16, 16, "", 0, False),
    }
    m4 = Hardware("macOS", "Apple M4 Pro", 14, 14, 24, apple_silicon=True)
    air = Hardware("macOS", "Apple M1", 8, 8, 8, apple_silicon=True)
    big = Hardware("macOS", "Apple M4 Max", 16, 16, 64, apple_silicon=True)
    cases.update({"qwen3-vl:8b-instruct ": m4, "qwen3-vl:4b-instruct ": air, "qwen3-vl:30b-a3b-instruct ": big})
    for want, hw in cases.items():
        got = local_llm.recommend(hw)
        check(f"local model {hw.cpu} {hw.ram_gb:g} GB -> {want.strip()}", got == want.strip(), got)
        check(f"  {got} is a known model", got in local_llm.MODELS)


class _FakeOllama:
    """A tiny stand-in for Ollama's HTTP API on a random local port."""
    REPORT = ("# Call\n\n## Summary\nA call.\n\n```mermaid\ngraph LR\nA-->B\n```\n\n"
              "## Action items\n- [ ] Do it (00:01)\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")

    def __enter__(self):
        import http.server
        import threading
        outer = self
        self.chats = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, lines):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for obj in lines:
                    self.wfile.write((json.dumps(obj) + "\n").encode())

            def do_GET(self):
                if self.path == "/api/version":
                    self._send([{"version": "0.40.16"}])
                else:
                    self._send([{"models": [{"name": m} for m in outer.models]}])

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/chat":
                    outer.chats.append(body)
                    rep = outer.REPORT
                    self._send([{"message": {"content": rep[:40]}}, {"message": {"content": rep[40:]}},
                                {"done": True, "prompt_eval_count": 1234, "eval_count": 56,
                                 "total_duration": 3e9}])
                else:
                    self._send([{"status": "success"}])

        self.models = {"qwen3-vl:8b-instruct"}
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        return self

    def __exit__(self, *a):
        self.srv.shutdown()


def test_local_report():
    from recall import local_llm
    with tempfile.TemporaryDirectory() as d, _FakeOllama() as fake:
        video, out = _fixture(Path(d))
        old, local_llm.HOST = local_llm.HOST, fake.url
        try:
            check("local: Ollama seen as running", local_llm.running())
            check("local: nothing to install", local_llm.missing("qwen3-vl:8b-instruct") == [])
            check("local: other model must be downloaded", len(local_llm.missing("qwen3-vl:2b-instruct")) == 1)
            frames = [f for f in json.loads((out / "frames.json").read_text()) if (out / f["file"]).exists()]
            md = local_llm.run_local(out, analyze.meeting_facts(video, 500), (out / "transcript.txt").read_text(),
                                     frames, "qwen3-vl:8b-instruct", log=lambda *_: None)
        finally:
            local_llm.HOST = old
        req = fake.chats[-1]
        check("local: model sent", req["model"] == "qwen3-vl:8b-instruct")
        check("local: format spec as system prompt", "## Output format" in req["messages"][0]["content"])
        check("local: 12 screenshots for an 8b model", len(req["messages"][1]["images"]) == 12,
              len(req["messages"][1]["images"]))
        check("local: context window set", req["options"]["num_ctx"] >= 16384)
        html = render.to_html(md, out)
        check("local: html has mermaid and tasks", 'class="mermaid"' in html and 'type="checkbox"' in html)

        env = dict(os.environ, HOME=d, USERPROFILE=d, OLLAMA_HOST=fake.url,
                   PYTHONPATH=os.pathsep.join([str(FAKE), str(ROOT)]))
        env.pop("ANTHROPIC_API_KEY", None)
        r = subprocess.run([sys.executable, "-m", "recall", str(video), "--no-gui"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        check("cli no key: hints at --report local", "--report local" in r.stdout, r.stdout[-400:])
        check("cli no key: no report written", not (out / "report.html").exists())
        r = subprocess.run([sys.executable, "-m", "recall", str(video), "--no-gui", "--report", "local"],
                           cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        check("cli --report local: exit 0", r.returncode == 0, r.stdout[-500:] + r.stderr[-500:])
        check("cli --report local: report.html written", (out / "report.html").exists(), r.stdout[-500:])


def test_typed_paths():
    from recall.ui import clean_typed_path
    cases = [
        ("/Users/a/Movies/test\\ call.mp4 ", False, "/Users/a/Movies/test call.mp4"),   # macOS Terminal drag
        ("'/Users/a/Movies/test call.mp4'", False, "/Users/a/Movies/test call.mp4"),
        ("/Users/a/Movies/plain.mp4", False, "/Users/a/Movies/plain.mp4"),
        ('"C:\\Users\\first last\\Videos\\x.mp4"', True, "C:\\Users\\first last\\Videos\\x.mp4"),
        ("C:\\Users\\a\\Videos\\x.mp4", True, "C:\\Users\\a\\Videos\\x.mp4"),
    ]
    for raw, win, want in cases:
        got = clean_typed_path(raw, windows=win)
        check(f"typed path: {raw!r}", got == want, f"got {got!r}")


if __name__ == "__main__":
    for t in (test_recommendations, test_cues, test_report_path, test_cli_reuse, test_typed_paths,
              test_local_recommendations, test_local_report):
        print(f"\n== {t.__name__}")
        t()
    print(f"\n{'All tests passed.' if not failures else f'{failures} failed.'}")
    sys.exit(1 if failures else 0)
