# 왜 DBMS인가: 터미널 시연

[왜 DBMS인가](../WHY_DBMS.md)의 문제 1·2·3을, 실제로 프로그램(서버) 여러 개를 띄워서 눈으로 확인하는 시연입니다. 과제 필수는 아니지만 실제 DBMS가 푸는 문제 세 가지(차별화 후보)도 `--all`로 함께 볼 수 있습니다.

## 0. 이 시연이 보여 주는 것

쇼핑몰 "정글마켓"에 회원, 주문, 배송, 정산, 마케팅 프로그램이 있다고 가정합니다. 이 프로그램들을 **두 가지 방식**으로 차례로 띄우고, 똑같은 요청을 똑같은 순서로 보냅니다.

| | 1부: 파일 직접 | 2부: DBMS |
| --- | --- | --- |
| 데이터를 다루는 곳 | 프로그램마다 CSV 파일을 직접 열고, 쉼표로 나누고, 처음부터 한 줄씩 읽음 | 프로그램은 SQL로 "이게 필요해"라고 부탁만 함. 파일은 DBMS만 만짐 |
| 포트 | 84xx (8401\~8406) | 85xx (8501\~8506) |

두 방식은 프로그램 구성, 요청 순서, 데이터가 모두 같고 **데이터를 다루는 곳만 다릅니다.** 그래서 결과가 다르게 나오면, 원인은 그 차이 하나입니다.

정산 프로그램의 코드를 비교하면 차이가 바로 보입니다.

```python
# 1부: 파일 직접 (store.py의 FileStore.revenue)
for line in open("orders.csv"):
    order_id, user, product, price = line.strip().split(",")   # "칸이 4개, 4번째가 가격"이라고 코드에 적혀 있음
    total += int(price)

# 2부: DBMS (store.py의 DbStore.revenue)
total = db.execute("SELECT SUM(price) FROM orders")             # "price 칸의 합"만 말함
```

**알아 둘 것**

- 파이썬 표준 라이브러리만 씁니다. 따로 설치할 것이 없고, 파이썬 3.8 이상이면 됩니다.
- 우리 미니 DBMS는 아직 없어서, **DBMS 자리에 파이썬에 들어 있는 SQLite**를 씁니다. 나중에 미니 DBMS의 API 서버(설계 3단계)가 생기면, `store.py`의 `DbStore`만 그 서버를 부르도록 바꾸면 됩니다.

## 1. 한 번에 보기

### 어디서 실행하나

반드시 **`docs/study/WHY_DBMS/` 폴더에서** 실행합니다. `dbms_demo` 폴더가 바로 아래에 보이는 위치입니다.

```bash
cd docs/study/WHY_DBMS      # 저장소 맨 위 폴더에서 시작했다면
ls                          # dbms_demo 폴더가 보여야 함
```

`dbms_demo` 폴더 안이나 저장소 맨 위 폴더에서 실행하면 `No module named 'dbms_demo'` 오류가 납니다. 파이썬이 `dbms_demo`라는 폴더를 현재 위치에서 찾기 때문입니다.

### 실행 명령

```bash
python3 -m dbms_demo.scenario --step        # Enter를 누를 때마다 한 장면씩 (발표할 때)
python3 -m dbms_demo.scenario               # 처음부터 끝까지 자동으로
python3 -m dbms_demo.scenario --rows 200000 # 주문을 20만 건만 만들어서 빠르게 (기본은 100만 건)
python3 -m dbms_demo.scenario --all         # 차별화 후보 A·B·C까지 모두
```

서버는 스크립트가 직접 띄우고, 끝나면 직접 끕니다. 터미널 하나면 됩니다.

### 화면 읽는 법

한 줄은 `어느 프로그램(포트) · 무엇을 했나 → 결과` 순서입니다.

```
정산(8404) · 500 ValueError: too many values to unpack (expected 4)   ← 정산이 멈춤!
```

"정산 프로그램(8404번 포트)이 매출을 계산하다가 `ValueError`로 멈췄다"는 뜻입니다.

### 마지막에 나오는 정리

```
                                                파일 직접           DBMS
  문제 1  쿠폰 칸 추가 후 정산                  멈춤(500)           정상
  문제 2  주문번호로 찾기                       357.1ms             0.6ms
  문제 2  user로 세기 (인덱스 없음, 둘 다 전체) 291.9ms             53.6ms
  문제 3  재고 1개, 산 사람                     2명                 1명
```

문제 2의 시간은 컴퓨터마다 다릅니다. 나머지는 항상 같게 나옵니다. `--all`을 붙이면 차별화 후보 A·B·C의 결과도 함께 나옵니다.

## 2. 장면별로 무슨 일이 일어나나

