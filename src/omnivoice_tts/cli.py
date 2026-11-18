"""omnivoice-tts 명령 (= python -m omnivoice_tts)."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import settings as settings_module

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="OmniVoice TTS — 이 PC 의 목소리로 음성 + 자막(SRT) · 발음 본사전 · HTTP API")
voices_app = typer.Typer(help="목소리 등록부 (voices/<코드>/)")
dict_app = typer.Typer(help="발음 본사전 · 앱 사전 [업데이트]/[다운받기]")
app.add_typer(voices_app, name="voices")
app.add_typer(dict_app, name="dict")
console = Console()


@app.command()
def synth(
    text: str = typer.Argument(..., help="읽을 글. [laughter] 같은 표현 태그를 넣을 수 있다"),
    voice: str = typer.Option(None, "--voice", "-v", help="목소리 코드 (기본 W1)"),
    out: Path = typer.Option(Path("synth.wav"), "--out", "-o", help="출력 wav"),
    speed: float = typer.Option(None, "--speed", help="말 빠르기 (기본: 목소리 설정 → 1.0)"),
    steps: int = typer.Option(None, "--steps", help="생성 스텝 (기본: 목소리 설정 → 32)"),
    lang: str = typer.Option(None, "--lang", help="언어 (기본 자동)"),
):
    """글 한 덩어리 → wav 하나."""
    from .audio_io import write_wav
    from .engine import Engine

    with console.status("모델 준비 중…"):
        eng = Engine.get_sync()
    with console.status(f"합성 중 ({eng.device_name})…"):
        wav, m = eng.synth_sync(text, voice_code=voice, speed=speed, steps=steps, lang=lang)
    write_wav(out, wav, eng.sample_rate)
    console.print(f"[green]저장[/green] {out}  {m['voice']} · {m['duration_seconds']:.1f}초 음성 · "
                  f"생성 {m['synth_seconds']:.1f}초 (×{m['rtf']}) · speed {m['speed']} · steps {m['steps']}")


@app.command()
def batch(
    script_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="대본 JSON (ch{NN}_script.json)"),
    chapter: str = typer.Option(None, "--chapter", help="챕터 번호 지정 (예: 05)"),
    output_root: Path = typer.Option(None, "--output-root", help="기본 ./workspace"),
    voice: str = typer.Option(None, "--voice", "-v", help="모든 장면을 이 목소리로"),
    speed: float = typer.Option(None, "--speed"),
    steps: int = typer.Option(None, "--steps"),
):
    """대본 JSON → 장면별 wav + SRT, 장 전체 SRT."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    from .batch import parse_script, run_batch
    from .engine import Engine

    script = parse_script(script_path.read_bytes())
    with console.status("모델 준비 중…"):
        eng = Engine.get_sync()

    async def _run():
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(),
                      console=console) as progress:
            tid = progress.add_task(f"합성 중 ({eng.device_name})", total=len(script.scenes))

            async def cb(done: int, total: int, current: int | None):
                progress.update(tid, completed=done, description=f"장면 {current} ({done}/{total})")

            return await run_batch(engine=eng, script=script, chapter_id_explicit=chapter,
                                   filename_hint=script_path.name, output_root=output_root,
                                   voice_override=voice, speed=speed, steps=steps, on_progress=cb)

    res = asyncio.run(_run())
    console.print(f"[green]완료[/green] ch{res.chapter_id} · {len(res.files)}개 → {res.output_dir}")
    for w in res.warnings:
        console.print(f"[yellow]경고[/yellow] {w}")


# ---------------------------------------------------------------- 목소리

@voices_app.callback(invoke_without_command=True)
def voices_list(ctx: typer.Context):
    """등록된 목소리 목록."""
    if ctx.invoked_subcommand:
        return
    from .voices import list_voices

    s = settings_module.load()
    t = Table(title=f"목소리 ({s.voices_dir})")
    for c in ("코드", "이름", "성별", "speed", "steps", "기준 녹음", "받아쓰기", "메모"):
        t.add_column(c)
    for v in list_voices(s.voices_dir):
        t.add_row(v.code + (" ★" if v.code == s.default_voice else ""), v.name, v.gender,
                  str(v.speed or "-"), str(v.steps or "-"),
                  ("[green]" if v.ok else "[red]없음 ") + str(v.ref_audio) + ("[/green]" if v.ok else "[/red]"),
                  "직접 적음" if v.ref_text else "Whisper", v.memo)
    console.print(t)


