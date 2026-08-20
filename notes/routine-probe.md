# 루틴 자리 확인 — 상시 세션에서 잰 것

2026-08-18부터 아침·저녁 루틴이 매번 아무 결과도 못 냈다. 예약은 발화했는데
저장소에 아무것도 안 올라왔다. 원인 후보가 둘이었다 — 예약으로 뜬 세션에
저장소가 안 붙거나, 권한 모드가 없어 첫 명령에서 멈추거나.

이 세션은 저장소가 붙어 있고 권한 모드도 정해져 있다. 그래서 그 둘이
원인이었다면 여기서는 통과해야 한다. 아래는 그것을 잰 결과다.

## 실행 시각

2026-08-21 08:28 KST (`TZ=Asia/Seoul date` → `Fri Aug 21 08:28:02 KST 2026`)

## 작업 디렉터리

```
/home/user/insight
```

저장소가 이미 클론되어 있었다. 직접 클론할 필요가 없었다.

## git remote -v

```
origin	https://github.com/enair840926-star/insight (fetch)
origin	https://github.com/enair840926-star/insight (push)
```

현재 브랜치는 `main`, 시작 시점 HEAD는 `97c8d5f 인사이트 반영 2026-08-21 08:23 [skip ci]`.

## python / python3

**둘 다 된다.** `/usr/local/bin/python`, `/usr/local/bin/python3`.
앞으로 루틴은 `python`을 쓴다.

## tools/pending.py -v 출력 전문

`TZ=Asia/Seoul python tools/pending.py -v`

```
국장    수집 08-21 06:47  작성 08-21 08:11  최신
미장    수집 08-21 02:23  작성 08-17 21:15  안 씀 — 장중 스냅샷 (수집 02:23에 이미 열려 있었음)
매크로   수집 08-21 06:53  작성 08-21 08:11  최신
코인    수집 08-20 21:15  작성 08-21 02:35  최신
```

이번엔 설치 확인만이라 인사이트는 쓰지 않았다. 미장이 '안 씀'인 이유는
`pending.py`가 장중 스냅샷을 거른 것이지 루틴이 실패한 것이 아니다.

## git fetch origin main

성공 (exit 0). `* branch main -> FETCH_HEAD`.

## git push --dry-run origin HEAD:main

```
Everything up-to-date
```

exit 0. 다만 이 시점에는 밀 커밋이 없어서 **인증이 실제로 쓰였는지는
이것만으로 확인 못 함.** 그래서 이 파일을 커밋해 실제로 밀어 본다.

## 이 커밋의 푸시 결과

**됐다.** `git push -u origin HEAD:main` 이 exit 0으로 끝났다.

```
To https://github.com/enair840926-star/insight
   97c8d5f..eddf540  HEAD -> main
branch 'main' set up to track 'origin/main'.
```

`git fetch` 후 `origin/main` 이 `eddf540`이고 `notes/routine-probe.md` 가
원격 트리에 들어 있는 것까지 확인했다. 재시도도 `git pull --rebase` 도
필요 없었다 — 한 번에 통과했다.

(이 문장 자체는 그 푸시 다음 커밋으로 들어간다. 결과를 적으려면 결과가
먼저 나와야 해서 순서가 그렇게 된다.)

## 그래서 무엇이 원인이었나

**저장소와 권한이 붙은 세션에서는 전부 통과한다.** 자리 확인·도구 실행·
푸시가 모두 됐다. 2026-08-18부터의 무소득이 예약 세션에 저장소나 권한이
없어서였다는 가설과 어긋나지 않는다.

다만 **이것이 그 가설을 증명하지는 않는다.** 여기서 되는 것을 봤을 뿐,
예약 세션에서 무엇이 어떻게 막혔는지는 이 세션에서 관측하지 못했다.
앞으로 루틴이 이 대화로 발화해서 결과가 나오기 시작하면 그때 확인된다.

## 루틴이 쓸 명령 (이 세션에서 되는 것을 확인한 것만)

```
cd /home/user/insight
git fetch origin main
TZ=Asia/Seoul python tools/pending.py -v
...
git push -u origin HEAD:main
```

`TZ`를 명령마다 붙이는 이유는 컨테이너가 UTC로 돌기 때문이다 — 안 붙이면
시각을 문자열로 찍는 자리가 9시간 어긋난다.
