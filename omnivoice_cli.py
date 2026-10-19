# -*- coding: utf-8 -*-
"""OmniVoice 보이스 클로닝 CLI (NVIDIA CUDA / Intel XPU / Apple MPS / CPU).

    python omnivoice_cli.py say "안녕하세요" -r voice_01.wav -o hello.wav
    python omnivoice_cli.py batch script.txt -r voice_01.wav -o outputs/lesson1
    python omnivoice_cli.py prompt -r voice_01.wav -o my_voice.pt

-r 에는 레퍼런스 wav 또는 `prompt` 로 저장한 .pt 를 줄 수 있다.
wav 를 주면 받아쓰기(Whisper)·인코딩 결과를 ~/.cache/omnivoice-cli/ 에 캐시해서
두 번째부터는 바로 합성한다.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

SR = 24000
MODEL_ID = "k2-fsa/OmniVoice"
CACHE = Path(os.environ.get("OMNIVOICE_CLI_CACHE", Path.home() / ".cache" / "omnivoice-cli"))


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


DEVICE = "auto"  # main() 에서 --device 로 채운다


def resolve_device(want: str) -> str:
    """auto 면 cuda → xpu → mps → cpu 순으로 쓸 수 있는 것을 고른다."""
    import torch

    has = {
        "cuda": torch.cuda.is_available(),
        "xpu": hasattr(torch, "xpu") and torch.xpu.is_available(),
        "mps": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
        "cpu": True,
    }
    if want == "auto":
        return next(d for d in ("cuda", "xpu", "mps", "cpu") if has[d])
    if not has[want]:
        sys.exit(f"{want} 장치를 쓸 수 없습니다. 그 장치용 setup 스크립트로 torch 를 설치했는지 확인하세요.")
    return want


def load_model(need_asr: bool):
    import torch
    from omnivoice import OmniVoice

    dev = resolve_device(DEVICE)
    name = {"cuda": lambda: torch.cuda.get_device_name(0),
            "xpu": lambda: torch.xpu.get_device_name(0)}.get(dev, lambda: dev.upper())()
    # CPU·MPS 는 float16 연산이 느리거나 불안정해서 float32 로 돌린다
    dtype = torch.float16 if dev in ("cuda", "xpu") else torch.float32
    device_map = f"{dev}:0" if dev in ("cuda", "xpu") else dev
    log(f"모델 로드 중… ({name})" + ("  ※ CPU 는 매우 느립니다" if dev == "cpu" else ""))
    t0 = time.time()
    model = OmniVoice.from_pretrained(MODEL_ID, device_map=device_map, dtype=dtype,
                                      load_asr=need_asr, asr_device=device_map)
    log(f"모델 로드 완료 ({time.time() - t0:.1f}초)")
    return model


def _cache_path(ref: Path, ref_text: str | None) -> Path:
    h = hashlib.sha1(ref.read_bytes())
    h.update((ref_text or "").encode("utf-8"))
    return CACHE / f"{ref.stem}_{h.hexdigest()[:12]}.pt"


def get_prompt(ref: str, ref_text: str | None, no_cache: bool = False):
    """(model, voice_prompt) — .pt 또는 캐시가 있으면 Whisper 를 띄우지 않는다."""
    from omnivoice import VoiceClonePrompt

    ref_p = Path(ref)
    if not ref_p.is_file():
        sys.exit(f"레퍼런스 파일이 없습니다: {ref}")
    if ref_p.suffix.lower() == ".pt":
        return load_model(need_asr=False), VoiceClonePrompt.load(str(ref_p))

    cached = _cache_path(ref_p, ref_text)
    if cached.is_file() and not no_cache:
        log(f"캐시된 목소리 사용: {cached}")
        return load_model(need_asr=False), VoiceClonePrompt.load(str(cached))

    model = load_model(need_asr=not ref_text)
    log("목소리 등록 중…" + ("" if ref_text else " (Whisper 자동 받아쓰기)"))
    prompt = model.create_voice_clone_prompt(ref_audio=str(ref_p), ref_text=ref_text or None)
    CACHE.mkdir(parents=True, exist_ok=True)
    prompt.save(str(cached))
    return model, prompt


def synth(model, prompt, text: str, speed: float, steps: int):
    return model.generate(text=text, voice_clone_prompt=prompt, speed=speed, num_step=steps)[0]


def write_wav(path: Path, wav) -> float:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), wav, SR, subtype="PCM_16")
    return len(wav) / SR


def play(path: Path) -> None:
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    else:
        log(f"재생은 Windows에서만 지원합니다: {path}")


def read_text(args) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    if args.text == "-" or args.text is None:
        return sys.stdin.read().strip()
    return args.text.strip()


def cmd_say(args) -> None:
    text = read_text(args)
    if not text:
        sys.exit("읽을 텍스트가 없습니다.")
    model, prompt = get_prompt(args.ref, args.ref_text, args.no_cache)
    out = Path(args.output or time.strftime("out_%Y%m%d_%H%M%S.wav"))
    t0 = time.time()
    sec = write_wav(out, synth(model, prompt, text, args.speed, args.steps))
    log(f"완료: {out} ({sec:.1f}초 음성, 생성 {time.time() - t0:.1f}초)")
    print(out.resolve())
    if args.play:
        play(out)


def cmd_batch(args) -> None:
    import numpy as np

    lines = [l.strip() for l in Path(args.script).read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        sys.exit("대본이 비어 있습니다.")
    model, prompt = get_prompt(args.ref, args.ref_text, args.no_cache)
    out_dir = Path(args.output or Path("outputs") / time.strftime("batch_%Y%m%d_%H%M%S"))
    gap = np.zeros(int(SR * args.gap), dtype=np.float32)
    pieces = []
    for i, line in enumerate(lines, 1):
        wav = synth(model, prompt, line, args.speed, args.steps).astype(np.float32)
        sec = write_wav(out_dir / f"{args.prefix}_{i:03d}.wav", wav)
        pieces += [wav, gap]
        log(f"[{i}/{len(lines)}] {sec:.1f}s {line[:40]}")
    total = write_wav(out_dir / f"{args.prefix}_all.wav", np.concatenate(pieces[:-1]))
    log(f"완료: {out_dir} ({len(lines)}개, 합본 {total:.1f}초)")
    print(out_dir.resolve())


def cmd_prompt(args) -> None:
    _, prompt = get_prompt(args.ref, args.ref_text, no_cache=True)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    prompt.save(str(out))
    log(f"저장: {out} — 이제 -r {out} 로 쓰면 받아쓰기 없이 바로 합성합니다.")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(prog="omnivoice", description="OmniVoice 보이스 클로닝 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, gen=True):
        p.add_argument("-d", "--device", default="auto",
                       choices=["auto", "cuda", "xpu", "mps", "cpu"],
                       help="실행 장치 (기본 auto: cuda → xpu → mps → cpu)")
        p.add_argument("-r", "--ref", required=True, help="레퍼런스 음성 wav (3~10초) 또는 .pt")
        p.add_argument("--ref-text", help="레퍼런스에서 실제로 말한 문장 (생략 시 Whisper 자동)")
        p.add_argument("--no-cache", action="store_true", help="목소리 캐시를 쓰지 않고 다시 등록")
        if gen:
            p.add_argument("--speed", type=float, default=1.0, help="말 빠르기 (기본 1.0)")
            p.add_argument("--steps", type=int, default=32, help="생성 스텝 16(빠름)/32(품질, 기본)")

    p = sub.add_parser("say", help="텍스트 한 덩어리 → wav 하나")
    p.add_argument("text", nargs="?", help="읽을 텍스트 ('-' 또는 생략 시 stdin)")
    p.add_argument("-f", "--text-file", help="텍스트 파일(UTF-8)에서 읽기")
    p.add_argument("-o", "--output", help="출력 wav (기본 out_날짜시각.wav)")
    p.add_argument("--play", action="store_true", help="생성 후 바로 재생")
    common(p)
    p.set_defaults(func=cmd_say)

    p = sub.add_parser("batch", help="대본 파일의 줄마다 wav + 합본 all.wav")
    p.add_argument("script", help="한 줄에 한 문장인 UTF-8 텍스트 파일")
    p.add_argument("-o", "--output", help="출력 폴더 (기본 outputs/batch_날짜시각)")
    p.add_argument("--gap", type=float, default=0.4, help="합본에서 문장 사이 무음(초)")
    p.add_argument("--prefix", default="line", help="파일 이름 앞부분")
    common(p)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("prompt", help="목소리를 .pt 로 저장 (다음부터 -r 에 그대로 사용)")
    p.add_argument("-o", "--output", required=True, help="저장할 .pt 경로")
    common(p, gen=False)
    p.set_defaults(func=cmd_prompt)

    args = ap.parse_args()
    global DEVICE
    DEVICE = args.device
    args.func(args)


if __name__ == "__main__":
    main()
