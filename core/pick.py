# -*- coding: utf-8 -*-
"""오늘의 픽 3종 — 근거가 두꺼운 쪽을 고른다

고르는 일을 글 쓰는 쪽에 맡기면 어제 픽과 오늘 픽이 같은 잣대로
뽑혔는지 알 수 없다. 여기서 재고, 글은 그 결과를 서술만 한다.

**이 데이터는 설명치지 예측치가 아니다.** 외국인이 샀다·이익 전망이
좋다·거래량이 붙었다까지가 아는 전부이고, 그것이 내일 오른다는 보장은
아니다. 그래서 "상승 확률"이 아니라 **"상승 근거가 얼마나 두껍게
쌓였는가"**를 잰다. 틀렸을 때 어느 근거가 틀렸는지 되짚을 수 있어야
다음 판정이 나아진다.

점수는 하나다. 방향성 있는 신호를 부호 있게 더한 값이고, 양수가 클수록
오를 근거가, 음수가 클수록 내릴 근거가 두껍다. **0 근처는 근거가 없거나
서로 맞선다는 뜻이라 픽에서 빠진다** — 갈림을 따로 판정할 필요가 없다.

추세(+)와 과열(-)이 같은 값에서 나와 상쇄되는 것은 의도한 동작이다.
많이 올라온 종목은 둘이 맞물려 중간으로 밀리고, 적당히 오르면서 수급이
붙은 종목이 위로 올라온다.

자산군에 따라 고르는 목적이 다르다.

    주식(국장·미장)   살 수 있는 쪽이 한 방향뿐이라 **오를 근거가 두꺼운
                      것**만 올린다. 갈리는 방향은 아무 쓸모가 없다.
                      상승 후보가 모자라면 남는 칸은 '피할 것'으로 채우고
                      그렇게 표시한다.
    선물(코인·매크로) 양방향이 다 의미가 있으므로 **방향이 뚜렷한 것**을
                      올린다. 오르든 내리든 근거가 두꺼우면 픽이다.

예정된 실적·공시는 점수에 넣지 않는다. 오를 이유가 아니라 결과에
달렸다는 뜻이기 때문이다. 대신 경고로 남겨 뒤집힐 자리를 알려 준다.

후보는 자산군마다 필드가 다르지만 채점기는 하나다. 없는 필드는 건너뛰므로
국장에만 있는 외국인 수급, 코인에만 있는 펀딩비가 같은 함수를 통과한다.
규칙이 자산군별로 흩어지면 넷이 서로 어긋난다.
"""
import datetime as dt
import statistics

from core import read, rules, session

# ---------------------------------------------------------------- 임계값
# 한곳에 모아 둔다. 흩어지면 어느 숫자를 만졌는지 추적이 안 된다.
# 실데이터로 돌려 보고 조정하는 값들이다.

VOLUME_GATE = 0.7        # dashboard.py의 partial 가드와 같은 선
COIN_MIN_RANK = 60       # 시총 순위. 밈코인이 3자리를 다 먹는 것을 막는다

# 추정PER 갭과 52주 고점 대비는 **스냅샷 중간값 대비**로 잰다. 절대값은
# 시장 전체가 같이 움직여 변별력이 없다 (아래 _relative 참조).
PER_GAP_REL = 20         # 중간값보다 이만큼 낮으면 이익 전망이 두드러짐
HIGH_REL = 10            # 중간값보다 이만큼 더 눌렸으면 저점권
STREAK_STRONG = 5        # 연속 순매수/매도 일수
STREAK_WEAK = 3
RATIO_DELTA = 0.5        # 외국인 지분율 10일 변화 %p
MA20_STRONG = 15.0       # 20일선 이격 %
MA20_WEAK = 10.0
MA20_MACRO = 3.0         # 매크로 지표는 진폭이 작아 이 선에서 센다
POS52_HIGH, POS52_LOW = 90, 10
POS52_HIGH_W, POS52_LOW_W = 80, 20
# 펀딩비·롱숏비도 중간값 대비로 잰다. read.py의 절대 기준(±5bp, 롱숏비 0.4)은
# 바이낸스 스케일이라 OKX 실측(펀딩비 -2.6~+3.0bp, 롱숏비 5%가 0.69)에서는
# **한 번도 걸리지 않았다.** 죽은 넷이 전부 상승을 가리키는 역방향 신호라
# 코인·매크로에서 반등 근거를 잡을 방법이 아예 없었다.
LS_REL = 0.8             # 롱숏비가 중간값보다 이만큼 벌어지면 쏠림
FUNDING_REL = 0.8        # 펀딩비 bp가 중간값보다 이만큼 벌어지면 쏠림
OI_MOVE = 10.0           # 미결제약정 7일 변화 %
QUIET_PRICE = 1.0        # 이 밑이면 '가격은 조용하다'
TREND_MIN = 1.0          # 당일·7일 등락을 방향으로 셀 최소 폭 %
REL_STRENGTH = 5.0       # 20일 기준 S&P500 대비 앞선 폭 %p
SECTOR_MOVE = 1.0        # 섹터 시총가중 등락률 %

TOP_N = 3
PER_GROUP = 1            # 같은 업종·섹터에서 몇 개까지
# 이 밑은 픽으로 올리지 않는다. 3개를 억지로 채우면 근거 없는 자리가
# 근거 있는 자리와 같은 무게로 읽힌다.
#
# 다만 기준을 3점으로 못박으면 매크로가 14회 중 3회만 3종을 채운다
# (잴 축이 적어서다 — 60일선도 거래량도 수급도 없다). 그렇다고 2점으로
# 낮추면 픽의 4분의 1이 근거 두 개짜리가 된다. 그래서 **3점으로 고르고,
# 모자라는 자리만 2점으로 채우되 그 자리를 표시한다.** 주식에서 상승
# 후보가 모자랄 때 '피할 것'으로 채우고 표시하는 것과 같은 구조다.
MIN_SCORE = 3
FALLBACK_SCORE = 2

# 주식은 살 수 있는 쪽이 한 방향뿐이라 상승 후보만 뽑고, 선물은 양방향이
# 다 의미가 있어 방향이 뚜렷하기만 하면 뽑는다.
MODE = {"kr": "stock", "us": "stock", "coin": "futures", "macro": "futures"}

# 선물은 대상을 고정한다. 매일 다른 알트코인·농산물이 올라오면 어제와
# 오늘을 이어서 볼 수가 없고, 애초에 그것들을 거래하지 않는다.
# **고정 대상은 점수가 낮아도 빼지 않는다** — 방향이 안 잡혔다는 것도
# 알아야 할 상태이지 숨길 일이 아니다.
#   WTI원유를 쓰는 이유: 브렌트유에는 선물 커브도 COT도 없어 근거가 얇다.
FOCUS = {
    "coin": ("BTC", "ETH"),
    "macro": ("금", "WTI원유"),
}
# 고정 대상의 방향을 인정할 최소 근거. 신호가 네댓 개뿐이라 2로 두면
# 짝수로 상쇄돼 대부분 '팽팽'이 된다(실측: WTI원유 14번 중 12번). 순
# 우세가 한 칸이라도 있으면 방향으로 세고, 정확히 0일 때만 팽팽이다.
DIR_MIN = 1