@voices_app.command("add")
def voices_add(
    code: str = typer.Argument(..., help="새 목소리 코드 (예: W2)"),
    wav: Path = typer.Argument(..., exists=True, dir_okay=False, help="3~10초 기준 녹음 wav"),
    name: str = typer.Option("", "--name"),
    gender: str = typer.Option("", "--gender", help="여 / 남"),
    ref_text: str = typer.Option("", "--ref-text", help="녹음에서 실제로 말한 문장 (비우면 Whisper)"),
    speed: float = typer.Option(None, "--speed"),
    steps: int = typer.Option(None, "--steps"),
    memo: str = typer.Option("", "--memo"),
):
    """voices/<코드>/ 폴더를 만들어 새 목소리를 등록한다."""
    from .voices import add_voice

    v = add_voice(settings_module.load().voices_dir, code, wav, name=name, gender=gender,
                  ref_text=ref_text, speed=speed, steps=steps, memo=memo)
    console.print(f"[green]등록[/green] {v.code} → {v.folder}\n"
                  f"  들어 보기: omnivoice-tts synth \"안녕하세요\" -v {v.code} -o {v.code}.wav")


# ---------------------------------------------------------------- 발음 사전

@dict_app.command("status")
def dict_status():
    """연결된 앱 사전들과 본사전의 차이."""
    from . import dictsync

    console.print(f"본사전: {dictsync.master_path()} ({len(dictsync.read_master().rules)}개)")
    t = Table()
    for c in ("id", "이름", "올릴 것", "지운 것", "충돌", "받을 것", "경로"):
        t.add_column(c)
    for st in dictsync.all_status():
        if "error" in st:
            t.add_row(st["id"], "[red]" + st["error"] + "[/red]", "", "", "", "", "")
            continue
        t.add_row(st["id"], st["name"], str(len(st["to_push"])), str(len(st["to_delete"])),
                  str(len(st["conflicts"])), str(st["to_pull"]), st["path"])
    console.print(t)


@dict_app.command("link")
def dict_link(name: str = typer.Argument(...), path: Path = typer.Argument(..., exists=True, dir_okay=False)):
    """앱 사전 파일을 연결한다."""
    from . import dictsync

    lid = dictsync.add_link(name, path)
    console.print(f"[green]연결[/green] {lid} → {path}")


@dict_app.command("push")
def dict_push(link_id: str = typer.Argument(...),
              prefer: str = typer.Option("", "--prefer", help="충돌을 한꺼번에: app 또는 master")):
    """[업데이트] 그 앱에서 바뀐 것을 본사전에 올린다."""
    from . import dictsync

    st = dictsync.status(link_id)
    choices = {k: prefer for k in st.conflicts} if prefer in ("app", "master") else {}
    r = dictsync.push(link_id, choices)
    console.print(f"[green]업데이트[/green] 새로 {r['added']} · 바뀜 {r['changed']} · 지움 {r['deleted']} "
                  f"→ 본사전 {r['master_count']}개")
    if r["unresolved"]:
        console.print(f"[yellow]충돌 {len(r['unresolved'])}개는 그대로 뒀습니다[/yellow] "
                      f"(웹 「발음 사전」에서 고르거나 --prefer app|master): {', '.join(r['unresolved'][:20])}")


@dict_app.command("pull")
def dict_pull(link_id: str = typer.Argument(...), force: bool = typer.Option(False, "--force")):
    """[다운받기] 본사전을 그 앱 사전 파일로 받는다."""
    from . import dictsync

    r = dictsync.pull(link_id, force=force)
    console.print(f"[green]다운받기[/green] {r['written']}개 (바뀐 것 {r['changed']}) · 백업 {r['backup']}")


@dict_app.command("candidates")
def dict_candidates():
    """상위 폴더에서 연결 후보(발음 사전처럼 보이는 파일)를 찾는다."""
    from . import dictsync

    for p in dictsync.find_candidates():
        console.print(p)


# ---------------------------------------------------------------- 점검·서버

