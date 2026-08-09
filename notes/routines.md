# 저장소 밖에 있는 것 — PC를 갈면 이것부터

이 앱이 사람 손 없이 매일 도는 구조는 **저장소 밖 파일 셋**에 걸려 있다.
git에 없으므로 PC가 죽으면 사라진다. 코드가 다 남아 있어도 *무엇을 다시
만들어야 하는지*를 모르면 복구가 안 되므로 여기 적어 둔다.

사본은 `.claude/routines/` 에 있고 `tools/backup_routines.py` 가 관리한다.

```
python tools/backup_routines.py            # 실물과 사본이 다른지 확인
python tools/backup_routines.py --save     # 실물 → 저장소 (고쳤을 때)
python tools/backup_routines.py --restore  # 저장소 → 실물 (PC를 갈았을 때)
```

**사본이니 어긋날 수 있다.** 그래서 확인하는 쪽을 같이 뒀다 — 스킬 사본을
그냥 두었다가 옛 규칙이 살아 돌아온 적이 있다(2026-08-08).

---

## 무엇이 어디에 있나

| 파일 | 실물 위치 | 하는 일 |
|---|---|---|
| `인사이트-포인터.md` | `~/.claude/skills/인사이트/SKILL.md` | `/인사이트` 진입점 |
| `asset-insight-morning.md` | `~/.claude/scheduled-tasks/asset-insight-morning/SKILL.md` | 아침 루틴 |
| `asset-insight-evening.md` | `~/.claude/scheduled-tasks/asset-insight-evening/SKILL.md` | 저녁 루틴 |

**포인터에는 지침이 없다.** 저장소의 `.claude/skills/인사이트/SKILL.md` 를
읽으라는 말만 있다. 지침을 양쪽에 두면 형식이 바뀔 때 어긋난다.

---

## 예약 (파일만으로는 안 살아난다)

`--restore` 는 파일만 되돌린다. **예약 자체는 Claude 앱에 다시 등록해야
한다.** 등록된 상태는 이랬다:

| 작업 | cron | 한국시간 |
|---|---|---|
| `asset-insight-morning` | `22 7,8,9 * * 1-5` | 평일 07:22 · 08:22 · 09:22 |
| `asset-insight-evening` | `12 21,22,23 * * 1-5` | 평일 21:12 · 22:12 · 23:12 |

**하루 세 번씩 도는 이유**는 GitHub 예약 수집이 한 시간까지 밀리기
때문이다(실측: 08:00 예약이 08:58에 실행). 시각만 보고 한 번 돌면
수집 전에 돌아 헛돈다. 세 번 돌면서 `tools/pending.py` 가 가리키는
것만 쓰므로 대부분은 몇 초에 끝난다.

수집(GitHub Actions)과 시각을 어긋나게 잡아 둔 것도 같은 이유다.

| | 수집 (자동, 클라우드) | 인사이트 (루틴, PC) |
|---|---|---|
| 국장 | 07:20 · 07:50 · 08:20 | 07:22 · 08:22 · 09:22 |
| 미장·매크로·코인 | 20:50 · 21:20 · 21:50 | 21:12 · 22:12 · 23:12 |

---

## 사용자 작업 지침 — 파일이 아니다

Claude 앱의 **설정 → 지침**은 계정에 저장된다. 디스크 어디에도 없어서
`backup_routines.py` 로 동기화할 수 없다(사용자 폴더 전체를 훑어 확인했다).
**새 세션부터 적용된다** — 지금 세션에서 안 보인다고 저장이 안 된 것이 아니다.

`.claude/routines/CLAUDE-사용자.md` 에 텍스트로만 남겨 둔다. 계정이
날아가거나 지침이 지워지면 그것을 설정에 붙여넣는다. **동기화가 없으므로
설정에서 고쳤으면 그 파일도 손으로 맞춘다.**

한때 `~/.claude/CLAUDE.md` 에도 같은 성격의 지침이 있었다. 설정 지침과
둘 다 로드되어 겹쳤으므로 `CLAUDE.md.replaced-by-settings` 로 이름을
바꿔 두었다. 되살릴 일이 있으면 그 파일을 다시 `CLAUDE.md` 로 바꾸면
되지만, 그러면 다시 겹친다.

## 저장소 밖에 있는 나머지

- **`.env`** — `DART_API_KEY` · `ECOS_API_KEY` · `EIA_API_KEY`.
  git에 올리지 않는다. 클라우드는 GitHub Secrets에 같은 이름으로 들어 있다.
  값은 `tools/probe.py` 가 길이와 포함 문자만 재서 알려 준다.
- **`data/`** — 중간 산출물(32MB). 커밋해야 하는 것은 `run.py --publish` 가
  `cloud/` 로 복사한다.

## 되살리는 순서

1. `git clone` 후 `pip install -r requirements.txt`
2. `.env` 를 다시 만든다 (`.env.example` 참고)
3. `python tools/backup_routines.py --restore`
4. Claude 앱에서 위 두 예약을 등록하고 **활성 상태**인지 확인
5. `python tools/probe.py` 로 소스가 닿는지 잰다
6. `python tools/backup_routines.py` 로 사본이 맞는지 확인