# ---------------------------------------------------------------- 도구
def _sig(cond, weight, text):
    """조건이 참일 때만 (가중치, 설명)을 남긴다."""
    return (weight, text) if cond else None


def _side(signals):
    """방향 신호의 가중 합. 반환: (합계, [설명], 맞섬여부)

    합계가 0인 데는 두 가지가 있고 둘은 전혀 다르다. 잴 신호가 아예
    없었던 것과, +와 -가 맞서 상쇄된 것이다. 앞은 "모르겠다"이고
    뒤는 "지금 싸우는 중"이라 후자가 오히려 볼 값이 크다.
    한 숫자로 뭉개면 삼성전자처럼 모순 만점인 종목이 '방향 없음'이 된다.
    """
    hits = [s for s in signals if s]
    total = sum(w for w, _ in hits)
    split = any(w > 0 for w, _ in hits) and any(w < 0 for w, _ in hits)
    # 부호를 설명에 붙여 둔다. 합계만 보여 주면 +2 안에 섞인 -1짜리
    # 근거를 읽는 쪽이 구분할 수 없어, 반대 근거를 찬성 근거로 옮겨 쓴다.
    return total, [f"({w:+d}) {t}" for w, t in hits], split


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _flow(c):
    """가격 × 미결제약정 판정. 가격이 사실상 안 움직였으면 세지 않는다.

    그 경우는 '가격은 조용한데 쏠림만'이 따로 잡으므로 여기서 빠져도
    놓치지 않는다.
    """
    chg = _num(c.get("change_pct"))
    if chg is None or abs(chg) < QUIET_PRICE:
        return ""
    return read.coin_flow(chg, _num(c.get("oi_change_7d_pct")))[0]


# ---------------------------------------------------------------- 게이트
def gate(c, partial=False):
    """점수 이전의 자격 심사. 반환: 탈락 사유 또는 None.

    못 믿을 데이터가 1위로 올라오는 것이 제일 나쁘다. 특히 수집 실패는
    조용히 빠지게 두면 안 된다 — 없는 것과 못 받은 것은 다르다.

    거래량 게이트는 **장중 스냅샷에서만** 건다. 그 가드가 원래 있는 이유는
    장이 안 끝나 거래량이 덜 찼기 때문이지(dashboard.py의 partial),
    거래가 적은 것 자체가 흠이어서가 아니다. 마감된 장에서 0.5배는
    데이터 결함이 아니라 "조용하다"는 정보다 — 떨어뜨리지 말고
    확신도만 낮춘다.
    """
    if c.get("failed"):
        return f"수집 실패 ({c.get('failed')})"

    vr = _num(c.get("volume_ratio"))
    if partial and vr is not None and vr < VOLUME_GATE:
        return (f"장중 수집이라 거래량이 20일 평균의 {vr}배까지만 찼다 — "
                f"{VOLUME_GATE}배 미만은 판정을 접는다")

    rank = c.get("rank")
    if rank is not None and rank > COIN_MIN_RANK:
        return f"시총 {rank}위 — {COIN_MIN_RANK}위 밖"

    return None


