# -*- coding: utf-8 -*-
"""기록 파일이 읽는 쪽이 기대하는 모양인지 잰다.

    python tools/history_probe.py

## 왜 있나

`history/picks-YYYY-MM.jsonl` 한 파일에 줄 종류가 다섯이다(pick · out ·
regime · regime_out · signals). 읽는 함수도 그만큼 있는데, `load()`가
**"regime만 빼고 나머지는 픽"** 으로 읽고 있었다. 그 뒤에 signals와
regime_out이 생기자 `key` 없는 줄이 픽으로 섞였고, `open_keys()`가
`KeyError: 'key'`로 죽어 **미장 수집이 2026-08-17부터 사흘 동안 저녁마다
통째로 실패했다.** 그동안 아무것도 그 사실을 말해 주지 않았다 — 대시보드는
마지막으로 성공한 스냅샷을 계속 보여 줬다.

그래서 두 가지를 잰다.

    1. 줄마다 그 종류가 있어야 할 필드를 갖고 있는가
    2. 읽는 함수가 자기 종류만 받아 가는가 (섞이면 여기서 걸린다)

새 줄 종류를 만들면 `SHAPE`에 넣어라. 넣지 않으면 '모르는 종류'로 찍힌다 —
그것 자체가 신호다. 읽는 쪽 어딘가가 그 줄을 픽으로 세고 있을 수 있다.
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history

# 종류 -> 그 줄에 반드시 있어야 하는 필드. 읽는 쪽이 `[...]`로 꺼내는
# (없으면 죽는) 것만 넣는다. `.get()`으로 읽는 것은 없어도 되므로 뺀다.
SHAPE = {
    "pick":       ("id", "market", "at", "key"),
    "out":        ("id",),
    "regime":     ("id", "market", "at"),
    "regime_out": ("id",),
    "signals":    ("market",),
}


def main():
    rows = []
    if history.DIR.is_dir():
        for f in sorted(history.DIR.glob("picks-*.jsonl")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    import json
                    rows.append((f.name, i, json.loads(line)))
                except ValueError:
                    rows.append((f.name, i, None))   # 병합이 반토막 낸 줄
    if not rows:
        print("기록이 없습니다. 수집이 한 번은 돌아야 합니다.")
        return 1

    kinds = Counter()
    broken = []
    for name, i, r in rows:
        if r is None:
            broken.append((name, i, "깨진 줄", "JSON이 아님"))
            continue
        t = r.get("t") or "pick"
        kinds[t] += 1
        want = SHAPE.get(t)
        if want is None:
            broken.append((name, i, t, "모르는 종류 — SHAPE에 없다"))
            continue
        miss = [k for k in want if k not in r]
        if miss:
            broken.append((name, i, t, "없는 필드: " + "·".join(miss)))

    print("### 줄 종류")
    for t, n in kinds.most_common():
        print(f"  {t:12s} {n:5d}줄")

    print("\n### 읽는 함수가 자기 종류만 받나")
    picks, outs = history.load()
    checks = [
        ("load() → picks", picks.values(), {"pick"}),
        ("load() → outs", outs.values(), {"out"}),
        ("load_regimes()", history.load_regimes().values(), {"regime"}),
        ("load_regime_outs()", history.load_regime_outs().values(), {"regime_out"}),
        ("load_signals()", history.load_signals(per_day=False), {"signals"}),
    ]
    bad = 0
    for label, got, want in checks:
        seen = Counter((r.get("t") or "pick") for r in got)
        extra = set(seen) - want
        mark = "✓" if not extra else f"✗ 섞임: {'·'.join(sorted(extra))}"
        bad += bool(extra)
        print(f"  {label:22s} {sum(seen.values()):5d}줄  {mark}")

    print("\n### 필드가 빠진 줄")
    if not broken:
        print("  없음 — 모든 줄이 자기 종류의 필드를 갖고 있습니다.")
    else:
        by = defaultdict(int)
        for name, i, t, why in broken:
            by[(t, why)] += 1
        for (t, why), n in sorted(by.items(), key=lambda kv: -kv[1]):
            print(f"  {t:12s} {n:5d}줄  {why}")
        print("\n  이 줄들을 읽는 쪽이 `[...]`로 꺼내면 그 자리에서 죽는다.")
        print("  실제로 그렇게 미장 수집이 사흘 멈춘 적이 있다.")

    return 1 if (broken or bad) else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
