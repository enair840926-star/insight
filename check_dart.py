# -*- coding: utf-8 -*-
"""DART 인증키 확인 및 기능 점검

    python check_dart.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core import env
from collectors import dart


def main():
    key = env.get("DART_API_KEY")
    if not key:
        print("[X] DART_API_KEY가 비어 있습니다.")
        print("    asset-insight/.env 파일을 열어 DART_API_KEY= 뒤에 키를 붙여넣으세요.")
        return 1
    print(f"[O] 키 로드됨 (길이 {len(key)}자, 앞 4자리 {key[:4]}…)\n")

    # 1) 전체 상장사 매핑
    print("[1/4] 상장사 목록(corpCode) 다운로드 …", end=" ", flush=True)
    try:
        corp = dart.load_corp_codes()
    except dart.DartError as e:
        print(f"\n  [X] {e}")
        if "010" in str(e) or "011" in str(e):
            print("  → 키가 아직 승인 대기 중일 수 있습니다. 발급 메일의 승인 여부를 확인하세요.")
        return 1
    except Exception as e:
        print(f"\n  [X] {type(e).__name__}: {e}")
        return 1
    print(f"{len(corp):,}개 종목")
    for c in ("005930", "000660", "035720"):
        info = corp.get(c)
        print(f"      {c} -> {info['corp_code']} {info['name']}" if info
              else f"      {c} -> 없음")

    cc = corp["005930"]["corp_code"]

    # 2) 공시 목록
    print("\n[2/4] 삼성전자 최근 공시 …", end=" ", flush=True)
    try:
        f = dart.recent_filings(cc, days=30, limit=5)
        print(f"{len(f)}건")
        for x in f[:5]:
            print(f"      {x['date']} {x['title'][:50]}  ({x['filer']})")
    except Exception as e:
        print(f"[X] {type(e).__name__}: {e}")

    # 3) 내부자 거래
    print("\n[3/4] 임원·주요주주 소유보고 (최근 90일) …", end=" ", flush=True)
    try:
        ins = dart.insider_trades(cc, days=90, limit=30)
        print(f"{len(ins)}건")
        for x in ins[:6]:
            d = x["delta"]
            arrow = "변동없음" if not d else f"{d:+,}주"
            print(f"      {x['date']} {x['name']} ({x['position']}) {arrow}"
                  f"  보유 {x['shares']:,}주" if x['shares'] else "")
        s = dart.summarize_insider(ins)
        if s:
            print(f"\n      집계: 매수 {s['buy_count']}건 / 매도 {s['sell_count']}건"
                  f" / 순 {s['net_shares']:+,}주")
            for c in s["clusters"]:
                print(f"      ★ {c['date']} {c['count']}명 동시 "
                      f"{'매수' if c['net'] > 0 else '매도'} {c['net']:+,}주"
                      f"  ({', '.join(c['people'])})")
    except Exception as e:
        print(f"[X] {type(e).__name__}: {e}")

    # 4) 대량보유
    print("\n[4/4] 대량보유 상황보고(5%룰, 최근 1년) …", end=" ", flush=True)
    try:
        mj = dart.major_holders(cc, days=365, limit=5)
        print(f"{len(mj)}건")
        for x in mj:
            print(f"      {x['date']} {x['holder'][:16]:16s} {x['ratio']}%"
                  f" ({x['ratio_delta']:+}%p) 주식 {x['shares_delta']:+,}주")
            print(f"                 └ {x['reason'][:50]}")
    except Exception as e:
        print(f"[X] {type(e).__name__}: {e}")

    print("\n완료. 이상 없으면 collect_kr.py에 DART를 연결합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