# ---------------------------------------------------------------- 상승 근거
def _bull(c):
    """상승 근거를 부호 있게 더한다. 반환: (점수, [설명], 맞섬여부)

    양수가 클수록 오를 근거가 두껍고, 음수가 클수록 내릴 근거가 두껍다.
    **0 근처는 근거가 없거나 서로 맞선다는 뜻이라 픽에서 빠진다** —
    갈림을 따로 판정할 필요가 없다.

    추세(+)와 과열(-)이 같은 값에서 나와 상쇄되는 것은 의도한 동작이다.
    많이 올라온 종목은 둘이 맞물려 중간으로 밀리고, 적당히 오르면서
    수급이 붙은 종목이 위로 올라온다.
    """
    fn, on = _num(c.get("foreign_net_rel")), _num(c.get("organ_net_rel"))
    rawf, rawo = c.get("foreign_net_5d"), c.get("organ_net_5d")
    fs, os_ = c.get("foreign_streak") or 0, c.get("organ_streak") or 0
    gap = _num(c.get("per_gap_rel"))
    rd = _num(c.get("foreign_ratio_rel"))
    news = _num(c.get("news_score"))
    disc, disc_title = _num(c.get("disc_score")), c.get("disc_title") or ""
    hi = _num(c.get("from_52w_high_rel"))
    p52 = _num(c.get("pos_52w"))
    ma = _num(c.get("vs_ma20_pct"))
    ma60 = _num(c.get("vs_ma60_pct"))
    d5, d20 = _num(c.get("change_5d_pct")), _num(c.get("change_20d_pct"))
    d7, chg = _num(c.get("change_7d")), _num(c.get("change_pct"))
    rs, sm = _num(c.get("rel_strength")), _num(c.get("sector_move"))
    no_vol = _num(c.get("volume_ratio")) is None
    ls, lsr = _num(c.get("long_short_account")), _num(c.get("ls_rel"))
    fb, fbr = _num(c.get("funding_bp")), _num(c.get("funding_rel"))
    taker = _num(c.get("taker_buy_sell"))
    kimchi = _num(c.get("kimchi_rel"))
    cot_side = c.get("cot_side") or ""
    inv = c.get("inv_state") or ""
    curve = c.get("curve_shape") or ""
    # COT는 주 1회라 가격도 주간 기준으로 맞춰 본다 (read.cot_flow의 전제).
    cflow = read.cot_flow(_num(c.get("change_5d_pct")),
                          _num(c.get("cot_net_change")))[0]

    flow = _flow(c)
    crowd = read.crowd_gap(_num(c.get("long_account_pct")),
                           _num(c.get("long_top_pct")))[0]
    # 미장은 수급도 펀더멘털도 없다(야후 quoteSummary 401). 거래량이 그
    # 자리를 대신한다 — read.volume_flow가 그러라고 있는 함수다.
    vflow = read.volume_flow(_num(c.get("change_pct")),
                             _num(c.get("volume_ratio")))[0]

    return _side([
        # --- 누가 사고 있나 (국장)
        _sig(fn, 1 if (fn or 0) > 0 else -1,
             f"외국인 수급이 이 스냅샷 중간값보다 "
             f"{'많음' if (fn or 0) > 0 else '적음'}"),
        _sig(on, 1 if (on or 0) > 0 else -1,
             f"기관 수급이 이 스냅샷 중간값보다 "
             f"{'많음' if (on or 0) > 0 else '적음'}"),
        # 쌍끌이는 한쪽만 사는 것과 무게가 다르다. 받아 줄 주체가 둘이다.
        _sig((rawf or 0) > 0 and (rawo or 0) > 0, 2,
             "외국인·기관이 함께 순매수"),
        _sig((rawf or 0) < 0 and (rawo or 0) < 0, -2,
             "외국인·기관이 함께 순매도"),
        _sig(fs >= STREAK_STRONG, 1, f"외국인 {fs}일 연속 순매수"),
        _sig(fs <= -STREAK_STRONG, -1, f"외국인 {abs(fs)}일 연속 순매도"),
        _sig(os_ >= STREAK_STRONG, 1, f"기관 {os_}일 연속 순매수"),
        _sig(os_ <= -STREAK_STRONG, -1, f"기관 {abs(os_)}일 연속 순매도"),
        _sig(rd is not None and rd >= 0.1, 1,
             f"외국인 지분율 변화가 중간값보다 {rd:+.2f}%p" if rd else ""),
        _sig(rd is not None and rd <= -0.1, -1,
             f"외국인 지분율 변화가 중간값보다 {rd:+.2f}%p" if rd else ""),

        # --- 이익 전망·뉴스
        # 중간값 대비라 '좋다/나쁘다'로 쓰면 절대 판단으로 읽힌다. 실제로
        # NAVER는 추정PER 19.09배 대 현재 19.62배로 이익 전망이 나쁜 게
        # 아니라 평범한 것인데, 반도체가 중간값을 -28.6%까지 끌어내려
        # 상대적으로 뒤처진 축이 된 것뿐이다. 앞섬/뒤처짐으로 쓴다.
        _sig(gap is not None and gap <= -PER_GAP_REL, 1,
             "이익 증가 전망이 이 스냅샷에서 앞선 축"),
        _sig(gap is not None and gap >= PER_GAP_REL, -1,
             "이익 증가 전망이 이 스냅샷에서 뒤처진 축"),
        _sig(news, 1 if (news or 0) > 0 else -1,
             f"뉴스 규칙 판정 {'호재' if (news or 0) > 0 else '악재'} 쪽"),
        # 공시는 확정 사실이라 뉴스보다 한 칸 무겁다.
        _sig(disc, 2 if (disc or 0) > 0 else -2,
             f"공시 {'호재' if (disc or 0) > 0 else '악재'} — {disc_title}"),

        # --- 거래량이 방향을 받쳐 주는가
        _sig(vflow == "실수요 동반", 2, "거래량이 평소의 1.5배 넘게 붙으며 올랐음"),
        _sig(vflow == "투매", -2, "거래량이 크게 늘면서 빠졌음"),
        _sig(vflow == "거래 없이 오름", -1, "한산한데 가격만 올랐음"),
        _sig(vflow == "관심 소멸", -1, "거래도 줄고 가격도 빠졌음"),

        # --- 추세가 정렬돼 있는가
        _sig(d5 is not None and d20 is not None and d5 > 0 and d20 > 0, 1,
             "5일·20일 추세가 둘 다 상승"),
        _sig(d5 is not None and d20 is not None and d5 < 0 and d20 < 0, -1,
             "5일·20일 추세가 둘 다 하락"),
        _sig(ma is not None and ma60 is not None and ma > 0 and ma60 > 0, 1,
             "20일선·60일선 위"),
        _sig(ma is not None and ma60 is not None and ma < 0 and ma60 < 0, -1,
             "20일선·60일선 아래"),
        # 7일·당일 추세. 이걸 빼 두면 신호가 네댓 개뿐인 대상(WTI원유는
        # 재고+1·커브+1·COT-1·20일선-1로) 매번 정확히 0으로 상쇄돼
        # 방향이 영영 안 잡힌다. 실측에서 14번 중 12번이 그랬다.
        _sig(d7 is not None and d7 >= TREND_MIN, 1,
             f"7일 {d7:+.1f}%" if d7 is not None else ""),
        _sig(d7 is not None and d7 <= -TREND_MIN, -1,
             f"7일 {d7:+.1f}%" if d7 is not None else ""),
        # 당일 등락은 **거래량이 없을 때만** 센다. 거래량이 있으면
        # read.volume_flow가 이미 같은 등락을 거래량과 묶어 판정하므로,
        # 여기서 또 세면 하루 급등 하나가 두 번 계산된다. 코인에는
        # volume_ratio가 없어 그쪽에서만 켜진다.
        _sig(no_vol and chg is not None and chg >= TREND_MIN, 1,
             f"당일 {chg:+.1f}%" if chg is not None else ""),
        _sig(no_vol and chg is not None and chg <= -TREND_MIN, -1,
             f"당일 {chg:+.1f}%" if chg is not None else ""),
        # 미장 전용 — 시장 전체 대비 상대강도와 섹터 흐름
        _sig(rs is not None and rs >= REL_STRENGTH, 1,
             f"20일 기준 S&P500보다 {rs:+.1f}%p 앞섬" if rs is not None else ""),
        _sig(rs is not None and rs <= -REL_STRENGTH, -1,
             f"20일 기준 S&P500보다 {rs:+.1f}%p 뒤짐" if rs is not None else ""),
        _sig(sm is not None and sm >= SECTOR_MOVE, 1,
             f"섹터가 통째로 {sm:+.2f}%" if sm is not None else ""),
        _sig(sm is not None and sm <= -SECTOR_MOVE, -1,
             f"섹터가 통째로 {sm:+.2f}%" if sm is not None else ""),

        # --- 얼마나 올라와 있나 (극단은 반대로 읽는다)
        _sig(ma is not None and ma >= MA20_STRONG, -1,
             f"20일선 위 {ma:+.1f}% — 되돌릴 자리" if ma is not None else ""),
        _sig(ma is not None and ma <= -MA20_STRONG, 1,
             f"20일선 아래 {ma:+.1f}% — 눌려 있음" if ma is not None else ""),
        _sig(p52 is not None and p52 >= POS52_HIGH, -1,
             f"1년 범위에서 {read.pos_52w(p52)}" if p52 is not None else ""),
        _sig(p52 is not None and p52 <= POS52_LOW, 1,
             f"1년 범위에서 {read.pos_52w(p52)}" if p52 is not None else ""),
        _sig(hi is not None and hi <= -HIGH_REL, 1,
             f"52주 고점 대비가 중간값보다 {hi:+.1f}%p — 더 눌려 있음"
             if hi is not None else ""),
        _sig(hi is not None and hi >= HIGH_REL, -1,
             f"52주 고점 대비가 중간값보다 {hi:+.1f}%p — 덜 내려옴"
             if hi is not None else ""),

        # --- 코인 포지셔닝
        _sig(flow == "신규 자금", 2, "가격도 포지션도 늘어남 — 신규 자금"),
        _sig(flow == "물타기", -2, "빠지는데 포지션이 늘어남 — 청산 위험"),
        _sig(flow == "숏 커버링", 1, "오르지만 포지션은 줄어 지속성은 약함"),
        _sig(flow == "디레버리징", -1, "빠지면서 포지션도 정리 중"),
        _sig(crowd.startswith("큰손이"), 2, f"{crowd}"),
        _sig(crowd.startswith("소매만"), -2, f"{crowd} — 큰손과 반대"),
        _sig(lsr is not None and lsr >= LS_REL, -1,
             f"롱이 숏의 {ls}배 — 이 스냅샷에서 롱으로 쏠린 쪽"
             if ls is not None else ""),
        _sig(lsr is not None and lsr <= -LS_REL, 1,
             f"롱이 숏의 {ls}배 — 이 스냅샷에서 숏으로 쏠린 쪽"
             if ls is not None else ""),
        _sig(fbr is not None and fbr >= FUNDING_REL, -1,
             f"펀딩비 {fb:+.2f}bp — 중간값보다 {fbr:+.2f}bp 높아 롱 과열"
             if fb is not None else ""),
        _sig(fbr is not None and fbr <= -FUNDING_REL, 1,
             f"펀딩비 {fb:+.2f}bp — 중간값보다 {fbr:+.2f}bp 낮아 숏 과열"
             if fb is not None else ""),
        _sig(taker is not None and taker > 1.1, 1, f"테이커 매수/매도 {taker}"),
        _sig(taker is not None and taker < 0.9, -1, f"테이커 매수/매도 {taker}"),
        _sig(kimchi is not None and kimchi > 0.3, 1,
             f"김치프리미엄이 중간값보다 {kimchi:+.2f}%p 높음" if kimchi else ""),
        _sig(kimchi is not None and kimchi < -0.3, -1,
             f"김치프리미엄이 중간값보다 {kimchi:+.2f}%p 낮음" if kimchi else ""),

        # --- 매크로
        # 투기 포지션이 한쪽으로 쏠렸으면 반전 시 청산이 연쇄한다.
        _sig(cot_side == "롱 쏠림", -1, f"투기 포지션 {cot_side} — 청산 붙기 쉬움"),
        _sig(cot_side == "숏 쏠림", 1, f"투기 포지션 {cot_side} — 되돌릴 자리"),
        _sig(inv == "타이트", 1, "재고 부족 — 공급자 우위"),
        _sig(inv == "과잉", -1, "재고 넘침 — 수요자 우위"),
        # 커브는 '기대'다. 원월이 비싼 것 자체는 보관비라 신호가 아니고
        # (read.curve_shape가 '정상'으로 접는다) 폭이 벌어져야 뜻이 생긴다.
        _sig(curve in ("공급 빠듯", "공급 다소 빠듯"), 1,
             f"선물 커브 {curve} — 지금 물건이 나중보다 비쌈"),
        _sig(curve == "공급 과잉", -1, "선물 커브 공급 과잉 — 지금 물건이 남음"),
        # COT 순포지션의 주간 변화. 절대 수준보다 방향이 중요할 때가 많다.
        _sig(cflow == "신규 롱 유입", 1, "투기 포지션이 늘면서 올랐음"),
        _sig(cflow == "숏 커버링", 1, "올랐지만 투기 포지션은 줄어 지속성은 약함"),
        _sig(cflow == "물타기", -1, "빠지는데 투기 롱이 늘어 청산 위험"),
        _sig(cflow == "포지션 정리", -1, "빠지면서 투기 포지션도 줄었음"),
        # 매크로 기록에는 60일선도 거래량도 없어 신호가 두세 개뿐이다.
        # 지표는 주식보다 진폭이 작으니 20일선 이격도 더 낮은 선에서 센다.
        _sig(ma is not None and ma >= MA20_MACRO and ma < MA20_WEAK, 1,
             f"20일선 위 {ma:+.1f}%" if ma is not None else ""),
        _sig(ma is not None and ma <= -MA20_MACRO and ma > -MA20_WEAK, -1,
             f"20일선 아래 {ma:+.1f}%" if ma is not None else ""),
    ])


