# 자산 인사이트 — 작업 지침

국장·미장·매크로·코인 데이터를 모아 폰에서 보는 앱. 수집은 GitHub
Actions가, 인사이트 글은 Claude가 쓴다.

배포: https://enair840926-star.github.io/insight/

---

## 이 프로젝트의 원칙

### 추측하지 말고 재라

이 저장소에서 가장 많이 틀렸던 순간은 전부 "될 것 같다"로 시작했다.
러너에서 네이버가 막힐 거라 걱정했지만 열렸고, 피드가 읽힐 거라
생각했지만 프록시가 막았다. 재는 도구가 이미 있다.

```
python tools/probe.py            # 45개 소스 접속 검증
python tools/pending.py -v       # 인사이트를 다시 써야 하는 자산군
python tools/lint_insight.py     # 인사이트에 전문용어가 남았는지
```

새 소스를 붙일 때는 `tools/probe.py`에 먼저 넣고 러너에서 재 본다.
PC에서 되는 것이 러너에서 된다는 보장이 없고 그 반대도 마찬가지다.

### 없는 것과 못 받은 것을 구분하라

이 구분이 무너지면 "내부자 매매가 없었다"처럼 사실이 아닌 문장이
만들어진다. 수집이 실패하면 조용히 빠지게 두지 말고 그 사실을
프롬프트·화면·피드에 남긴다.

- `collect_kr.py` — DART/ECOS 실패 시 "받지 못한 것"이라고 명시
- `core/feed.py` — `missing` 배열에 이유까지
- `dashboard.py` — 패널마다 수집 시각, 18시간 넘으면 표시

### 판정과 숫자를 섞지 마라

매크로 데스크(`enair840926-star/-`)와 숫자만 주고받는다. `stance`나
호재·악재 판정을 넘기면 그쪽 스코어보드가 자기 룰셋이 아니라 이쪽
판단을 채점하게 된다. 두 시스템의 판단이 갈리는 것 자체가 정보다.

같은 이유로 뉴스도 제목·날짜·출처만 넘기고 `label`·`score`는 뺀다.

### 시각은 mtime으로 재지 마라

git이 파일을 받아오면 mtime이 그때로 찍힌다. 클라우드가 대시보드를
다시 구울 때마다 일주일 전 인사이트가 "방금 작성"으로 보였던 원인이다.

- 수집 시각 → 파일명에 박힌 값 (`core/store.py`)
- 인사이트 작성 시각 → 마지막 커밋 시각 (`dashboard.py:_written_at`)
- `actions/checkout`은 `fetch-depth: 0` 이라야 `git log`가 이력을 본다

---

## 환경

- **PowerShell 5.1** — `&&`는 파서 오류다. `;` 또는 `if ($?) { }`.
  한글이 든 커밋 메시지는 `-m` 대신 파일로 넘긴다(`git commit -F`).
  `Set-Content -Encoding UTF8`은 BOM을 붙인다 — 파이썬 파일에 쓰면
  `SyntaxError: invalid non-printable character U+FEFF`가 난다.
- **의존성은 `requirements.txt` 둘뿐** — `requests`, `feedparser`.
  워크플로도 이 파일을 쓴다. 새로 추가하면 양쪽이 어긋나지 않게 여기 넣는다.
- `.env`의 키는 채팅에 붙여넣지 않는다. GitHub Secrets는 Name에 이름,
  Secret에 **값만** (이름을 값에 같이 넣어 세 키가 전부 거부된 적 있다).

---

## 구조

```
collect_{kr,us,macro,coin}.py   수집 → data/{market}_시각.json + prompt_*.txt
core/session.py                 개장까지 남은 시간 → 대비형 프롬프트
core/read.py                    숫자 → 사람 말 (해석 규칙을 한곳에)
core/store.py                   data/ 와 cloud/ 중 최신 고르기
core/feed.py                    매크로 데스크용 숫자 피드
dashboard.py                    → data/latest.html · docs/index.html · feed.json
insights/insight_{market}.md    인사이트 글 (커밋됨 — data/ 에 두면 지워진다)
```

`data/`는 `.gitignore` 대상이다. 클라우드 러너에는 없으므로 **커밋해야
하는 산출물은 `cloud/`나 `insights/`에 둔다.**

## 흐름

| | 누가 | 언제 |
|---|---|---|
| 수집 | GitHub Actions | 평일 07:20~08:20 · 20:50~22:50 (여러 번) |
| 인사이트 | Claude 루틴(PC) 또는 `/인사이트` | 새 데이터가 있을 때만 |
| 대시보드 재빌드 | GitHub Actions | `insights/` 가 바뀌면 |

GitHub 예약은 한 시간까지 밀린다(실측: 08:00 예약이 08:58 실행). 그래서
개장 전 구간에 여러 번 걸고 `--auto`가 중복을 거른다. 루틴도 시각이
아니라 `tools/pending.py`가 가리키는 것만 쓴다.

---

## 글쓰기

인사이트는 **회고가 아니라 대비**다. 지나간 장을 복기하지 말고 다가올
장에서 무엇을 볼 것인지 쓴다. 형식은 프롬프트 파일의 `## 요청` 섹션에
있고, 그게 정본이다 — 다른 곳에 베껴 적으면 낡는다.

전문용어를 그대로 쓰지 않는다. 플래트닝 → 장단기 금리차 축소,
백워데이션 → 지금 물건이 나중보다 비쌈, 타이트 → 부족. 커밋 전에
`python tools/lint_insight.py`를 통과시킨다.

매수·매도를 권하지 않는다. "무엇을 보라"까지가 범위다.

---

## 자주 걸리는 것

**`docs/index.html` 충돌** — 생성물이다. 병합하지 말고
`python run.py --skip-collect --no-insight --no-deploy`로 다시 굽고
`git add`한다. `.gitattributes`가 자동 병합을 막아 둔 이유다.

**푸시 거부** — 클라우드가 먼저 커밋했을 수 있다. `git pull --rebase`
후 재시도. 리베이스 중 `docs/` 충돌이면 위와 같이 처리한다.

**워크플로 실행이 `cancelled`** — 실패가 아니다. 예약이 여러 개라
같은 `concurrency` 그룹에 몰리면 대기 중이던 것이 취소된다. 앞뒤
실행이 이미 받았으므로 데이터 손실은 없다.

**미장 거래량이 전부 낮게 나옴** — 장중에 수집된 것이다. 완결된 장이면
거래량 배율의 중앙값이 1.0 근처다. 0.7 미만이면 판정을 접는다
(`dashboard.py`의 `partial`).

---

## 커밋 메시지

무엇을 바꿨는지가 아니라 **왜 바꿨는지**를 쓴다. 코드는 무엇을 하는지
이미 말하고 있다. 실측값이 있으면 넣는다 — "GitHub 예약이 밀린다"보다
"08:00 예약이 08:58에 돌았다"가 다음 사람에게 쓸모 있다.
