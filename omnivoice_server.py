# -*- coding: utf-8 -*-
"""OmniVoice 합성 서버 — GPU 있는 곳(코랩 T4 등)에서 띄우고, GPU 없는 PC 의 CLI 가 부른다.

    python omnivoice_server.py --tunnel                 # 코랩: 임시 공개 주소 + 비밀번호 출력
    python omnivoice_server.py --port 8765 --token abc  # 같은 네트워크에서만

PC 쪽:
    omnivoice say "안녕하세요" -r voice_01.wav --server <주소> --token <비밀번호>

API (모두 Authorization: Bearer <token> 필요)
    GET  /health  → {"ok": true, "device": "..."}
    POST /tts     {text, ref_name, ref_b64, ref_text?, speed?, steps?} → audio/wav (24kHz)

레퍼런스 wav 는 요청마다 같이 오지만, 해시로 캐시해서 목소리 등록(Whisper)은 처음 한 번만 한다.
GPU 하나를 나눠 쓰므로 합성은 한 번에 하나씩 처리한다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import omnivoice_cli as cli

MAX_BODY = 30 * 1024 * 1024   # 레퍼런스 wav + 텍스트
MAX_TEXT = 5000               # 한 요청 글자 수 (긴 원고는 batch 로 줄 단위)
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"


class State:
    model = None
    device = "?"
    token = ""
    lock = threading.Lock()
    prompts: dict = {}


def get_prompt(ref_name: str, ref_bytes: bytes, ref_text: str):
    key = hashlib.sha1(ref_bytes + ref_text.encode("utf-8")).hexdigest()
    if key not in State.prompts:
        ref_dir = cli.CACHE / "server_refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".pt" if ref_name.lower().endswith(".pt") else ".wav"
        ref_p = ref_dir / f"{Path(ref_name).stem}_{key[:12]}{suffix}"
        if not ref_p.is_file():
            ref_p.write_bytes(ref_bytes)
        State.prompts[key] = cli.make_prompt(State.model, ref_p, ref_text or None)
    return State.prompts[key]


class Handler(BaseHTTPRequestHandler):
    server_version = "omnivoice-server"

    def log_message(self, fmt, *args):  # 접속 로그 대신 합성 로그만
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authorized(self) -> bool:
        got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if hmac.compare_digest(got, State.token):
            return True
        self._json(401, {"error": "토큰이 틀렸습니다"})
        return False

    def do_GET(self):
        if self.path != "/health":
            return self._json(404, {"error": "not found"})
        if self._authorized():
            self._json(200, {"ok": True, "device": State.device})

    def do_POST(self):
        if self.path != "/tts":
            return self._json(404, {"error": "not found"})
        if not self._authorized():
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {"error": "요청이 너무 큽니다"})
        try:
            req = json.loads(self.rfile.read(n))
            text = (req.get("text") or "").strip()
            if not text or len(text) > MAX_TEXT:
                return self._json(400, {"error": f"text 는 1~{MAX_TEXT}자"})
            ref_bytes = base64.b64decode(req["ref_b64"])
            speed = float(req.get("speed") or 1.0)
            steps = int(req.get("steps") or 32)
            t0 = time.time()
            with State.lock:
                prompt = get_prompt(req.get("ref_name") or "ref.wav", ref_bytes, req.get("ref_text") or "")
                wav = cli.synth(State.model, prompt, text, speed, steps)
            import soundfile as sf
            buf = io.BytesIO()
            sf.write(buf, wav, cli.SR, format="WAV", subtype="PCM_16")
            cli.log(f"합성 {len(wav) / cli.SR:.1f}초 ({time.time() - t0:.1f}초 걸림) {text[:30]}")
            self._send(200, buf.getvalue(), "audio/wav")
        except Exception as e:  # noqa: BLE001
            cli.log(f"오류: {type(e).__name__}: {e}")
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def find_cloudflared(given: str | None = None) -> str:
    if given:
        return given
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    if platform.system() != "Linux":
        sys.exit("cloudflared 가 없습니다. https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ 에서 받아 PATH 에 두세요.")
    dst = cli.CACHE / "cloudflared"
    if not dst.is_file():
        cli.log("cloudflared 내려받는 중…")
        dst.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(CLOUDFLARED_URL, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    return str(dst)


def start_tunnel(port: int, cloudflared: str | None = None) -> str:
    """cloudflared 무료 임시 터널 — 계정 없이 https://….trycloudflare.com 주소가 생긴다."""
    proc = subprocess.Popen([find_cloudflared(cloudflared), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    pat = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")
    deadline = time.time() + 60
    for line in proc.stderr:  # type: ignore[union-attr]
        m = pat.search(line)
        if m:
            # 남은 로그는 버린다(파이프가 차서 터널이 멈추지 않게)
            threading.Thread(target=lambda: [None for _ in proc.stderr], daemon=True).start()
            return m.group(0)
        if time.time() > deadline:
            break
    sys.exit("터널 주소를 받지 못했습니다. 잠시 후 다시 실행하세요.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="OmniVoice 합성 서버")
    ap.add_argument("--host", default="127.0.0.1", help="듣는 주소 (같은 네트워크에 열려면 0.0.0.0)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default=os.environ.get("OMNIVOICE_TOKEN"), help="비밀번호 (생략 시 자동 생성)")
    ap.add_argument("--tunnel", action="store_true", help="cloudflared 임시 공개 주소 만들기 (코랩용)")
    ap.add_argument("--cloudflared", help="cloudflared 실행파일 경로 (PATH 에 없을 때)")
    ap.add_argument("-d", "--device", default="auto", choices=["auto", "cuda", "xpu", "mps", "cpu"])
    args = ap.parse_args()

    State.token = args.token or secrets.token_urlsafe(9)
    cli.DEVICE = args.device
    State.device = cli.resolve_device(args.device)
    State.model = cli.load_model(need_asr=True)   # 어떤 레퍼런스가 와도 받아쓸 수 있게

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = start_tunnel(args.port, args.cloudflared) if args.tunnel else f"http://{args.host}:{args.port}"

    bar = "=" * 70
    print(f"\n{bar}\n  OmniVoice 서버 준비됨 ({State.device})\n"
          f"  주소     : {url}\n  비밀번호 : {State.token}\n\n"
          f"  PC 에서:\n  omnivoice say \"안녕하세요\" -r voice_01.wav --server {url} --token {State.token}\n"
          f"\n  이 셀(프로그램)을 멈추면 서버도 꺼집니다.\n{bar}\n", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