def _breaks(c):
    """근거가 깨지는 지점. 반환: [(거리%, 설명), ...] 가까운 순.

    일률적인 손절선(-3% 같은)은 그 종목이 왜 뽑혔는지와 무관하다. 깨져도
    무엇이 깨진 것인지 알 수 없어 다음 판정에 쓸 수가 없다. 각 근거는
    이미 자기 조건을 갖고 있으므로 그 값을 그대로 낸다.

    **매도 지시가 아니라 근거 무효화 조건이다.** 무엇을 할지는 읽는 쪽 몫이다.
    """
    out = []
    price = _num(c.get("price"))

    for key, label in (("vs_ma20_pct", "20일선"), ("vs_ma60_pct", "60일선")):
        v = _num(c.get(key))
        if v is None or v <= 0:
            continue          # 이미 아래면 그 근거는 애초에 안 켜졌다
        # 현재가에서 이동평균까지 몇 % 인가. +24%면 -19.4%다(1/1.24-1).
        gap = round((1 / (1 + v / 100) - 1) * 100, 1)
        line = f"{label}이 무너지면 (지금보다 {gap:+.1f}%"
        if price:
            # 원화는 소수점이 의미가 없고 달러는 필요하다. 자릿수로 가른다.
            at = price * (1 + gap / 100)
            line += f", 약 {at:,.0f}" if at >= 1000 else f", 약 {at:,.2f}"
        out.append((abs(gap), line + ")"))

    vr = _num(c.get("volume_ratio"))
    if vr is not None and vr >= 1.2:
        out.append((999, f"거래량이 20일 평균 아래로 내려가면 (지금 {vr}배)"))

    for key, who in (("foreign_streak", "외국인"), ("organ_streak", "기관")):
        n = c.get(key) or 0
        if abs(n) >= STREAK_STRONG:
            side = "순매수" if n > 0 else "순매도"
            flip = "순매도" if n > 0 else "순매수"
            out.append((998, f"{who}이 {abs(n)}일 연속 {side}를 끊고 "
                             f"{flip}로 돌면"))

    rs = _num(c.get("rel_strength"))
    if rs is not None and rs >= REL_STRENGTH:
        out.append((997, f"20일 기준 S&P500 대비 앞선 폭이 "
                         f"{REL_STRENGTH}%p 밑으로 좁혀지면 (지금 {rs:+.1f}%p)"))

    out.sort(key=lambda x: x[0])
    return out