장면마다 실제 코드(`store.py`)를 짧게 보여 줍니다. 위가 파일 직접(`FileStore`), 아래가 DBMS(`DbStore`)입니다. 3절에서 `curl`로 같은 일을 직접 해 볼 수 있습니다.

### 문제 1 · 칸 하나 추가했더니 정산이 멈춘다

```
orders.csv  바꾸기 전:  1,user1,마우스,2000
            바꾼 뒤:    1,user1,마우스,500,2000      ← 주문 프로그램이 가격 앞에 쿠폰 칸을 넣음
```

```python
# 파일 직접: 정산 프로그램 (칸이 4개라고 정해 둠)
order_id, user, product, price = line.split(",")
# 바꾼 뒤에는 5개를 4개에 담으려다 멈춤
# ValueError: too many values to unpack (expected 4)

# DBMS: 정산 프로그램 (칸을 이름으로 요청)
db.execute("SELECT SUM(price) FROM orders")    # 쿠폰 칸이 생겨도 그대로 동작
```

### 문제 2 · 주문 100만 건에서 찾기

```python
# 파일 직접: 첫 줄부터 비교
for line in open("orders.csv"):
    if line.split(",")[0] == "900000": ...       # 900,000줄을 읽어야 찾음

# DBMS
db.execute("SELECT * FROM orders WHERE id = 900000")      # id 인덱스로 바로 찾음
db.execute("SELECT COUNT(*) FROM orders WHERE user = 'user77'")   # user에는 인덱스가 없어서 DBMS도 전부 읽음
```

user로 세기는 DBMS도 전부 읽습니다. 그래도 더 빠른 건 SQLite가 C 언어로 짜여 있어서일 뿐입니다. 이 장면의 핵심은 "DBMS라서 빠르다"가 아니라 **"인덱스가 있으면 빠르다"**입니다.

### 문제 3 · 남은 1개를 두 명에게 판다

재고 1개인 키보드를 kim과 lee가 동시에 삽니다. 구매는 "읽기 → 0.3초 판단 → 쓰기"입니다.

```python
# 파일 직접
n = int(open("stock.txt").read())     # kim도 lee도 1을 읽음
time.sleep(0.3)
open("stock.txt", "w").write(str(n - 1))   # 둘 다 0을 씀 → 2명에게 팖

# DBMS
db.execute("BEGIN IMMEDIATE")         # SQLite에서 lock을 잡는 명령. 먼저 온 쪽이 잡고, 나머지는 여기서 기다림
n = db.execute("SELECT count FROM stock ...")   # 나중에 온 쪽은 0을 읽음 → 품절
...
db.execute("COMMIT")
```

| | 산 사람 |
| --- | --- |
| 파일 직접 | **2명** |
| DBMS | 1명 (기다린 만큼 시간은 약 두 배) |

### 차별화 후보 (과제 필수 아님, `--all`로 실행)

우리 미니 DBMS가 처음부터 만들지는 않지만, 실제 DBMS가 푸는 문제입니다. 시간이 남으면 차별화로 해 볼 수 있습니다.

#### 차별화 A · 주소를 바꿨는데 택배는 옛날 집으로 간다

처음 폴더에는 kim의 주소가 **파일 두 개**에 들어 있습니다. 배송팀이 편하게 쓰려고 회원 파일을 복사해 둔 것입니다.

```
members.csv   (회원 프로그램이 씀)      shipping.csv  (배송 프로그램이 씀)
kim,강남구                              kim,강남구
lee,마포구                              lee,마포구
```

kim이 주소를 송파구로 바꾸고, 그다음 택배를 보냅니다.

```python
# 파일 직접
# 회원 프로그램: 자기 파일만 고침
members.csv  →  kim,송파구          # shipping.csv는 그대로 kim,강남구

# 배송 프로그램: 자기 파일에서 주소를 읽음
for line in open("shipping.csv"):
    name, addr = line.split(",")    # kim → 강남구
```

```python
# DBMS
db.execute("UPDATE members SET address = '송파구' WHERE name = 'kim'")     # 회원 프로그램
db.execute("SELECT address FROM members WHERE name = 'kim'")              # 배송 프로그램 → 송파구
```

| | 택배가 간 곳 | 왜 |
| --- | --- | --- |
| 파일 직접 | **강남구 (옛 주소)** | 같은 주소가 파일 두 개에 있고, 한쪽만 고쳐짐 |
| DBMS | 송파구 | 주소가 `members` 테이블 한 곳에만 있고, 둘 다 거기서 읽음 |

#### 차별화 B · 새 질문이 생기면 코드를 새로 짜야 한다

마케팅이 "가장 많이 팔린 상품 3개는?"을 묻습니다.

