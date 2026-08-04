# -*- coding: utf-8 -*-
"""인사이트 생성 — 수집기가 만든 프롬프트를 Claude에 보내 분석을 받는다

    python insight.py --dry-run   # 호출 없이 토큰·비용만 계산
    python insight.py             # 실제 생성
    python insight.py kr macro    # 특정 자산군만

ANTHROPIC_API_KEY가 없으면 아무것도 하지 않는다 (DART·EIA와 같은 방식).
"""
import io
import glob
import os
import sys
import time
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

MARKETS = ["kr", "us", "macro", "coin"]
LABELS = {"kr": "국장", "us": "미장", "macro": "매크로", "coin": "코인"}

# 100만 토큰당 달러. 실제 청구는 콘솔에서 확인하는 게 정확하다.
PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),      # 2026-08-31까지 도입가 $2/$10
    "claude-haiku-4-5": (1.0, 5.0),
}
USD_KRW = 1430


def latest_prompt(market):
    files = sorted(glob.glob(str(DATA / f"prompt_{market}_2*.txt")),
                   key=os.path.getmtime)
    return Path(files[-1]) if files else None


def _client():
    try:
        import anthropic
    except ImportError:
        print("  anthropic 패키지가 없습니다.  pip install anthropic")
        return None
    from core import env
    key = env.get("ANTHROPIC_API_KEY")
    if not key:
        print("  .env에 ANTHROPIC_API_KEY가 없습니다.")
        return None
    return anthropic.Anthropic(api_key=key)


def count(client, model, prompt):
    """실제 토큰 수. 한글은 영문보다 토큰을 많이 먹어서 글자 수로 어림하면
    크게 틀린다 — API에 직접 물어본다."""
    r = client.messages.count_tokens(
        model=model, messages=[{"role": "user", "content": prompt}])
    return r.input_tokens


def cost_krw(model, tin, tout):
    pin, pout = PRICING.get(model, (5.0, 25.0))
    return (tin * pin + tout * pout) / 1e6 * USD_KRW


def generate(client, model, prompt, max_tokens, effort):
    """인사이트 1건. 반환: (본문, 입력토큰, 출력토큰)"""
    kw = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    # Opus 5는 사고가 기본이고, 그 외 모델은 명시해야 켜진다.
    if not model.startswith("claude-haiku"):
        kw["thinking"] = {"type": "adaptive"}
        kw["output_config"] = {"effort": effort}

    r = client.messages.create(**kw)

    if r.stop_reason == "refusal":
        return "(안전 분류기가 요청을 거절했습니다)", r.usage.input_tokens, 0

    text = "\n".join(b.text for b in r.content if b.type == "text")
    if r.stop_reason == "max_tokens":
        text += "\n\n*(출력 한도에 걸려 잘렸습니다. max_tokens를 늘리세요.)*"
    return text, r.usage.input_tokens, r.usage.output_tokens


def run(markets=None, dry_run=False, model=None, max_tokens=None, effort=None):
    import config
    model = model or getattr(config, "INSIGHT_MODEL", "claude-opus-5")
    max_tokens = max_tokens or getattr(config, "INSIGHT_MAX_TOKENS", 16000)
    effort = effort or getattr(config, "INSIGHT_EFFORT", "high")
    markets = markets or MARKETS

    client = _client()
    if not client:
        return {}

    print(f"  모델 {model} · effort {effort} · max_tokens {max_tokens:,}\n")
    results, tin_all, tout_all = {}, 0, 0
    now = dt.datetime.now()

    for m in markets:
        p = latest_prompt(m)
        if not p:
            print(f"  {LABELS[m]:6s} 프롬프트 없음 — collect_{m}.py를 먼저 실행하세요")
            continue
        prompt = p.read_text(encoding="utf-8")

        try:
            tin = count(client, model, prompt)
        except Exception as e:
            print(f"  {LABELS[m]:6s} 토큰 계산 실패: {type(e).__name__} {str(e)[:60]}")
            continue

        if dry_run:
            # 출력은 실제 생성분(사고 포함)을 4,000토큰으로 가정
            est = cost_krw(model, tin, 4000)
            print(f"  {LABELS[m]:6s} 입력 {tin:>7,} 토큰"
                  f"  예상 {est:>6,.0f}원  ({p.name})")
            tin_all += tin
            tout_all += 4000
            continue

        t0 = time.time()
        print(f"  {LABELS[m]:6s} 입력 {tin:>7,} 토큰 · 생성 중 … ",
              end="", flush=True)
        try:
            text, tin2, tout = generate(client, model, prompt, max_tokens, effort)
        except Exception as e:
            print(f"실패 — {type(e).__name__}: {str(e)[:70]}")
            continue

        out = DATA / f"insight_{m}.md"
        out.write_text(text, encoding="utf-8")
        # 날짜별 사본 — 지난 판단을 되짚어볼 수 있게
        (DATA / f"insight_{m}_{now:%Y%m%d_%H%M}.md").write_text(text, encoding="utf-8")

        results[m] = text
        tin_all += tin2
        tout_all += tout
        print(f"완료 {time.time()-t0:5.1f}초 · 출력 {tout:,} 토큰 · "
              f"{cost_krw(model, tin2, tout):,.0f}원")

    total = cost_krw(model, tin_all, tout_all)
    kind = "예상" if dry_run else "실제"
    print(f"\n  {kind} 합계  입력 {tin_all:,} / 출력 {tout_all:,} 토큰"
          f"  ≈ {total:,.0f}원")
    if total:
        print(f"  하루 1회 기준 월 {total*30:,.0f}원 · "
              f"하루 3회면 월 {total*90:,.0f}원")
    return results


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    print(f"\n인사이트 생성 {'(계산만)' if dry else ''}\n")
    run(markets=args or None, dry_run=dry)
    print()