def _caution(c, n_signals):
    """점수에는 안 넣지만 글에 반드시 남겨야 하는 것.

    예정된 실적은 상승 근거가 아니다 — 오를 이유가 아니라 결과에 달렸다는
    뜻이라 근거로 세면 안 되고, 그렇다고 빼놓으면 뒤집힐 자리를 모른 채
    읽게 된다.
    """
    out = []
    if c.get("event_today"):
        out.append(f"이번 장에 결판나는 재료가 있음 — {c['event_today']}")
    if c.get("event_soon"):
        out.append(f"곧 결판나는 재료가 있음 — {c['event_soon']}")
    if c.get("broken_pair"):
        out.append(f"{c['broken_pair']} — 통상 관계가 깨진 상태라 "
                   f"평소 경험칙이 안 통할 수 있음")
    vr = _num(c.get("volume_ratio"))
    if vr is not None and vr < 0.8:
        out.append(f"거래량이 20일 평균의 {vr}배로 한산함 — 근거가 얇음")
    if n_signals < 3:
        out.append(f"근거가 {n_signals}개뿐임")
    if c.get("caveat"):
        out.append(c["caveat"])
    return out




# ---------------------------------------------------------------- 조립
# 중간값 대비로 바꿀 값들 — 원본 → 결과 키
RELATIVE = {
    "kimchi_pct": "kimchi_rel",
    "per_gap_pct": "per_gap_rel",
    "from_52w_high_pct": "from_52w_high_rel",
    "foreign_net_5d": "foreign_net_rel",
    "organ_net_5d": "organ_net_rel",
    "foreign_ratio_delta": "foreign_ratio_rel",
    "funding_bp": "funding_rel",
    "long_short_account": "ls_rel",
}


def _relative(cands):
    """절대 수준이 시장 전체의 상수인 값을 중간값 대비로 바꾼다.

    **모두에게 켜지는 신호는 신호가 아니라 상수다.** 실측으로 확인한 것:

      김치프리미엄     전 코인이 -0.35% 언저리 — 그건 환율 얘기지
                       개별 코인 얘기가 아니다
      추정PER 갭       국장 266개 중 92%가 음수, 중간값 -28.6%.
                       '-20% 이하면 이익 증가'로 세면 3분의 2가 +1을
                       받아 국장 방향이 57개 중 54개 '상승 쪽'이 됐다
      52주 고점 대비   국장은 100%가 음수(최대 -12.5%)라 절대 기준으로는
                       아무것도 가르지 못한다
      외국인·기관 수급 양수가 각각 58%·69%다. 스크리너가 거래대금 상위와
                       급등을 뽑으니 사들여지는 쪽으로 기운 표본이라
                       부호를 그대로 세면 방향이 늘 '상승'이 된다

    중간값에서 얼마나 떨어졌는지가 그 종목에 대한 정보다. "샀는가"가 아니라
    "오늘 이 종목이 남들보다 사들여지고 있는가"를 묻는 것이라, 표본이
    어느 쪽으로 기울어도 판정이 한쪽으로 굳지 않는다.

    거래소가 바뀌면 펀딩비·롱숏비의 절대 수준이 달라진다는 것도 같은
    이유 — 크기는 같은 스냅샷 안에서만 본다.

    **원본 값은 그대로 둔다.** 5일 누적과 연속 방향이 어긋나는지(손바뀜)
    같은 모순 판정은 실제 부호를 봐야 하므로 상대값으로 바꾸면 안 된다.
    """
    for key, out in RELATIVE.items():
        xs = [_num(c.get(key)) for c in cands]
        xs = [x for x in xs if x is not None]
        if len(xs) < 3:
            continue
        mid = statistics.median(xs)
        for c in cands:
            v = _num(c.get(key))
            if v is not None:
                c[out] = round(v - mid, 3)
    return cands


def _take(scored, want, per_group, groups, topics, ok):
    """조건에 맞는 것을 위에서부터 담되 업종·사실 중복은 거른다."""
    out = []
    for p in scored:
        if len(out) >= want:
            break
        if not ok(p) or p.get("taken"):
            continue
        g = p["group"]
        # 반도체 3형제가 세 자리를 다 먹으면 그건 픽 3개가 아니라 1개다.
        if g and groups.get(g, 0) >= per_group:
            continue
        # 같은 사실이 두 자리를 먹는 것도 막는다. '금 vs 미10년물 관계가
        # 깨졌다'는 금에서 한 번, 미10년물에서 한 번 잡히지만 한 사실이다.
        if p["topic"] and p["topic"] in topics:
            continue
        p["taken"] = True
        out.append(p)
        groups[g] = groups.get(g, 0) + 1
        if p["topic"]:
            topics.add(p["topic"])
    return out


def compute(cands, market="kr", top_n=TOP_N, per_group=PER_GROUP,
            partial=False):
    """후보 전체를 같은 잣대로 재서 3종을 고른다.

    주식(국장·미장)과 선물(코인·매크로)은 고르는 목적이 다르다.

      주식   살 수 있는 쪽이 한 방향뿐이므로 **오를 근거가 두꺼운 것**만
             올린다. 상승 후보가 모자라면 남는 칸은 '피할 것'으로 채우고
             그렇게 표시한다 — 들고 있는 종목이 거기 있으면 쓸모가 있다.
      선물   양방향이 다 의미가 있으므로 **방향이 뚜렷한 것**을 올린다.
             오르든 내리든 근거가 두꺼우면 픽이다.

    어느 쪽이든 0 근처(근거가 없거나 맞서는 것)는 빠진다.

    반환: (픽 리스트, 탈락 리스트)
    """
    _relative(cands)

    scored, dropped = [], []
    for c in cands:
        why = gate(c, partial)
        if why:
            dropped.append({"label": c.get("label"), "why": why})
            continue

        score, why_list, split = _bull(c)
        scored.append({
            "key": c.get("key") or "",
            "label": c.get("label"),
            "group": c.get("group") or "",
            "topic": c.get("topic") or "",
            "reasons": c.get("reasons") or [],
            "score": score,
            "why": why_list,
            "split": split,
            "caution": _caution(c, len(why_list)),
            "breaks": _breaks(c),
            "turnover": _num(c.get("turnover")) or 0,
            "kind": "",
            "weak": False,
        })

    # 근거가 두꺼운 순. 동점이면 신호 개수, 그다음 거래대금.
    scored.sort(key=lambda p: (p["score"], len(p["why"]), p["turnover"]),
                reverse=True)

    # 고정 대상이 정해진 자산군은 고르지 않는다. 정해진 것의 방향만 낸다.
    # 점수가 낮으면 빼는 대신 '방향 안 잡힘'으로 표시한다 — 오늘 방향이
    # 없다는 것도 알아야 할 상태다.
    focus = FOCUS.get(market)
    if focus:
        by_key = {p["key"]: p for p in scored}
        picks = []
        for k in focus:
            p = by_key.get(k)
            if not p:
                dropped.append({"label": k, "why": "이 스냅샷에 없음"})
                continue
            p["kind"] = ("상승" if p["score"] >= DIR_MIN else
                         "하락" if p["score"] <= -DIR_MIN else "팽팽")
            picks.append(p)
        return picks, dropped

    groups, topics = {}, set()

    if MODE.get(market) == "futures":
        by_strength = sorted(scored, key=lambda p: (abs(p["score"]),
                                                    len(p["why"])),
                             reverse=True)
        picks = _take(by_strength, top_n, per_group, groups, topics,
                      lambda p: abs(p["score"]) >= MIN_SCORE)
        # 모자라는 자리만 한 단계 낮은 근거로 채우고 그 자리를 표시한다.
        if len(picks) < top_n:
            weak = _take(by_strength, top_n - len(picks), per_group,
                         groups, topics,
                         lambda p: abs(p["score"]) >= FALLBACK_SCORE)
            for p in weak:
                p["weak"] = True
            picks += weak
        for p in picks:
            p["kind"] = "상승" if p["score"] > 0 else "하락"
        return picks, dropped

    picks = _take(scored, top_n, per_group, groups, topics,
                  lambda p: p["score"] >= MIN_SCORE)
    for p in picks:
        p["kind"] = "상승"

    # 상승 후보가 모자라면 남는 칸은 '피할 것'으로 채운다. 내릴 근거가
    # 두꺼운 종목이라 오를 종목과 섞으면 안 된다.
    if len(picks) < top_n:
        avoid = _take(sorted(scored, key=lambda p: (p["score"], -len(p["why"]))),
                      top_n - len(picks), per_group, groups, topics,
                      lambda p: p["score"] <= -MIN_SCORE)
        for p in avoid:
            p["kind"] = "피할 것"
        picks += avoid

    # 그래도 모자라면 한 단계 낮은 상승 근거로 채우고 표시한다.
    if len(picks) < top_n:
        weak = _take(scored, top_n - len(picks), per_group, groups, topics,
                     lambda p: p["score"] >= FALLBACK_SCORE)
        for p in weak:
            p["kind"], p["weak"] = "상승", True
        picks += weak

    return picks, dropped


