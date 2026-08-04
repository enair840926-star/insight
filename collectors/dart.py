# -*- coding: utf-8 -*-
"""전자공시 OPENDART

네이버 공시가 못 주는 것들:
  - 임원·주요주주 소유보고 (내부자 매매)
  - 대량보유 상황보고 (5%룰 — 기관/펀드 지분 변동)
  - 정식 공시 원문 링크
  - 전체 상장사 목록 (종목코드 <-> DART 고유번호 매핑)

DART는 종목코드가 아니라 8자리 고유번호(corp_code)를 쓴다.
매핑표는 corpCode.xml(ZIP)로 한 번 받아 캐시한다.
"""
import io
import json
import time
import zipfile
import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

from core import env
from core.http import fetch_json

BASE = "https://opendart.fss.or.kr/api"
CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE.mkdir(exist_ok=True)
CORP_CACHE = CACHE / "corp_codes.json"
CORP_CACHE_DAYS = 7

# DART 응답 status 코드
_STATUS = {
    "000": "정상",
    "010": "등록되지 않은 인증키",
    "011": "사용할 수 없는 인증키 (승인 대기 또는 정지)",
    "012": "접근할 수 없는 IP",
    "013": "조회된 데이터 없음",
    "014": "파일이 존재하지 않음",
    "020": "요청 제한 초과 (일 20,000건)",
    "021": "조회 가능한 회사 개수 초과",
    "100": "필드 부적절",
    "101": "부적절한 접근",
    "800": "시스템 점검 중",
    "900": "정의되지 않은 오류",
    "901": "적절한 권한이 없음",
}


class DartError(RuntimeError):
    pass


def _key():
    return env.get("DART_API_KEY", required=True)


def _call(path, **params):
    """DART 호출. status가 000이 아니면 사유를 명확히 알려준다."""
    params["crtfc_key"] = _key()
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    j = fetch_json(f"{BASE}/{path}?{qs}")
    if j is None:
        return None
    st = j.get("status")
    if st == "013":          # 데이터 없음은 정상 상황이다
        return {"status": "013", "list": []}
    if st and st != "000":
        raise DartError(f"DART {st}: {_STATUS.get(st, j.get('message', '알 수 없음'))}")
    return j


# ---------------------------------------------------------------- 상장사 매핑
def load_corp_codes(force=False):
    """종목코드 -> DART 고유번호 매핑. 전체 상장사 목록이기도 하다.

    반환: {"005930": {"corp_code": "00126380", "name": "삼성전자"}, ...}
    """
    if CORP_CACHE.exists() and not force:
        age = time.time() - CORP_CACHE.stat().st_mtime
        if age < CORP_CACHE_DAYS * 86400:
            return json.loads(CORP_CACHE.read_text(encoding="utf-8"))

    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": _key()},
                     timeout=60)
    r.raise_for_status()

    # 정상이면 ZIP, 오류면 XML 에러 문서가 온다
    if not r.content[:2] == b"PK":
        try:
            root = ET.fromstring(r.content.decode("utf-8", "ignore"))
            st = (root.findtext("status") or "").strip()
            raise DartError(f"DART {st}: {_STATUS.get(st, root.findtext('message'))}")
        except ET.ParseError:
            raise DartError("corpCode 응답을 해석할 수 없습니다")

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        xml = z.read(z.namelist()[0])

    root = ET.fromstring(xml)
    out = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if not stock or stock == " ":       # 비상장사는 stock_code가 비어있다
            continue
        out[stock] = {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "name": (item.findtext("corp_name") or "").strip(),
        }
    CORP_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------------------------------------------------------- 공시 조회
# 공시 유형 중 주가에 직접 영향이 큰 것들
PBLNTF_TYPES = {
    "A": "정기공시",
    "B": "주요사항보고",
    "C": "발행공시",
    "D": "지분공시",
    "I": "거래소공시",
}


def recent_filings(corp_code=None, days=7, pblntf_ty=None, limit=100):
    """공시 목록. corp_code 없으면 전체 시장 공시."""
    end = dt.date.today()
    bgn = end - dt.timedelta(days=days)
    j = _call("list.json",
              corp_code=corp_code,
              bgn_de=f"{bgn:%Y%m%d}", end_de=f"{end:%Y%m%d}",
              pblntf_ty=pblntf_ty,
              page_no=1, page_count=min(limit, 100),
              last_reprt_at="Y")
    if not j:
        return []
    return [{
        "corp_name": f.get("corp_name"),
        "stock_code": f.get("stock_code"),
        "title": (f.get("report_nm") or "").strip(),
        "date": f.get("rcept_dt"),
        "filer": f.get("flr_nm"),
        "rcept_no": f.get("rcept_no"),
        "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={f.get('rcept_no')}",
    } for f in (j.get("list") or [])]


