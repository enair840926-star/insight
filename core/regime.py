# -*- coding: utf-8 -*-
"""장 자체가 어떤 상태인가 — 픽 위에 세우는 한 줄

종목 픽이 두꺼워도 장이 나쁘면 다르게 읽어야 한다. 그런데 그 판단을 글에
맡기면 어제와 오늘의 잣대가 달라져서, 나중에 '장이 나쁘다고 했던 날'을
세는 것조차 못 한다. `core/pick.py`가 종목에 하는 일을 시장에 한다.

**픽 점수와 곱하지 않는다.** 곱하면 픽이 왜 뽑혔는지 되짚을 수 없고, 지금
표본으로는 그 보정이 도움이 됐는지 검증할 방법도 없다. 따로 내서 나란히
둔다 — "장은 이런 상태다, 그 위에서 이 셋이 뽑혔다".

## 자산군마다 잴 수 있는 것이 다르다

국장은 개장 전 스냅샷에 **오늘 값이 아예 없다**(실측: 지수 등락 0.0,
`market_status` PREOPEN, 2,580개 전부 flat, 상승비율 0.0). 그래서 근거가
전부 밤사이 해외 값이고, 그것은 '어떻게 열릴까'이지 '장중에 어떨까'가
아니다. `basis`에 그 사실을 담아 화면과 프롬프트가 함께 밝힌다.

## 임계값은 아직 실측이 아니다

`cloud/`에 스냅샷이 자산군당 한둘뿐이라 분포를 모른다. 그래서 **부호를
중심으로 잡고 크기 임계값은 작게** 두었다. 대신 판정을 `history`에 남겨
표본이 차면 그때 고친다 — 픽이 정확히 이 순서로 만들어졌다.

임계값을 넣었으면 **실제로 몇 번 켜지는지 세라.** 한 번도 안 걸리는 조건은
죽은 코드다. `tools/regime_probe.py`가 그것을 센다.
"""

# 임계값이나 축을 바꾸면 올린다. 이 값이 다르면 기록끼리 직접 비교하면
# 안 된다. `core/history.py`의 RULES_VERSION 과 따로 두는 이유는 픽 규칙과
# 시장 판정이 각자 바뀌기 때문이다 — 한 값으로 묶으면 픽을 고칠 때마다
# 판정 기록이 끊긴다.
VERSION = "2026-08-13"

# 신호 하나가 ±1이다. 크기를 다르게 주려면 실측이 먼저다 — 지금은 어느
# 신호가 더 값을 하는지 모르므로 전부 같은 무게로 둔다.
STRONG = 2          # |합계|이 이 이상이면 방향을 붙인다

# 임계값. 전부 초기 추정값이며 실측으로 정한 것이 아니다.
TH = {
    "futures": 0.3,        # 미국 선물 등락 %
    "vix": 3.0,            # VIX 등락 % (오르면 비우호)
    "fx": 0.5,             # 원달러 등락 % (내리면 원화 강세 = 우호)
    "yield": 2.0,          # 미10년물 등락 %
    "fg": 5,               # 공포탐욕 지수 전일 대비 변화
    "cap_weighted": 0.3,   # 시총가중 등락 %
    "breadth": 55.0,       # 상승비율 % (아래는 100-이 값)
    "sector": 62.0,        # 상승 섹터 비율 % (13개 중 8개가 61.5)
    "premarket": 0.3,      # 프리마켓 중간 등락 %
    "coin_med": 0.5,       # 코인 중간 등락 %
    # 85인 이유는 실측이다. 75로 뒀더니 스냅샷 17개 중 16개에서 켜져 신호가
    # 아니라 상수였다 — 관측 범위가 75.9~87.3%로 늘 높은 쪽이다.
    "funding": 85.0,       # 펀딩비 양수 비율 % — 쏠리면 되돌림 위험
    "kimchi": 2.0,         # 김치 프리미엄 %
}