# ---------------------------------------------------------------- 어댑터
# 자산군마다 원자료의 모양이 다르다. 여기서 공통 후보로 옮기고, 채점은
# 위의 한 벌이 전부 맡는다. 채점 규칙을 자산군별로 두면 넷이 어긋난다.

def _days(day, offset):
    """수집일 기준 며칠 뒤(앞)의 날짜 문자열."""
    try:
        d = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    return (d + dt.timedelta(days=offset)).isoformat()


def from_kr(b):
    """국장 — 외국인·기관 수급이 가장 정보량이 큰 축이다."""
    day = (b.get("collected_at") or "")[:10]
    prev = _days(day, -1)
    dart = b.get("dart") or {}

    news = {}
    for n in b.get("news_selected") or []:
        for a in n.get("assets") or []:
            # 예전 스냅샷은 (코드, 이름) 2튜플이라 근거 칸이 없다.
            # collect_kr.py가 같은 자리에서 같은 방식으로 물러선다.
            via = a[2] if len(a) > 2 else "직접"
            if via == "직접":     # 섹터 연관으로 묶인 것은 근거가 약하다
                news[a[0]] = news.get(a[0], 0) + (n.get("score") or 0)

    out = []
    for st in b.get("stocks") or []:
        code = st.get("code")
        if st.get("error"):
            out.append({"label": st.get("name") or code,
                        "failed": "종목 조회 실패"})
            continue

        g = st.get("signals") or {}
        trend = st.get("trend") or []
        chg = None
        if len(trend) >= 2 and trend[0].get("close") and trend[1].get("close"):
            chg = round((trend[0]["close"] / trend[1]["close"] - 1) * 100, 2)

        ds = st.get("disclosures") or []
        today = next((d for d in ds if (d.get("datetime") or "")[:10] == day), None)
        soon = next((d for d in ds if (d.get("datetime") or "")[:10] == prev), None)

        # 공시는 뉴스와 달리 확정 사실이라 따로 센다. 최근 것 중 방향이
        # 가장 센 하나만 쓴다 — 여러 건을 더하면 공시가 많은 대형주가
        # 그것만으로 이긴다.
        scored = [(rules.score_disclosure(d.get("title") or "")[0], d)
                  for d in ds[:5]]
        scored = [(s, d) for s, d in scored if s]
        disc_score, disc_top = (max(scored, key=lambda x: abs(x[0]))
                                if scored else (0, None))

        # DART가 이 종목만 실패했으면 공시·내부자 축이 통째로 빈다.
        # 점수가 낮게 나온 이유가 '조용해서'가 아니라 '못 받아서'일 수 있다.
        dd = dart.get(code)
        caveat = ("DART 조회 실패 — 공시·내부자 거래를 못 받았다"
                  if dart and (not dd or dd.get("error")) else None)

        out.append({
            "key": code,
            "label": f"{st.get('name')} ({code})",
            "group": st.get("industry") or "",
            "reasons": st.get("reasons") or [],
            "turnover": st.get("turnover"),
            "caveat": caveat,
            "change_pct": chg,
            "price": (trend[0].get("close") if trend else None),
            "volume_ratio": g.get("volume_ratio"),
            "vs_ma20_pct": g.get("vs_ma20_pct"),
            "from_52w_high_pct": g.get("from_52w_high_pct"),
            "per_gap_pct": g.get("per_gap_pct"),
            "foreign_net_5d": g.get("foreign_net_5d"),
            "foreign_streak": g.get("foreign_streak"),
            "organ_net_5d": g.get("organ_net_5d"),
            "organ_streak": g.get("organ_streak"),
            "foreign_ratio_delta": g.get("foreign_ratio_delta"),
            "news_score": news.get(code),
            "disc_score": disc_score,
            "disc_title": (disc_top or {}).get("title"),
            "event_today": f"오늘 공시 — {today['title']}" if today else None,
            "event_soon": f"어제 공시 — {soon['title']}" if soon else None,
        })
    return out