@app.command()
def doctor(skip_synth: bool = typer.Option(False, "--skip-synth", help="시험 합성 생략")):
    """장치 · 모델 캐시 · 목소리 · 시험 합성."""
    from . import dictsync
    from .engine import cache_path
    from .voices import list_voices

    s = settings_module.load()
    settings_module.remember_home(s.home)
    ok = True
    console.print(f"[bold]집 폴더[/bold]  {s.home}")
    try:
        import torch

        cuda = torch.cuda.is_available()
        console.print(f"[bold]torch[/bold]    {torch.__version__} · CUDA {'[green]사용 가능[/green] ' + torch.cuda.get_device_name(0) if cuda else '[yellow]없음[/yellow]'}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold]torch[/bold]    [red]없음[/red] ({exc}) — setup.bat 을 먼저 실행하세요"
                      + (" (원격 모드라면 괜찮습니다)" if s.remote_server else ""))
        ok = bool(s.remote_server)
    hf = Path.home() / ".cache" / "huggingface" / "hub" / "models--k2-fsa--OmniVoice"
    if hf.is_dir():
        size = sum(p.stat().st_size for p in hf.rglob("*") if p.is_file()) / 1e9
        console.print(f"[bold]모델[/bold]     {hf} ({size:.1f} GB)")
    else:
        console.print("[bold]모델[/bold]     아직 없음 — 첫 합성 때 약 3GB 를 받습니다")
    console.print(f"[bold]발음 사전[/bold] {s.pronunciation_map_path} ({len(dictsync.read_master().rules)}개)")
    vs = list_voices(s.voices_dir)
    if not vs:
        console.print(f"[red]목소리가 없습니다[/red] ({s.voices_dir})")
        ok = False
    for v in vs:
        pt = cache_path(v.ref_audio, v.ref_text, s.prompt_cache_dir) if v.ok and v.ref_audio.suffix != ".pt" else None
        console.print(f"[bold]목소리 {v.code}[/bold] {v.name} · 녹음 "
                      + ("[green]있음[/green]" if v.ok else f"[red]없음 {v.ref_audio}[/red]")
                      + (f" · 캐시 {pt.name} {'[green]있음[/green]' if pt.is_file() else '(첫 합성 때 만듦)'}" if pt else ""))
        ok = ok and v.ok
    if skip_synth or not ok:
        raise typer.Exit(0 if ok else 1)
    from .audio_io import write_wav
    from .engine import Engine

    t0 = time.time()
    with console.status("모델 로드 중…"):
        eng = Engine.get_sync()
    console.print(f"[bold]장치[/bold]     {eng.device} ({eng.device_name}) · 로드 {time.time() - t0:.1f}초")
    with console.status(f"{s.default_voice} 시험 합성 중…"):
        wav, m = eng.synth_sync("안녕하세요. 시험 합성입니다.", voice_code=s.default_voice)
    out = s.workspace_root / "doctor" / f"doctor_{s.default_voice}.wav"
    write_wav(out, wav, eng.sample_rate)
    console.print(f"[green]시험 합성 OK[/green] {m['duration_seconds']:.1f}초 음성을 {m['synth_seconds']:.1f}초에 "
                  f"(×{m['rtf']}) → {out}")


def _lan_ips() -> list[str]:
    """이 PC 의 사내망 IPv4 (127.x · 169.254.x 제외)."""
    import socket

    ips: set[str] = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:   # 기본 경로로 나가는 주소 (패킷은 보내지 않는다)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            ips.add(sk.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))


def _share_token(home: Path) -> str:
    """사내 공개용 비밀번호 — config/share_token.txt 에 한 번 만들어 계속 쓴다."""
    import secrets

    p = home / "config" / "share_token.txt"
    if p.is_file() and p.read_text(encoding="utf-8").strip():
        return p.read_text(encoding="utf-8").strip()
    tok = secrets.token_urlsafe(8)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok, encoding="utf-8")
    return tok


@app.command()
def serve(host: str = typer.Option(None, "--host", help="기본 127.0.0.1 (사내 공개는 --share)"),
          port: int = typer.Option(None, "--port", help="기본 7879"),
          share: bool = typer.Option(False, "--share", help="사내 다른 PC 에 비밀번호를 걸고 연다")):
    """웹 화면 + HTTP API 서버."""
    import os

    import uvicorn

    s = settings_module.load()
    settings_module.remember_home(s.home)
    p = port or s.port
    if share:
        h = host or "0.0.0.0"
        token = s.token or _share_token(s.home)
        os.environ["OMNIVOICE_TTS_TOKEN"] = token          # 서버(같은 프로세스)가 읽는다
        console.print(f"\n[bold]사내 공개[/bold] — 비밀번호 [bold]{token}[/bold]  (config/share_token.txt, 지우면 새로 만듦)")
        for ip in _lan_ips():
            console.print(f"  다른 PC 브라우저 : [cyan]http://{ip}:{p}/?token={token}[/cyan]")
            console.print(f"  다른 PC 프로그램 : http://{ip}:{p}/api/synthesize  + 헤더 Authorization: Bearer {token}")
        console.print("  ※ 처음 한 번 Windows 방화벽 창이 뜨면 「개인 네트워크」 허용\n")
    else:
        h = host or s.host
        if h not in ("127.0.0.1", "localhost") and not s.token:
            console.print("[yellow]주의[/yellow] 다른 PC 에 열었지만 비밀번호가 없습니다. --share 를 쓰세요.")
    console.print(f"이 PC: http://localhost:{p}   (API 문서 http://localhost:{p}/docs)")
    uvicorn.run("omnivoice_tts.server.app:create_app", factory=True, host=h, port=p, workers=1, log_level="info")


if __name__ == "__main__":
    app()