```python
# 파일 직접: 받을 곳이 없음
raise NotImplementedError("질문마다 반복문 코드를 새로 짜서 배포해야 합니다")   # → 501

# DBMS: SQL 한 문장
db.execute("SELECT product, COUNT(*) AS n FROM orders GROUP BY product ORDER BY n DESC LIMIT 3")
```

#### 차별화 C · 저장하다 꺼지면 돈만 빠진다

주문 하나 = 1. 결제 기록 → 2. 재고 줄이기 → 3. 주문 기록. 2번을 쓰는 도중에 프로그램이 죽습니다.

```python
# 파일 직접: 파일 세 개를 하나씩 고침
open("payments.csv", "a").write("paid\n")         # 1번 써짐
f = open("stock.json", "w"); f.write('{"monit')    # 2번 반만 써진 채로
os._exit(1)                                        #    전원이 나감. 3번은 시작도 못 함

# DBMS: 세 개를 트랜잭션 하나로 묶음
db.execute("BEGIN")
db.execute("INSERT INTO payments ...")    # 1번
db.execute("UPDATE stock ...")            # 2번
os._exit(1)                               # COMMIT 전에 죽음 → 1·2번이 모두 취소됨
```

| | 다시 켠 뒤 |
| --- | --- |
| 파일 직접 | **결제 1, 주문 0**, 재고 파일은 `{"monit`만 남아 읽을 수 없음 |
| DBMS | 결제 0, 주문 0, 재고 10 (처리 전과 같음. 다시 시도하면 됨) |

## 3. curl로 직접 해 보기

시연 스크립트가 보여 준 장면을, 요청을 하나씩 보내며 직접 확인하는 방법입니다.

### 서버 띄우기

터미널 두 개를 열고, **둘 다 `docs/study/WHY_DBMS/` 폴더에서** 실행합니다. 처음 상태(주문 100만 건)를 만드는 데 1\~2초 걸립니다.

```bash
python3 -m dbms_demo.servers --mode file    # 터미널 1: 파일 직접 방식 (84xx)
python3 -m dbms_demo.servers --mode dbms    # 터미널 2: DBMS 방식 (85xx)
```

| 프로그램 | 파일 직접 | DBMS |
| --- | --- | --- |
| 회원 | 8401 | 8501 |
| 주문 | 8402 | 8502 |
| 배송 | 8403 | 8503 |
| 정산 | 8404 | 8504 |
| 주문2 (문제 3에서 동시에 주문하는 두 번째 주문 프로그램) | 8405 | 8505 |
| 마케팅 | 8406 | 8506 |

### 요청 보내기

터미널을 하나 더 열고 아래 명령을 칩니다. 예시는 모두 파일 직접(84xx)입니다. **포트 앞의 `84`를 `85`로 바꾸면 DBMS 방식**입니다. 같은 명령을 두 번 쳐서 결과를 비교해 보세요.

처음 상태로 되돌리고 싶으면 터미널 1, 2에서 `Ctrl+C`로 껐다가 다시 띄우면 됩니다.

#### 문제 1

```bash
curl localhost:8404/revenue                  # 정산: 매출 합계 (정상)
curl -X POST localhost:8402/admin/coupon     # 주문팀: 쿠폰 칸 추가
curl localhost:8404/revenue                  # 정산: 다시 계산
```

- 파일 직접: 두 번째 정산이 `500`이고, `"error"`에 `ValueError: too many values to unpack (expected 4)`, `"where"`에 멈춘 코드 줄이 나옵니다.
- DBMS: 칸이 생겨도 매출이 그대로 나옵니다.

#### 문제 2

```bash
curl localhost:8402/orders/900000            # 주문번호 900000 찾기 (뒤쪽)
curl localhost:8402/orders/10                # 주문번호 10 찾기 (앞쪽)
curl "localhost:8402/orders?user=user77"     # user77의 주문 세기 (user 칸에는 인덱스 없음)
```

- 파일 직접: `"scanned_lines"`가 읽은 줄 수입니다. 900000번은 900,000줄, 10번은 10줄을 읽습니다. 뒤쪽 주문일수록 오래 걸립니다.
- DBMS: `"how"`에 DBMS가 고른 방법이 나옵니다. 주문번호는 `SEARCH orders USING INTEGER PRIMARY KEY`(인덱스로 바로), user는 `SCAN orders`(처음부터 끝까지)입니다. `"elapsed_ms"`(걸린 시간, ms)를 비교해 보세요.

#### 문제 3

두 주문 프로그램에 **동시에** 요청을 보냅니다.

```bash
curl -X POST localhost:8402/stock/reset -d '{"count":1}'      # 재고를 1개로
curl -X POST localhost:8402/buy -d '{"user":"kim"}' & \
curl -X POST localhost:8405/buy -d '{"user":"lee"}' & wait    # kim과 lee가 동시에 구매
curl localhost:8402/stock                                     # 몇 개 팔렸나
```