def from_us(b):
    """미장 — 펀더멘털이 없다(야후 quoteSummary 401). 위치와 거래량으로 잰다."""
    day = (b.get("collected_at") or "")[:10]
    nxt = _days(day, 1)

    earn = {}
    for e in b.get("earnings") or []:
        earn.setdefault(e.get("symbol"), e)

    # 미장은 수급도 펀더멘털도 없어 근거가 얇다. 이미 수집해 둔 것 중
    # 안 쓰던 두 축을 끌어온다 — 새 소스를 붙이는 것보다 먼저 할 일이다.
    #   상대강도: 지수보다 얼마나 앞서는가
    #   섹터 흐름: 그 종목이 속한 섹터가 통째로 어느 쪽인가
    #
    # **상대강도는 20일로 잰다.** 당일로 재면 시장 시총가중 등락률이
    # 0 근처라(실측 -0.03%) 종목 등락률과 사실상 같은 값이 되어, 하루
    # 급등 하나가 '당일 상승'과 '시장 대비 앞섬'으로 두 번 세진다.
    agg = b.get("aggregate") or {}
    bench = ((b.get("indices") or {}).get("S&P500") or {}).get("change_20d_pct")
    bench = _num(bench)
    sector_move = {s["sector"]: s.get("cap_weighted_pct")
                   for s in (agg.get("sectors") or [])}

    news = {}
    for n in b.get("news_selected") or []:
        for t in n.get("tickers") or []:
            news[t] = news.get(t, 0) + (n.get("score") or 0)

    out = []
    for r in b.get("selected") or []:
        sym = r.get("symbol")
        e = earn.get(sym)
        ed = (e or {}).get("date")
        d20 = _num(r.get("change_20d_pct"))
        out.append({
            "rel_strength": (round(d20 - bench, 2)
                             if d20 is not None and bench is not None else None),
            "sector_move": _num(sector_move.get(r.get("sector"))),
            "key": sym,
            "label": f"{sym} — {r.get('name')}",
            "group": r.get("sector") or "",
            "reasons": r.get("reasons") or [],
            "turnover": r.get("turnover"),
            "change_pct": r.get("change_pct"),
            "change_5d_pct": r.get("change_5d_pct"),
            "change_20d_pct": r.get("change_20d_pct"),
            "price": r.get("price"),
            "volume_ratio": r.get("volume_ratio"),
            "vs_ma20_pct": r.get("vs_ma20_pct"),
            "vs_ma60_pct": r.get("vs_ma60_pct"),
            "pos_52w": r.get("pos_52w"),
            "from_52w_high_pct": r.get("from_52w_high_pct"),
            "news_score": news.get(sym),
            "event_today": (f"오늘 실적 발표 ({e.get('time')}, 예상EPS "
                            f"{e.get('eps_forecast')})") if e and ed == day else None,
            "event_soon": (f"내일 실적 발표 ({e.get('time')})"
                           if e and ed == nxt else None),
        })
    return out


def from_coin(b):
    """코인 — 가치는 가격이 아니라 포지셔닝에 있다.

    펀딩비·롱숏비의 절대 수준은 거래소가 바뀌면 달라진다. 그래서 출처를
    후보마다 달고, 크기 비교는 같은 스냅샷 안에서만 한다.
    """
    day = (b.get("collected_at") or "")[:10]
    src = b.get("derivatives_source", "binance")

    news = {}
    for n in b.get("news_selected") or []:
        for c in n.get("coins") or []:
            news[c] = news.get(c, 0) + (n.get("score") or 0)

    out = []
    for c in b.get("selected") or []:
        sym = c.get("symbol")
        fr = c.get("funding_rate")
        k = c.get("kimchi") or {}
        # 코인에는 실적·공시처럼 시각이 박힌 것이 없다. 뉴스로 대신하되
        # 규칙이 호재·악재로 판정한 것만 센다. "AVAX to USD live" 같은
        # 시세 페이지까지 세면 전 코인이 같은 점수를 받아 변별력이 0이 된다.
        hot_news = [n for n in (b.get("news_selected") or [])
                    if sym in (n.get("coins") or [])
                    and (n.get("published") or "")[:10] == day
                    and (n.get("score") or 0) != 0]
        out.append({
            "key": sym,
            "label": f"{sym} — {c.get('name')} (시총 {c.get('rank')}위)",
            "group": "",          # 이 데이터에 섹터 분류가 없다
            "reasons": c.get("reasons") or [],
            "turnover": c.get("turnover"),
            "rank": c.get("rank"),
            "caveat": f"파생 지표 출처 {src.upper()} — 절대 수준은 다른 "
                      f"거래소와 비교하지 마라",
            "change_pct": c.get("change_pct"),
            "change_7d": c.get("change_7d"),
            "funding_bp": fr * 10000 if fr is not None else None,
            "oi_change_7d_pct": c.get("oi_change_7d_pct"),
            "long_short_account": c.get("long_short_account"),
            "long_account_pct": c.get("long_account_pct"),
            "long_top_pct": c.get("long_top_pct"),
            "taker_buy_sell": c.get("taker_buy_sell"),
            "kimchi_pct": k.get("premium_pct"),
            "news_score": news.get(sym),
            "event_soon": (f"오늘자 호재·악재 뉴스 {len(hot_news)}건 — "
                           f"{hot_news[0]['title'][:40]}") if hot_news else None,
        })
    return out


def from_macro(b):
    """매크로 — 종목이 아니라 지표다. 관계가 깨진 자리가 알맹이다."""
    day = (b.get("collected_at") or "")[:10]
    try:
        weekday = dt.date.fromisoformat(day).weekday()
    except (TypeError, ValueError):
        weekday = None

    # 깨진 관계는 쌍의 양쪽에서 각각 잡힌다. 한 사실이므로 같은 쌍 이름을
    # topic으로 달아 두 자리를 먹지 않게 한다.
    broken, topic = {}, {}
    for d in b.get("divergences") or []:
        if not d.get("broken"):
            continue
        for side in ("a", "b"):
            nm = (d.get(side) or {}).get("name")
            if nm:
                broken[nm] = f"통상 {d['expected']}관계인 {d['pair']}가 깨짐"
                topic[nm] = d["pair"]

    # side는 '롱 쏠림'/'숏 쏠림'이다(collectors/commodity.py). 표시 문구에는
    # '롱숏비'가 섞여 들어가므로 부분 문자열로 방향을 가리면 안 되고,
    # 방향은 원래 값을 따로 들고 간다.
    cot, cot_side = {}, {}
    for e in b.get("cot_extremes") or []:
        cot[e["name"]] = (f"투기 포지션 {e['side']} (롱숏비 {e['ratio']}, "
                          f"순포지션이 미결제약정의 {e['net_pct_oi']}%)")
        cot_side[e["name"]] = e["side"]

    # state는 '타이트'/'과잉'이다(collectors/eia.py). read.inventory_state가
    # 그걸 사람 말로 옮긴다 — '타이트'를 '부족'으로 찾으면 안 걸린다.
    inv = {r["name"]: r.get("state")
           for r in (b.get("inventory_readings") or [])}

    # 선물 커브와 COT 순포지션 주간 변화. 매크로에서 가장 정보량이 큰 두
    # 축인데 안 쓰면 지표당 근거가 두 개뿐이라 픽이라 부르기 어렵다.
    # 재고는 '사실', 커브는 '기대', COT는 '포지션'이라 서로 다른 것을 잰다.
    curves = {}
    for name, cv in (b.get("curves") or {}).items():
        if not cv.get("monotonic"):
            continue      # 비단조는 계절성이라 단순 판정이 안 된다
        curves[name] = read.curve_shape(cv.get("shape"), cv.get("spread_pct"))[0]

    cot_move = {}
    for name, d in (b.get("cot") or {}).items():
        cot_move[name] = d.get("spec_net_change")
    etf_vol = {n: e.get("volume_ratio")
               for n, e in (b.get("commodity_etfs") or {}).items()}

    news = {}
    for n in b.get("news_selected") or []:
        for grp in n.get("groups") or []:
            news[grp] = news.get(grp, 0) + (n.get("score") or 0)

    out = []
    for r in b.get("records") or []:
        name = r.get("name")
        if r.get("error"):
            out.append({"label": name, "failed": "조회 실패"})
            continue

        # 원유 재고 서프라이즈는 화·수요일에만 들어온다 (API·EIA 발표일).
        # 다른 요일에 이 자리가 비는 것은 정상이다.
        oil = name in inv or "원유" in name or "천연가스" in name
        state = read.inventory_for(name, inv)
        out.append({
            "key": name,
            "label": name,
            "group": r.get("group") or "",
            # '평년 수준'은 선별 사유가 아니다. 부족·넘침일 때만 남긴다.
            "reasons": [x for x in [read.inventory_state(state, 1)[0]]
                        if x and x != "평년 수준"],
            "inv_state": state,
            "cot_side": cot_side.get(name),
            "curve_shape": curves.get(name),
            "cot_net_change": cot_move.get(name),
            "change_pct": r.get("change_pct"),
            "change_5d_pct": r.get("change_5d_pct"),
            "change_20d_pct": r.get("change_20d_pct"),
            "volume_ratio": etf_vol.get(name),
            "vs_ma20_pct": r.get("vs_ma20_pct"),
            "pos_52w": r.get("pos_52w"),
            "cot_extreme": cot.get(name),
            "broken_pair": broken.get(name),
            "topic": topic.get(name),
            "news_score": news.get(r.get("group")),
            "event_today": ("EIA 주간 재고 발표일"
                            if oil and weekday in (1, 2) else None),
        })
    return out


