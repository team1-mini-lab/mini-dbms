# 왜 DBMS인가: 터미널 시연

[WHY_DBMS](../WHY_DBMS_GUIDE.md)의 여섯 장면을 **실제 프로그램(서버) 여러 개**로 재현합니다. 미니 레디스의 `demo/scenario.py`(로컬 캐시 vs mini-redis)와 같은 방식입니다.

정글마켓의 회원·주문·배송·정산·마케팅 프로그램을 **같은 코드로 역할만 바꿔** 띄우고, 데이터를 다루는 방식만 바꿔 끼운 뒤 똑같은 요청을 보냅니다.

```
1부  파일 직접   프로그램마다 CSV 파일을 직접 열고, 쉼표로 나누고, 처음부터 읽음   (84xx 포트)
2부  DBMS        프로그램은 SQL로 부탁만. 파일은 DBMS만 만짐                     (85xx 포트)
```

- 표준 라이브러리만 씁니다. 설치할 것이 없고, 파이썬 3.8 이상이면 됩니다.
- 미니 DBMS가 아직 없어서 **DBMS 자리에 파이썬 내장 SQLite**를 둡니다. 미니 DBMS의 Phase 3 서버(`POST /query`)가 생기면 `store.py`의 `DbStore`만 그걸 부르도록 바꾸면 됩니다.

## 1. 한 번에 보기 (Enter로 한 단계씩)

**`docs/study/WHY_DBMS/` 폴더에서** 실행합니다(`dbms_demo` 폴더의 바로 위). `dbms_demo` 폴더 안이나 저장소 최상위에서 실행하면 `No module named 'dbms_demo'` 오류가 납니다.

```bash
cd docs/study/WHY_DBMS
```

```bash
python3 -m dbms_demo.scenario --step        # Enter를 누를 때마다 한 단계씩 (발표용)
python3 -m dbms_demo.scenario               # 처음부터 끝까지 자동으로 (약 5초)
python3 -m dbms_demo.scenario --rows 200000 # 주문 수를 줄여서 (기본 100만)
```

서버는 스크립트가 직접 띄우고 끝나면 끕니다. 터미널 하나면 됩니다. 마지막에 이런 정리가 나옵니다(숫자는 컴퓨터마다 다름).

```
                                        파일 직접           DBMS
  ① 이사 후 택배가 간 곳                강남구              송파구
  ② 쿠폰 칸 추가 후 정산                멈춤(500)           정상
  ③ 마케팅의 새 질문                    코드 새로 짜야 함   SQL로 바로
  ④ 주문번호로 찾기                     249.8ms             0.3ms
  ④ user로 세기 (인덱스 없음, 둘 다 전체) 199.8ms           36.8ms
  ⑤ 재고 1개, 산 사람                   2명                 1명
  ⑥ 정전 후 결제·주문                   결제 1 · 주문 0     결제 0 · 주문 0
  ⑥ 정전 후 모니터 재고                 깨짐                10
```

## 2. curl로 직접 쳐 보기

터미널 두 개에서(둘 다 `docs/study/WHY_DBMS/` 폴더에서) 두 방식을 각각 띄웁니다. 처음 상태(주문 100만 건)를 만드는 데 1~2초 걸립니다.

```bash
python3 -m dbms_demo.servers --mode file    # 터미널 1: 파일 직접 (84xx)
python3 -m dbms_demo.servers --mode dbms    # 터미널 2: DBMS (85xx)
```

| 프로그램 | 파일 직접 | DBMS |
| --- | --- | --- |
| 회원 | 8401 | 8501 |
| 주문 | 8402 | 8502 |
| 배송 | 8403 | 8503 |
| 정산 | 8404 | 8504 |
| 주문2 (장면 ⑤용 두 번째 주문 프로그램) | 8405 | 8505 |
| 마케팅 | 8406 | 8506 |

터미널 3에서 아래 명령을 칩니다. **같은 명령을 84xx로 한 번, 85xx로 한 번** 쳐 보면 차이가 보입니다. 아래 예시는 파일 직접(84xx)이고, 앞의 `84`를 `85`로 바꾸면 DBMS입니다. 처음 상태로 돌리려면 `servers`를 껐다 켜면 됩니다.

### 장면 ① 주소를 바꿨는데 택배는 옛날 집으로

```bash
curl -X PUT localhost:8401/members/kim -d '{"address":"송파구"}'   # 회원 프로그램이 주소 변경
curl -X POST localhost:8403/ship -d '{"user":"kim"}'              # 배송 프로그램이 발송
```

| | 파일 직접 (84xx) | DBMS (85xx) |
| --- | --- | --- |
| 주소 변경 | `"changed": "members.csv"` (회원팀 파일만) | `"sql": "UPDATE members ..."` |
| 발송 | `"read_from": "shipping.csv", "sent_to": "강남구"` ← 옛 주소 | `"read_from": "members 테이블", "sent_to": "송파구"` |

### 장면 ② 칸 하나 추가했더니 정산이 깨진다

```bash
curl localhost:8404/revenue                  # 정산: 매출 합계 (정상)
curl -X POST localhost:8402/admin/coupon     # 주문팀: 쿠폰 칸 추가
curl localhost:8404/revenue                  # 정산: 다시
```

- 파일 직접: 두 번째 정산이 `500`, `"error": "ValueError: too many values to unpack (expected 4)"`. `"where"`에 멈춘 코드 줄이 나옵니다. "칸이 네 개"라는 형식 지식이 정산 코드에 박혀 있습니다.
- DBMS: `ALTER TABLE`로 칸이 생겨도 정산은 `SELECT SUM(price)`로 이름을 써서 그대로 동작합니다.

