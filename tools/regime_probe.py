# -*- coding: utf-8 -*-
"""시장 판정의 신호가 실제로 걸리는지 센다

    python tools/regime_probe.py          # 있는 스냅샷 전부
    python tools/regime_probe.py -v       # 임계에 못 미친 값까지

임계값을 넣었으면 **몇 번 켜지는지 세야 한다.** 한 번도 안 걸리는 조건은
죽은 코드이고, 임계값이 실제 범위 밖이거나 필드 이름이 안 맞는 경우가
흔하다. 이 저장소에서 실제로 그런 일이 있었다 — 코인 임계값을 read.py에서
그대로 가져왔더니 OKX 스케일에서 한 번도 안 걸렸다.

반대로 **모두에게 늘 켜지는 신호도 신호가 아니라 상수다.** 켜진 비율이
100%에 가까우면 그것도 함께 의심하라.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import history, regime, store

MARKETS = ["kr", "us", "coin", "macro"]


def _name(text):
    """설명에서 값을 지우고 신호 이름만 남긴다.

    안 그러면 '미국 선물 +4.46%'와 '미국 선물 +2.59%'가 다른 신호로
    세어져 전부 1회씩 흩어진다 — 몇 번 켜졌는지 세려고 만든 도구인데
    그 숫자가 안 나온다.
    """
    t = text.split(" —")[0]
    t = re.sub(r"\s*\([^)]*\)", "", t)          # 괄호 안 (수치·개수)
    t = re.sub(r"[-+]?\d[\d,]*\.?\d*%?", "", t)  # 남은 숫자
    return t.strip() or text


def snapshots(market, per_day=True):
    """cloud/ 와 data/ 의 스냅샷. 기본은 **날짜별 마지막 하나**다.

    하루에 여러 번 수집되므로 전부 세면 그날이 여러 번 반영돼 분포가
    부푼다. 실측에서 08-04 하루가 국장 22개 중 14개를 차지해, 그날이
    리스크온이었다는 이유만으로 '우호 21/22'가 나왔다. `score_picks`가
    픽에 하는 것과 같은 처리다.
    """
    seen, out = set(), []
    for d in ("cloud", "data"):
        for f in sorted(glob.glob(str(store.ROOT / d / f"{market}_2*.json"))):
            name = os.path.basename(f)
            if name in seen:
                continue
            seen.add(name)
            try:
                out.append((name, json.load(open(f, encoding="utf-8"))))
            except (OSError, ValueError) as e:
                print(f"  ! {name} 읽기 실패 — {type(e).__name__}")
    if per_day:
        by_day = {}
        for name, b in sorted(out):
            parts = name.split("_")
            by_day[parts[1] if len(parts) > 1 else name] = (name, b)
        out = [by_day[k] for k in sorted(by_day)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--all", action="store_true",
                    help="같은 날 스냅샷도 전부 센다 (기본은 날짜별 마지막)")
    ap.add_argument("markets", nargs="*", default=None)
    a = ap.parse_args()

    total_fired = defaultdict(int)
    total_snaps = 0
    for m in (a.markets or MARKETS):
        snaps = snapshots(m, per_day=not a.all)
        if not snaps:
            print(f"\n### {m}: 스냅샷 없음")
            continue
        print(f"\n### {m} — {'스냅샷' if a.all else '날짜'} {len(snaps)}개")
        total_snaps += len(snaps)
        states = defaultdict(int)
        for name, b in snaps:
            r = regime.judge(m, b)
            states[r["state"]] += 1
            print(f"  {name[-18:]:18s} {r['state']:6s} "
                  f"합계 {r['score']:+d}  신호 {r['n']}개")
            for s, t in r["signed"]:
                total_fired[(m, _name(t))] += 1
                if a.verbose:
                    print(f"      ({s:+d}) {t}")
        # 한쪽으로 굳었는지 본다. 8할 넘게 한 상태면 그건 판정이 아니라 상수다.
        # 다만 날이 적으면 굳은 것과 그 며칠이 실제로 한 방향이었던 것을
        # 구별할 수 없다. 그럴 때는 단정하지 않는다.
        top = max(states.values())
        if len(snaps) < 10:
            warn = f"  (날이 {len(snaps)}일뿐이라 굳었는지 판단 못 함)"
        elif top >= len(snaps) * 0.8:
            warn = "  ← 한쪽으로 굳었다"
        else:
            warn = ""
        print(f"  상태 분포: {dict(states)}{warn}")

    print(f"\n{'='*70}\n신호별 켜진 횟수 (스냅샷 {total_snaps}개 기준)")
    if not total_fired:
        print("  **하나도 안 걸렸다.** 임계값이 범위 밖이거나 필드가 안 맞는다.")
        return 1
    for (m, k), n in sorted(total_fired.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}회  {m}: {k}")
    print("\n한 번도 안 나온 신호는 위 목록에 없다 — 죽은 조건인지 확인하라.")
    print("스냅샷이 적으면 안 걸린 것과 걸릴 수 없는 것이 구별되지 않는다.")

    _scoreboard(a.markets or MARKETS)
    return 0


def _scoreboard(markets):
    """판정이 실제로 맞았나. 위쪽이 '신호가 걸리나'를 센다면 이건 '그 판정이
    맞았나'를 센다 — 둘은 다른 질문이다.

    **'중립'은 세지 않는다.** 방향을 주장하지 않았으므로 맞고 틀릴 것이
    없다(픽의 '팽팽'과 같다). 대신 몇 건이 중립이었는지는 함께 찍는다 —
    대부분이 중립이면 판정이 일을 안 하고 있다는 뜻이다.
    """
    rows = history.regime_pairs(markets)
    print(f"\n{'='*70}\n판정이 맞았나 (결과가 채워진 것만)")
    if not rows:
        print("  아직 없다. 판정 하나는 다음 세션"
              f"({history.MIN_HOURS}시간 뒤)이 지나야 채점된다.")
        print("  **2026-08-16 이전 판정은 영영 못 잰다** — 그때는 벤치마크")
        print("  수준을 같이 안 남겨서 다음 세션 등락을 낼 수가 없다.")
        return

    for m in markets:
        xs = [(r, o) for r, o in rows if r.get("market") == m]
        if not xs:
            continue
        band = history.regime_flat_band(rows, m)
        vs = [v for r, o in xs for v in [history.regime_verdict(r, o, band)] if v]
        hit = sum(1 for v in vs if v == "맞음")
        flat = sum(1 for v in vs if v == "횡보")
        neutral = sum(1 for r, _ in xs if r.get("state") == "중립")
        d = hit + sum(1 for v in vs if v == "틀림")
        bench = history.REGIME_BENCH.get(m)
        rate = f"{hit*100/d:5.1f}% ({hit}/{d})" if d else "  —  (방향 0건)"
        band_txt = (f"횡보폭 {band:.2f}%" if band else
                    f"횡보 안 가름 (표본 {history.REGIME_BAND_MIN}건 미만)")
        print(f"  {m:6s} {rate}  중립 {neutral}건 · 횡보 {flat}건  "
              f"[{bench}] {band_txt}")
        if d:
            print(f"         {history.coin_flip_gap(hit, d)}")

    print(f"  → {history.verdict(len(rows), history.ENOUGH_REGIME, '판정을 손댈 만하다')}")
    print("  매크로 벤치마크는 S&P500이다 — 판정이 재는 것이 금·원유 자체가")
    print("  아니라 그 배경인 위험 선호라서다. 미장과 같은 잣대이므로 두")
    print("  판정이 갈리면 그 자체가 정보다(신호 구성이 다르다).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