BY_MARKET = {"kr": from_kr, "us": from_us, "coin": from_coin, "macro": from_macro}


def block(market, bundle, partial=None):
    """수집기가 부르는 입구. 프롬프트에 붙일 텍스트를 돌려준다.

    partial(장중 수집이라 거래량이 덜 찼는가)은 넘기지 않으면 여기서
    장 상태로 판단한다. 수집기 넷이 각자 계산하면 하나가 틀려도 모른다.
    """
    adapt = BY_MARKET.get(market)
    if not adapt:
        return ""
    if partial is None:
        partial = "장중" in (session.describe(market).get("state") or "")
    picks, dropped = compute(adapt(bundle), market=market, partial=partial)
    return render(picks, dropped, market)


# ---------------------------------------------------------------- 출력
def render(picks, dropped, market="kr"):
    """프롬프트에 넣을 블록. 글 쓰는 쪽은 이 결과를 서술만 한다."""
    futures = MODE.get(market) == "futures"
    focus = FOCUS.get(market)
    what = "방향이 뚜렷한" if futures else "오를 근거가 두꺼운"

    L = [f"\n## 오늘의 픽 {len(picks)}종 (규칙으로 계산한 결과)"]
    if not picks:
        L.append(f"**{what} 후보가 {FALLBACK_SCORE}점 기준도 넘지 못했다.** 픽을")
        L.append("지어내지 말고 '오늘은 근거가 쌓인 대상이 없었습니다'라고 쓰라.")
        if dropped:
            L.append("게이트 탈락:")
            for d in dropped[:8]:
                L.append(f"- {d['label']}: {d['why']}")
        return "\n".join(L)

    if focus:
        L.append(f"**대상은 {' · '.join(focus)}로 고정돼 있다.** 고른 것이 아니라")
        L.append("정해진 것의 방향을 낸 것이다. 다른 종목을 끌어오지 말고,")
        L.append("'팽팽'이 나왔으면 억지로 한쪽을 고르지 말고 그대로 써라 —")
        L.append("양쪽 근거가 맞선다는 것도 알아야 할 상태다.")
    else:
        L.append(f"이 스냅샷의 후보 전체를 같은 잣대로 재서 **{what}** 순으로 골랐다.")
        L.append("**순서를 바꾸거나 다른 대상으로 갈아치우지 마라.** 근거가 약하다고")
        L.append("판단되면 그 사실을 글에 적어라 — 조용히 바꾸는 것이 제일 나쁘다.")
    L.append("점수는 상승 근거를 부호 있게 더한 값이다. 양수가 클수록 오를")
    L.append("근거가, 음수가 클수록 내릴 근거가 두껍다. 0 근처는 근거가 없거나")
    L.append("서로 맞선다는 뜻이라 애초에 픽에서 빠진다.")

    avoid = [p for p in picks if p["kind"] == "피할 것"]
    if avoid:
        L.append(f"\n**상승 후보가 {TOP_N - len(avoid)}개뿐이라 나머지 {len(avoid)}칸은"
                 f" '피할 것'으로 채웠다.** 이건 오를 종목이 아니라 내릴 근거가"
                 f" 두꺼운 종목이다. 반드시 그렇게 구분해서 쓰고, 상승 픽과"
                 f" 섞어서 나열하지 마라.")

    for i, p in enumerate(picks, 1):
        mark = {"상승": "상승 근거", "하락": "하락 근거",
                "팽팽": "**팽팽** — 양쪽 근거가 정확히 맞섬",
                "피할 것": "**피할 것** — 내릴 근거"}[p["kind"]]
        L.append(f"\n### {i}. {p['label']} — {mark} {p['score']:+d}점")
        if p["reasons"]:
            L.append(f"- 선별 사유: {', '.join(p['reasons'])}")
        L.append("- 근거: " + (" / ".join(p["why"]) or "없음"))
        if p.get("weak"):
            L.append(f"- ※ **{MIN_SCORE}점을 넘긴 후보가 모자라 채운 자리다.**"
                     f" 앞의 픽과 같은 무게로 쓰지 말고, 근거가 그만큼"
                     f" 얇다는 사실을 글에 함께 적어라.")
        if p.get("breaks"):
            L.append("- 근거가 깨지는 지점: "
                     + " / ".join(t for _, t in p["breaks"]))
        if p["split"]:
            L.append("- ※ 반대 근거도 함께 있다. 위 목록의 부호를 보고 "
                     "양쪽을 다 적어라 — 한쪽만 옮기면 글이 데이터보다 세진다.")
        for w in p["caution"]:
            L.append(f"- ※ {w}")

    if dropped:
        L.append(f"\n※ 게이트에서 걸러진 후보 {len(dropped)}개: "
                 + ", ".join(f"{d['label']}({d['why']})" for d in dropped[:5]))
        L.append("  이들은 데이터가 모자라 뺀 것이지 볼 것이 없다는 뜻이 아니다.")

    return "\n".join(L)