명령 끝의 `&`는 "끝나길 기다리지 말고 바로 다음 명령을 실행"이라는 뜻이라, 두 요청이 거의 동시에 나갑니다. `wait`는 둘 다 끝날 때까지 기다립니다.

- 파일 직접: 둘 다 `"saw_stock": 1, "ok": true`이고, `/stock`에 `"sold": 2`가 나옵니다.
- DBMS: 한쪽만 `"ok": true`이고, 다른 쪽은 `"saw_stock": 0, "ok": false`입니다.
- 읽기와 쓰기 사이 시간(기본 0.3초)을 바꾸려면 `localhost:8402/buy?delay=1`처럼 붙입니다.

#### 차별화 A

```bash
curl -X PUT localhost:8401/members/kim -d '{"address":"송파구"}'   # 회원 프로그램: 주소 변경
curl -X POST localhost:8403/ship -d '{"user":"kim"}'              # 배송 프로그램: 발송
```

| 응답에서 볼 곳 | 파일 직접 (84xx) | DBMS (85xx) |
| --- | --- | --- |
| 주소 변경 | `"changed": "members.csv"` (회원팀 파일만 고침) | `"sql": "UPDATE members ..."` |
| 발송 | `"read_from": "shipping.csv", "sent_to": "강남구"` (옛 주소) | `"read_from": "members 테이블", "sent_to": "송파구"` |

#### 차별화 B

```bash
curl -X POST localhost:8406/query \
     -d '{"sql":"SELECT product, COUNT(*) AS n FROM orders GROUP BY product ORDER BY n DESC LIMIT 3"}'
```

위 SQL은 "상품별로 주문 수를 세서(`GROUP BY`), 많은 순서로 정렬해(`ORDER BY ... DESC`), 위에서 3개만(`LIMIT 3`)"이라는 뜻입니다.

- 파일 직접: `501`과 "질문을 받는 곳이 없습니다".
- DBMS: 바로 답이 나옵니다. SQL을 바꿔 다른 질문도 해 보세요. 시연에서는 데이터를 바꾸지 않도록 `SELECT`만 받습니다.

#### 차별화 C

```bash
curl localhost:8404/consistency                 # 처리 전: 결제 수, 주문 수, 모니터 재고
curl -X POST "localhost:8402/checkout?crash=1"  # 주문 처리 도중 2번(재고) 단계에서 프로그램이 죽음 (응답 없음)
curl localhost:8404/consistency                 # 정산 프로그램이 다시 확인
```

- 파일 직접: 결제 1, 주문 0, 모니터 재고 `"읽을 수 없음"`.
- DBMS: 결제 0, 주문 0, 재고 10.

죽은 주문 프로그램은 `servers`가 1초 안에 다시 띄워 줍니다. 그다음 `crash=1` 없이 한 번 더 보내 보세요.

```bash
curl -X POST localhost:8402/checkout
curl localhost:8404/consistency
```

- DBMS: 정상 처리되어 결제 1, 주문 1, 재고 9가 됩니다.
- 파일 직접: 재고 파일이 깨져 있어서 주문은 또 실패합니다. 그런데 결제 기록은 재고를 읽기 전에 쓰기 때문에, **결제만 2건**이 됩니다. 한 번 깨진 데이터가 다음 요청까지 망가뜨리는 것입니다. 되돌리려면 `servers`를 껐다 켜서 처음 상태로 만들어야 합니다.

## 4. 파일 구성

| 파일 | 하는 일 |
| --- | --- |
| `store.py` | 두 방식의 실제 코드. `FileStore`(파일 직접)와 `DbStore`(DBMS)가 **같은 함수 이름**을 갖고 속만 다르게 동작함. 장면별 코드가 여기 있음 |
| `app.py` | 프로그램 하나(HTTP 서버). `--role`(역할 이름), `--mode`(`file` 또는 `dbms`), `--port`로 띄움 |
| `servers.py` | 한 방식의 프로그램 여섯 개를 한꺼번에 띄움. 죽은 프로그램은 다시 띄움 (3절 curl 실습용) |
| `scenario.py` | 두 방식을 차례로 띄워 같은 순서로 요청하고 결과를 비교해 보여 줌 (1절 시연용). 기본은 문제 1·2·3, `--all`이면 차별화 A·B·C까지 |

`store.py`의 `FileStore`는 일부러 "파일로 데이터를 다루던 시절의 프로그램"처럼 짰습니다. 예를 들어 `revenue()`는 "칸이 네 개"라고 가정한 채 1년 전에 짠 정산 코드라는 설정입니다. 고치지 말고, 그대로 깨지는 모습을 보는 것이 시연의 목적입니다.
