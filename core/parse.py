# -*- coding: utf-8 -*-
"""네이버 응답 파싱 헬퍼

네이버는 숫자를 전부 사람이 읽는 문자열로 준다.
"-3,896,489" / "46.63%" / "19.36배" / "1,400조 1,837억"
"""
import re
import json
import html


def to_int(s):
    """'-3,896,489' -> -3896489, '+8,658,155' -> 8658155"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    t = str(s).replace(",", "").replace("+", "").strip()
    if not t or t in ("-", "N/A"):
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def to_float(s):
    """'46.63%' -> 46.63, '19.36배' -> 19.36, '-8.76' -> -8.76"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = re.sub(r"[^\d.\-+]", "", str(s).replace(",", ""))
    if not t or t in ("-", "+", "."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def korean_amount(s):
    """'1,400조 1,837억' -> 140018370000000 (원)"""
    if not s:
        return None
    t = str(s).replace(",", "").replace(" ", "")
    total = 0
    found = False
    for unit, mul in (("조", 10 ** 12), ("억", 10 ** 8), ("만", 10 ** 4)):
        m = re.search(rf"(\d+){unit}", t)
        if m:
            total += int(m.group(1)) * mul
            found = True
    if not found:
        return to_int(s)
    return total


def clean_text(s):
    """HTML 엔티티/태그 제거. 네이버 뉴스 title에 &quot; 가 그대로 온다."""
    if not s:
        return ""
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", str(s), flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_sise_json(raw):
    """네이버 siseJson.naver 응답은 작은따옴표 섞인 유사 JS 배열이다.
    json.loads가 그대로는 실패하므로 정규화한다.

    입력: [['날짜','시가',...], ["20260803", 248000, ...], ...]
    반환: [{"date":"20260803","open":248000,...}, ...]
    """
    if not raw:
        return []
    txt = raw.strip().replace("'", '"')
    txt = re.sub(r",\s*]", "]", txt)          # 트레일링 콤마
    txt = re.sub(r"\s+", " ", txt)
    try:
        rows = json.loads(txt)
    except ValueError:
        return []
    if not rows or len(rows) < 2:
        return []

    keys = ["date", "open", "high", "low", "close", "volume", "foreign_ratio"]
    out = []
    for row in rows[1:]:                       # 0번은 헤더
        if not isinstance(row, list) or len(row) < 6:
            continue
        rec = dict(zip(keys, row))
        rec["date"] = str(rec.get("date", ""))
        out.append(rec)
    return out


def struct_to_date(st):
    """feedparser의 published_parsed(struct_time) -> 'YYYY-MM-DD HH:MM'
    RSS 날짜 포맷이 매체마다 제각각이라 feedparser가 정규화한 값을 쓴다."""
    if not st:
        return ""
    try:
        return f"{st.tm_year:04d}-{st.tm_mon:02d}-{st.tm_mday:02d} {st.tm_hour:02d}:{st.tm_min:02d}"
    except (AttributeError, TypeError):
        return ""


def date_only(s):
    """'2026-08-03 14:22' -> '2026-08-03'"""
    return (s or "")[:10]


def parse_naver_datetime(s):
    """'202608040039' -> '2026-08-04 00:39'"""
    if not s:
        return ""
    t = str(s)
    if len(t) >= 12 and t.isdigit():
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
    return t
