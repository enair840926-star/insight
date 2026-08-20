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

아래 "실측" 절에 커밋 직후 채운다.
