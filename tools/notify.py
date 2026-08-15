# -*- coding: utf-8 -*-
"""알림 미리보기 · 발송 — 지금은 설정이 없어 잠들어 있다

    python tools/notify.py              # 보낼 내용만 찍는다 (설정 없어도 됨)
    python tools/notify.py --send       # 실제 발송 (설정 있어야 감)
    python tools/notify.py --send kr    # 자산군 지정

**기본이 미리보기다.** 실수로 보내지지 않게 하려는 것이기도 하지만,
시중에 내기 전에 "무엇이 나갈지"를 먼저 보라는 뜻이 더 크다. 알림은 화면과
달리 되돌릴 수가 없다 — 폰에 한 번 뜨면 끝이다.

설정은 `core/notify.py` 위쪽에 적어 두었다. GitHub Secrets에 값을 넣으면
그때부터 수집 워크플로가 자동으로 보낸다. **코드는 다시 안 고쳐도 된다.**
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import notify


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("markets", nargs="*", default=None,
                    help="자산군 (비우면 전부)")
    ap.add_argument("--send", action="store_true",
                    help="실제로 보낸다. 없으면 미리보기만.")
    a = ap.parse_args()

    chans = notify.configured()
    body = notify.build(a.markets or None)

    print("─" * 52)
    print(body)
    print("─" * 52)
    print(f"글자 수 {len(body)}")

    if not chans:
        print("\n설정된 채널이 없습니다 — 알림은 잠들어 있습니다.")
        print("시중에 낼 때 아래를 GitHub Secrets(또는 .env)에 넣으면 돕니다:")
        print("  NOTIFY_TELEGRAM_TOKEN + NOTIFY_TELEGRAM_CHAT")
        print("  NOTIFY_DISCORD_WEBHOOK")
        print("둘 다 넣으면 둘 다 갑니다. 코드는 고칠 것이 없습니다.")
        return 0

    print(f"\n설정된 채널: {', '.join(chans)}")
    if not a.send:
        print("미리보기입니다. 실제로 보내려면 --send 를 붙이세요.")
        return 0

    for chan, (ok, note) in notify.send(body).items():
        print(f"  {chan}: {'보냄' if ok else '실패'} ({note})")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