def _axis(*cands):
    """한 축에서 **하나만** 센다.

    같은 사실을 두 번 세면 판정이 한쪽으로 굳는다. 실측에서 그랬다 —
    국장은 선물·VIX·원달러를 따로 세어 스냅샷 22개 중 21개가 '우호'로
    나왔는데, 그 셋은 리스크온 하루의 세 얼굴이지 근거 셋이 아니다.
    미장도 시총가중·상승비율·섹터가 전부 "오늘 올랐다"의 다른 표현이라
    14개 중 11개가 우호였다.

    후보를 센 것이 우선순위 순으로 들어오고, 먼저 걸리는 하나만 쓴다.
    """
    for c in cands:
        if c:
            return c
    return None


def _band(v, th, label, up="", down="", invert=False):
    """임계 밖이면 (부호, 설명). 안이면 None.

    invert=True 는 '오르면 나쁜' 값이다 (VIX·환율·금리).
    """
    if v is None or abs(v) < th:
        return None
    sign = 1 if v > 0 else -1
    if invert:
        sign = -sign
    tag = (up if sign > 0 else down) or ""
    return (sign, f"{label} {v:+.2f}%" + (f" — {tag}" if tag else ""))


def _get(d, *path):
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# ---------------------------------------------------------------- 국장
def _kr(b):
    """개장 전이라 오늘 국장 값이 없다. 밤사이 해외 값으로만 잰다.

    축: 해외 위험선호 · 통화 · 금리 · 심리. 선물과 VIX를 한 축에 둔 것은
    둘이 같은 것을 재기 때문이다 — 선물이 오른 날 VIX는 거의 항상 내린다.
    """
    mac = b.get("macro") or {}
    out = []

    # [축 1] 해외 위험선호 — 선물이 우선이고, 없거나 미달이면 VIX로 본다.
    fut = [_get(mac, k, "change_pct") for k in ("나스닥선물", "S&P500선물")]
    fut = [x for x in fut if x is not None]
    out.append(_axis(
        _band(sum(fut) / len(fut), TH["futures"], "미국 선물",
              "위험 선호", "위험 회피") if fut else None,
        _band(_get(mac, "VIX", "change_pct"), TH["vix"], "VIX",
              invert=True, up="변동성 진정", down="변동성 확대"),
    ))
    # [축 2] 통화 — 원화가 강해지면 외국인이 들어오기 쉽다.
    out.append(_band(_get(mac, "원달러", "change_pct"), TH["fx"], "원달러",
                     invert=True, up="원화 강세", down="원화 약세"))
    # [축 3] 금리
    out.append(_band(_get(mac, "미10년물", "change_pct"), TH["yield"],
                     "미10년물 금리", invert=True, down="금리 부담"))
    # [축 4] 심리
    out.append(_fear_greed(_get(b, "sentiment", "us_fear_greed"),
                           "미국 공포탐욕"))
    return [x for x in out if x]


def _fear_greed(fg, label, cur="score", prev="prev_close"):
    """공포탐욕은 수준이 아니라 **전일 대비 변화**로 센다.

    수준으로 재면 강세장 내내 'greed'라 상수가 된다 — 이 저장소가 절대
    임계값을 중간값 대비로 바꾼 것과 같은 이유다.
    """
    if not fg or fg.get(cur) is None or fg.get(prev) is None:
        return None
    d = fg[cur] - fg[prev]
    if abs(d) < TH["fg"]:
        return None
    return (1 if d > 0 else -1, f"{label} {fg[cur]:.0f} ({d:+.0f})")