### 장면 ③ 질문 하나에 프로그램 하나

```bash
curl -X POST localhost:8406/query \
     -d '{"sql":"SELECT product, COUNT(*) AS n FROM orders GROUP BY product ORDER BY n DESC LIMIT 3"}'
```

- 파일 직접: `501` "질문을 받는 곳이 없습니다. 질문마다 반복문 코드를 새로 짜서 배포해야 합니다."
- DBMS: SQL 한 문장으로 바로 답. SQL을 바꿔 가며 다른 질문도 해 보세요 (시연에서는 `SELECT`만 받습니다).

### 장면 ④ 100만 건에서 찾기

```bash
curl localhost:8402/orders/900000            # 주문번호로 찾기
curl localhost:8402/orders/10                # 앞쪽 주문
curl "localhost:8402/orders?user=user77"     # user로 세기 (인덱스 없음)
```

- 파일 직접: `"scanned_lines": 900000`, 앞쪽 주문은 금방, 뒤쪽일수록 오래 걸립니다.
- DBMS: `"how": "SEARCH orders USING INTEGER PRIMARY KEY"`(인덱스로 바로) vs `"how": "SCAN orders"`(인덱스 없으면 DBMS도 전부 훑음). `elapsed_ms`를 비교해 보세요. 우리 Phase 2의 "인덱스 vs 선형 탐색"이 바로 이 차이입니다.

### 장면 ⑤ 남은 1개를 두 명에게

두 주문 프로그램에 **동시에** 요청을 보냅니다. 명령 끝의 `&`가 동시에 보내는 부분이고, `wait`는 둘 다 끝날 때까지 기다립니다.

```bash
curl -X POST localhost:8402/stock/reset -d '{"count":1}'
curl -X POST localhost:8402/buy -d '{"user":"kim"}' & \
curl -X POST localhost:8405/buy -d '{"user":"lee"}' & wait
curl localhost:8402/stock
```

- 파일 직접: 둘 다 `"saw_stock": 1, "ok": true` → `/stock`에 `"sold": 2`. 재고를 읽고 쓰는 사이(0.3초)에 서로 끼어듭니다.
- DBMS: 한쪽만 성공, 다른 쪽은 `"saw_stock": 0, "ok": false`. 먼저 온 쪽이 트랜잭션 lock을 잡아 나머지는 기다립니다.
- 읽기와 쓰기 사이 시간을 바꾸려면 `localhost:8402/buy?delay=1`처럼 붙입니다.

### 장면 ⑥ 저장하다 꺼지면

```bash
curl localhost:8404/consistency                 # 처리 전: 결제·주문·모니터 재고
curl -X POST "localhost:8402/checkout?crash=1"  # 주문 처리 중 ② 단계에서 프로세스가 죽음 (응답 없음)
curl localhost:8404/consistency                 # 정산 프로그램이 확인
```

- 파일 직접: 결제 1, 주문 0, 모니터 재고 `"읽을 수 없음"`(반만 써진 파일). 돈만 빠졌습니다.
- DBMS: 결제 0, 주문 0, 재고 10. `COMMIT` 전이었으므로 전부 되돌려졌습니다.
- 죽은 주문 프로그램은 `servers`가 1초 안에 다시 띄웁니다. 그다음 `crash=1` 없이 다시 보내 보세요.
  - DBMS: 정상 처리되어 결제 1, 주문 1, 재고 9가 됩니다.
  - 파일 직접: 재고 파일이 깨져 있어서 주문은 또 실패하는데, 결제 기록은 그 전에 써져서 **결제만 2건**이 됩니다. 한 번 깨진 데이터가 다음 요청까지 망가뜨립니다. 되돌리려면 `servers`를 껐다 켜서 처음 상태로 만들어야 합니다.

## 3. 파일 구성

| 파일 | 하는 일 |
| --- | --- |
| `store.py` | `FileStore`(파일 직접)와 `DbStore`(DBMS)가 같은 함수 이름으로 다르게 동작. 장면별 코드가 여기 있음 |
| `app.py` | 프로그램 하나(HTTP 서버). `--role`, `--mode`, `--port`로 띄움 |
| `servers.py` | 한 방식의 프로그램 여섯 개를 한꺼번에 띄움 (curl 실습용) |
| `scenario.py` | 두 방식을 차례로 띄워 같은 순서로 요청하고 비교 (발표용) |

`store.py`의 `FileStore`는 일부러 "그 시절 프로그램"처럼 짰습니다. 예를 들어 `revenue()`는 "칸이 네 개"라고 가정한 채 1년 전에 짠 코드입니다. 파일을 고치지 말고 그대로 깨지는 모습을 보세요.

## 4. 레디스 시연과 나란히

| | 미니 레디스 시연 | 이 시연 |
| --- | --- | --- |
| 같은 코드를 여러 개 | 데모 API 서버 A, B (**같은 역할**) | 회원·주문·배송·정산·마케팅 (**다른 역할**) |
| 바꿔 끼우는 것 | 캐시 위치: 각 서버 안 dict / mini-redis | 데이터 다루는 곳: 각 프로그램 / DBMS |
| 드러나는 뿌리 | 상태가 각 서버에 묶여 있다 | 데이터 다루는 법이 각 프로그램에 묶여 있다 |