def insider_trades(corp_code, days=90, limit=30):
    """임원·주요주주 소유주식 보고 — 내부자가 사고 있는지 팔고 있는지.

    경영진의 실제 매매는 어떤 뉴스보다 직접적인 신호다.

    주의: 이 API는 기간 파라미터가 없어 전체 이력을 반환한다
    (삼성전자 3,375건, 2년치). 최신순 정렬 후 기간으로 잘라야 한다.
    """
    j = _call("elestock.json", corp_code=corp_code)
    if not j:
        return []
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = sorted((j.get("list") or []),
                  key=lambda x: x.get("rcept_dt", ""), reverse=True)
    out = []
    for r in rows:
        d = r.get("rcept_dt", "")
        if d < cutoff:
            break
        out.append({
            "date": d,
            "name": r.get("repror"),
            "position": r.get("isu_exctv_ofcps"),
            "registered": r.get("isu_exctv_rgist_at"),
            "is_major_holder": r.get("isu_main_shrholdr") not in ("-", "", None),
            "shares": _num(r.get("sp_stock_lmp_cnt")),
            "delta": _num(r.get("sp_stock_lmp_irds_cnt")),
            "rcept_no": r.get("rcept_no"),
        })
        if len(out) >= limit:
            break
    return out


def summarize_insider(trades):
    """개별 보고를 그대로 LLM에 넘기면 노이즈다. 방향을 집계한다.

    임원 한 명의 200주 매도는 의미 없지만, 같은 날 4명이 동시에
    팔면 그건 신호다.
    """
    if not trades:
        return {}
    buys = [t for t in trades if (t.get("delta") or 0) > 0]
    sells = [t for t in trades if (t.get("delta") or 0) < 0]
    by_date = {}
    for t in trades:
        if t.get("delta"):
            by_date.setdefault(t["date"], []).append(t)
    # 같은 날 3명 이상이 같은 방향으로 움직인 경우
    clusters = []
    for d, group in sorted(by_date.items(), reverse=True):
        if len(group) < 3:
            continue
        net = sum(t["delta"] for t in group)
        same_dir = all((t["delta"] > 0) == (net > 0) for t in group)
        if same_dir:
            clusters.append({
                "date": d, "count": len(group), "net": net,
                "people": [t["name"] for t in group][:6],
            })
    return {
        "report_count": len(trades),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "net_shares": sum(t["delta"] for t in trades if t.get("delta")),
        "latest_date": trades[0]["date"] if trades else None,
        "clusters": clusters[:3],
    }


def major_holders(corp_code, days=365, limit=20):
    """대량보유 상황보고(5%룰) — 기관·펀드·행동주의 지분 변동.

    네이버 '외국인 순매수'는 덩어리지만 이건 보유자 이름이 나온다.
    """
    j = _call("majorstock.json", corp_code=corp_code)
    if not j:
        return []
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = sorted((j.get("list") or []),
                  key=lambda x: x.get("rcept_dt", ""), reverse=True)
    out, seen = [], set()
    for r in rows:
        d = r.get("rcept_dt", "")
        if d < cutoff:
            break
        ratio = _num(r.get("stkrt"))
        holder = r.get("repror")
        # 같은 보고자의 같은 비율 보고가 연달아 오면 중복이다
        sig = (holder, ratio, d)
        if sig in seen:
            continue
        seen.add(sig)
        out.append({
            "date": d,
            "holder": holder,
            "type": r.get("report_tp"),
            "ratio": ratio,
            "ratio_delta": _num(r.get("stkrt_irds")),
            "shares": _num(r.get("stkqy")),
            "shares_delta": _num(r.get("stkqy_irds")),
            # report_resn에 개행이 들어있어 한 줄로 편다
            "reason": " / ".join(
                x.strip(" -") for x in (r.get("report_resn") or "").split("\n")
                if x.strip(" -")),
            "rcept_no": r.get("rcept_no"),
        })
        if len(out) >= limit:
            break
    return out


def _num(s):
    """'-99,646' -> -99646, '19.69' -> 19.69, '-' -> None"""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if not t or t in ("-", "+"):
        return None
    try:
        return float(t) if "." in t else int(t)
    except ValueError:
        return None


# ---------------------------------------------------------------- 일괄
def collect_for_watchlist(watchlist, corp_map, days=7, max_workers=4):
    """관심종목별 DART 정보 수집. 종목당 3회 호출."""
    def job(item):
        code, name = item
        info = corp_map.get(code)
        if not info:
            return code, {"error": f"DART 고유번호 없음 ({name})"}
        cc = info["corp_code"]
        try:
            ins = insider_trades(cc, days=90, limit=30)
            return code, {
                "corp_code": cc,
                "filings": recent_filings(cc, days=days, limit=20),
                "insider": ins[:10],
                "insider_summary": summarize_insider(ins),
                "major": major_holders(cc, days=365, limit=10),
            }
        except DartError as e:
            return code, {"error": str(e)}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        return dict(ex.map(job, watchlist))