# ---------------------------------------------------------------- 미장
def _us(b):
    """축: 방향 · 폭 · 변동성 · 개장 전 · 심리.

    시총가중(방향)과 상승비율(폭)은 갈릴 수 있어 따로 둔다 — 대형주만
    오른 날이 실제로 있다. 반면 상승비율과 섹터 개수는 같은 폭을 두 번
    세는 것이라 한 축에 묶었다.
    """
    ix, ag = b.get("indices") or {}, b.get("aggregate") or {}
    out = []

    # [축 1] 방향
    out.append(_band(ag.get("market_cap_weighted_pct"), TH["cap_weighted"],
                     "시총가중 등락"))

    # [축 2] 폭 — 상승비율이 우선, 없으면 섹터 개수로 본다.
    br = ag.get("breadth") or {}
    r = br.get("up_ratio")
    breadth = None
    if r is not None and (r >= TH["breadth"] or r <= 100 - TH["breadth"]):
        breadth = (1 if r >= TH["breadth"] else -1,
                   f"상승비율 {r:.1f}% ({br.get('up', 0):,}/"
                   f"{br.get('counted', 0):,})")
    secs = ag.get("sectors") or []
    sector = None
    if secs:
        up = sum(1 for s in secs if (s.get("cap_weighted_pct") or 0) > 0)
        pctv = up * 100 / len(secs)
        if pctv >= TH["sector"] or pctv <= 100 - TH["sector"]:
            sector = (1 if pctv >= TH["sector"] else -1,
                      f"섹터 {up}/{len(secs)}개 상승")
    out.append(_axis(breadth, sector))

    # [축 3] 변동성
    out.append(_band(_get(ix, "VIX", "change_pct"), TH["vix"], "VIX",
                     invert=True, up="변동성 진정", down="변동성 확대"))

    # [축 4] 개장 전 — 수집이 개장 1시간 전이라 프리마켓이 이미 네 시간 반
    # 지나 있다. 중간값으로 본다. 평균은 급등 하나에 끌려간다.
    pre = sorted(x["pre_change_pct"] for x in (b.get("selected") or [])
                 if x.get("pre_change_pct") is not None)
    if pre:
        out.append(_band(pre[len(pre) // 2], TH["premarket"],
                         f"프리마켓 중간 등락 ({len(pre)}종목)"))

    # [축 5] 심리
    out.append(_fear_greed(_get(b, "sentiment", "us_fear_greed"), "공포탐욕"))
    return [x for x in out if x]


# ---------------------------------------------------------------- 코인
def _coin(b):
    """축: 방향과 폭 · 포지션 · 심리 · 국내 수요.

    상승비율과 중간 등락은 같은 것을 재므로 한 축에 묶었다 — 절반 넘게
    오른 날은 중간 등락도 양수다.
    """
    ag = b.get("aggregate") or {}
    out = []

    # [축 1] 방향·폭 — 상승비율이 우선, 미달이면 중간 등락으로 본다.
    r = ag.get("up_ratio")
    breadth = None
    if r is not None and (r >= TH["breadth"] or r <= 100 - TH["breadth"]):
        breadth = (1 if r >= TH["breadth"] else -1,
                   f"상승비율 {r:.1f}% ({ag.get('up', 0)}/"
                   f"{ag.get('counted', 0)})")
    out.append(_axis(breadth,
                     _band(ag.get("median_change_pct"), TH["coin_med"],
                           "중간 등락")))

    # [축 2] 포지션 — 펀딩비가 한쪽으로 쏠리면 되돌려질 때 청산이 몰린다.
    # 그래서 롱 쏠림은 상승 신호가 아니라 위험 신호로 센다.
    f = ag.get("positive_funding_ratio")
    if f is not None and (f >= TH["funding"] or f <= 100 - TH["funding"]):
        out.append((-1 if f >= TH["funding"] else 1,
                    f"펀딩비 양수 {f:.1f}% — "
                    + ("롱 쏠림(되돌림 위험)" if f >= TH["funding"]
                       else "숏 쏠림(반등 여지)")))

    # [축 3] 심리
    out.append(_fear_greed(b.get("fear_greed"), "코인 공포탐욕",
                           cur="value", prev="prev"))

    # [축 4] 국내 수요 — 김프가 크면 국내가 앞서 있다는 뜻이라 되돌림이 잦다.
    ks = sorted(v.get("premium_pct") for v in (b.get("kimchi") or {}).values()
                if isinstance(v, dict) and v.get("premium_pct") is not None)
    if ks:
        med = ks[len(ks) // 2]
        if abs(med) >= TH["kimchi"]:
            out.append((-1 if med > 0 else 1,
                        f"김치 프리미엄 중간값 {med:+.2f}%"))
    return [x for x in out if x]


# ---------------------------------------------------------------- 매크로
def _macro(b):
    """매크로에는 '장'이 없다. 금·원유의 배경인 위험 선호를 잰다.

    축: 위험자산 방향 · 변동성 · 금리 구조 · 관계 · 심리. 실측에서 스냅샷
    15개 중 5개가 '알 수 없음'이었다 — 곡선 역전과 관계 깨짐만으로는
    대부분의 날에 아무것도 안 걸린다. `records`에 이미 있는 S&P500·VIX를
    쓰면 그 날들이 메워진다.
    """
    out = []
    rec = {r.get("name"): r for r in (b.get("records") or [])
           if isinstance(r, dict)}

    # [축 1] 위험자산 방향
    out.append(_band(_get(rec, "S&P500", "change_pct"), TH["cap_weighted"],
                     "S&P500"))
    # [축 2] 변동성
    out.append(_band(_get(rec, "VIX", "change_pct"), TH["vix"], "VIX",
                     invert=True, up="변동성 진정", down="변동성 확대"))

    # [축 3] 금리 구조 — 역전은 침체 신호로 읽힌다.
    for c in b.get("yield_curve") or []:
        if c.get("label") == "10Y-2Y":
            if c.get("inverted"):
                out.append((-1, f"장단기 금리 역전 ({c.get('spread_bp')}bp)"
                                " — 침체 신호로 읽힌다"))
            break

    # [축 4] 관계 — 늘 성립하던 짝이 깨졌다는 것은 어느 한쪽이 다른 것을
    # 보고 있다는 뜻이다. 방향은 모르지만 불확실성이 커진 것은 맞다.
    broken = [d["pair"] for d in b.get("divergences") or [] if d.get("broken")]
    if broken:
        out.append((-1, f"관계가 깨진 짝 {len(broken)}개 ({broken[0]} 등)"))

    # [축 5] 심리
    out.append(_fear_greed(_get(b, "sentiment", "us_fear_greed"), "공포탐욕"))
    return [x for x in out if x]


BY_MARKET = {"kr": _kr, "us": _us, "coin": _coin, "macro": _macro}

# 판정 근거가 무엇에 근거하는가. 국장만 특별하다.
BASIS = {
    "kr": "오늘 국장 값은 개장 전이라 아직 없다. 아래는 전부 밤사이 해외 "
          "값이므로 '어떻게 열릴까'이지 '장중에 어떨까'가 아니다.",
}


def judge(market, bundle):
    """시장 상태 판정. 반환: dict (신호가 없으면 state='알 수 없음')."""
    fn = BY_MARKET.get(market)
    sigs = fn(bundle) if fn else []
    score = sum(s for s, _ in sigs)
    if not sigs:
        state = "알 수 없음"
    elif score >= STRONG:
        state = "우호"
    elif score <= -STRONG:
        state = "비우호"
    else:
        state = "중립"
    return {
        "state": state,
        "score": score,
        "why": [t for _, t in sigs],
        "signed": [(s, t) for s, t in sigs],
        "n": len(sigs),
        "basis": BASIS.get(market),
    }


def text(market, bundle):
    """프롬프트에 넣을 블록. 화면은 dashboard.py가 따로 그린다."""
    r = judge(market, bundle)
    if r["state"] == "알 수 없음":
        return ("## 장 상태\n판정할 재료가 없다. 이번 스냅샷에서는 시장 수준 "
                "신호가 하나도 걸리지 않았다 — **없는 것이 아니라 못 받은 "
                "것일 수 있으니 '장이 잠잠하다'로 쓰지 마라.**\n")
    lines = [f"## 장 상태 — **{r['state']}** (신호 {r['n']}개, 합계 "
             f"{r['score']:+d})"]
    if r["basis"]:
        lines.append(r["basis"])
    for s, t in r["signed"]:
        lines.append(f"- ({s:+d}) {t}")
    lines.append("")
    lines.append("**이 판정은 픽 점수에 들어가 있지 않다.** 픽은 종목 자체의 "
                 "근거로만 뽑혔고, 이것은 그 위에 놓이는 배경이다. 장이 "
                 "비우호인데 픽이 상승이면 그 사실을 함께 적어라 — 둘 중 "
                 "하나를 지우지 마라.")
    return "\n".join(lines) + "\n"
