# 미니 DBMS 구현

SQL 문장을 받아 데이터를 파일에 저장하고, 원하는 데이터를 꺼내 주는 작은 데이터베이스(DBMS)를 **SQL 처리기부터 B+ 트리 인덱스, Thread Pool API 서버까지 외부 라이브러리 없이** 직접 만들었습니다.

```sql
INSERT INTO users (name, age) VALUES ('현지', 25);   -- 저장: users.tbl 파일에 한 줄 추가 (id는 자동으로 1)
SELECT * FROM users WHERE id = 1;                   -- 꺼내기: B+ 트리로 위치를 찾아 그 한 줄만 읽음 → 1, 현지, 25
```

[mini-redis](https://github.com/team1-mini-lab/mini-redis)는 키 하나로 값 하나를 꺼내는 메모리 캐시였습니다. DBMS는 꺼져도 데이터가 남게 파일에 쓰고, 키 하나가 아니라 열과 범위로도 찾고, 여러 사람이 동시에 씁니다. 그래서 세 가지 문제를 풀었습니다.

**1. 데이터의 모양 (Phase 1).** 어떤 열이 몇 번째 칸에 있는지를 여러 코드가 각자 알고 있으면, 열 하나가 추가되거나 바뀔 때 그 파일을 읽는 코드를 전부 고쳐야 합니다. 그래서 파일의 모양은 SQL 처리기 한 곳만 알게 했습니다. 다른 코드는 열 이름으로 요청하고, 열 이름을 칸 번호로 바꾸는 일과 쓰기 전에 열과 타입을 확인하는 일은 처리기가 맡습니다. [→ 코드로 보기](#phase-1-파일-모양은-왜-sql-처리기-한-곳만-아나요)

**2. 많은 행 (Phase 2).** 목차가 없으면 100만 건을 처음부터 훑습니다(1,364ms). INSERT 때 자동으로 붙는 id와 그 줄의 파일 위치를 메모리의 목차(B+ 트리)에 적어 두고, 찾을 때 그 줄만 읽습니다(0.032ms). 해시 테이블은 키 하나는 빠르지만 순서를 몰라 범위를 못 찾고, 이진 탐색 트리는 순서대로 들어오는 id에서 한쪽으로 기울어서, 균형을 유지하며 범위도 찾는 B+ 트리를 골랐습니다. [→ 왜 B+ 트리인가](#phase-2-왜-해시-테이블이-아니라-b-트리인가요)

**3. 동시에 오는 요청 (Phase 3).** 요청은 여러 스레드로 받습니다. 실행을 동시에 하려는 게 아니라 받기·보내기를 겹치려는 것으로, 접속만 하고 요청을 다 보내지 않는 느린 연결 하나에 모두가 막히지 않게 합니다. 실행은 두 INSERT가 같은 id를 받지 않도록 엔진 입구의 lock으로 한 번에 하나씩 합니다. 그래서 스레드를 늘려도 빨라지지 않고, 가끔 긴 쿼리가 오면 그동안 요청이 쌓입니다. mini-redis는 처리가 키 조회 정도로 짧아 요청마다 스레드를 만들어도 금방 끝나 쌓이지 않았지만, DBMS는 실행이 길 수 있어 스레드 수(4)와 대기열 칸 수(16)를 정해 두고, 넘치면 바로 503으로 돌려보냅니다. [→ lock은 어디에](#phase-3-lock은-어디에-왜-엔진에-걸었나요) · [→ 스레드 수는 왜](#phase-3-스레드는-왜-여럿이고-왜-4개와-16칸인가요)

```mermaid
flowchart TD
    C["클라이언트 · curl, 브라우저, 다른 서버"]
    subgraph P3["Phase 3 · server.py: 동시에 받기·보내기 (lock 밖)"]
        Q["대기열 16칸 · 꽉 차면 503"]
        W1["스레드 1"]
        W2["스레드 2"]
        W3["스레드 3"]
        W4["스레드 4"]
    end
    L{{"🔒 engine.py lock · 한 번에 한 요청"}}
    subgraph RUN["실행 (lock 안)"]
        P1["Phase 1 · SQL 처리기: 파서 → 실행기 (열·타입 확인, 경로 선택)"]
        BT["Phase 2 · B+ 트리 (메모리): id → 파일 위치"]
        F[("users.tbl · 한 줄에 한 행")]
    end
    C -->|"POST /query"| Q
    Q --> W1 & W2 & W3 & W4
    W1 & W2 & W3 & W4 -->|"5초 넘게 안 보내면 408"| L
    L -->|"engine.execute(sql)"| P1
    P1 -->|"id 조건"| BT -->|"그 줄만 읽기"| F
    P1 -->|"그 밖의 조건: 전체 스캔"| F
```

## 실행 및 시연

Python 3.10 이상이면 됩니다. 실행에 필요한 외부 패키지는 없습니다 (테스트에만 pytest).

### 1. SQL 처리기: SQL 파일을 CLI로 (Phase 1)
```bash
python3 -m minidb examples/step1.sql --data-dir /tmp/demo --schema data/schema.json   # INSERT 2개 + SELECT
python3 -m minidb examples/step2.sql --data-dir /tmp/demo --schema data/schema.json   # 다시 실행해 id = 2 조회
```
```
1 row inserted (id=1)
1 row inserted (id=2)
id | name | age
---+------+----
1  | 현지 | 25
2  | 민수 | 31
```
데이터는 `/tmp/demo/users.tbl`에 한 줄씩 저장되어, 프로그램을 다시 실행해도 남아 있고 id로 바로 찾습니다. 종료 코드는 0 성공, 1 입력 문제(파일 없음, 문법 오류), 2 실행 문제(없는 테이블, 타입 불일치)입니다.

### 2. 100만 건 성능 비교 (Phase 2)
```bash
python3 bench/run_bench.py 10000 100000    # 빠르게 보기
python3 bench/run_bench.py                 # 1만, 10만, 100만 건 (100만 건은 약 1분, 메모리 약 1.7GB)
```
| 건수 | 넣기 | 켜기(B+ 트리 다시 만들기) | 트리 높이 | id로 찾기 (인덱스) | name으로 찾기 (전체 스캔) | 배 |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000,000 | 48.4초 | 1.87초 | 5 | 0.032ms | 1364.1ms | 43,094배 |

INSERT 100만 줄을 만들어 CLI로 넣고, 같은 데이터에서 두 경로의 시간을 잽니다([측정 방법](docs/phase2.md)).

### 3. API 서버와 동시성 (Phase 3)
```bash
python3 server.py                          # http://localhost:8000 (브라우저로 열면 테스트 페이지)
curl -s -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id > 1;"}'
curl -s localhost:8000/stats               # 스레드·대기열 상태, 503으로 돌려보낸 수
```

**lock이 없을 때와 있을 때.** 스레드 100개가 동시에 INSERT합니다. lock을 끄면 여러 행이 같은 id를 받고, 켜면 1~100이 정확히 나옵니다.
```bash
python3 checks/check_concurrency.py
```

**스레드가 여럿인 이득.** 느린 연결 하나를 걸어 두고 조회를 보냅니다. `python3 server.py --workers 1`이면 약 4.7초(느린 연결이 408로 끊길 때까지), 기본값(스레드 4개)이면 바로 답이 옵니다.
```bash
(sleep 3 | nc localhost 8000 &) ; sleep 0.3
time curl -s -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id = 1;"}'
```

## 설계: 왜 이렇게 만들었나

### Phase 1: 파일 모양은 왜 SQL 처리기 한 곳만 아나요?

어떤 열이 몇 번째 칸에 있는지를 여러 코드가 각자 알고 있으면, 열 하나가 바뀔 때 그 파일을 읽는 코드를 전부 고쳐야 합니다([왜 DBMS인가](docs/study/WHY_DBMS/WHY_DBMS.md)의 문제 1). 그래서 모양은 **한 파일**에만 적고, 그걸 읽는 건 **SQL 처리기**뿐입니다.

**① 모양은 `data/schema.json` 한 곳에만 있습니다.**
```json
"users": {"columns": [{"name": "id", "type": "INT"}, {"name": "name", "type": "TEXT"}, {"name": "age", "type": "INT"}]}
```

**② INSERT: 사용자가 쓴 순서를 스키마 순서로 바꿉니다** (`minidb/executor.py`)
```python
given = dict(zip(columns, stmt.values))          # {name: '지수', age: 30}  ← 사용자가 쓴 순서
...
return tuple(given[c] for c in table.user_columns)  # ('지수', 30)          ← 스키마 순서
```
```sql
INSERT INTO users (age, name) VALUES (30, '지수');   -- users.tbl에는 "1	지수	30"으로 저장
```

**③ SELECT: 열 이름을 칸 번호로 바꿔 꺼냅니다** (`minidb/executor.py`, `minidb/catalog.py`)
```python
out_indexes = [table.column_index(n) for n in out_names]   # ["age", "name"] → [2, 1]
rows = [tuple(row[i] for i in out_indexes) for row in candidates if predicate(row)]
```

`server.py`와 `engine.py`에는 칸 번호가 한 번도 나오지 않습니다. SQL을 그대로 넘기고, 열 이름으로 된 결과를 받을 뿐입니다. 그래서 열 순서가 바뀌어도 고칠 곳은 `schema.json` 한 줄과 처리기뿐이고, 쓰기 전에 열 이름과 타입(INT·TEXT)을 확인하는 일도 처리기 한 곳에서 합니다. 단, `INSERT INTO users VALUES ('지수', 30)`처럼 열 이름을 생략하면 스키마 순서로 받으므로, 이때는 다시 순서에 기대게 됩니다.

### Phase 2: 왜 해시 테이블이 아니라 B+ 트리인가요?

DB는 `id = 7`처럼 하나만 묻지 않고, `id > 990000`, `id <= 5`처럼 **범위**와 **순서**를 묻습니다. 그래서 목차는 키를 정렬된 채로 들고 있어야 했습니다.

| 자료구조 | `id = 7` | `id` 2~5 (범위) | 순서대로 들어오는 id |
| --- | --- | --- | --- |
| 해시 테이블 (mini-redis) | 가장 빠름 | 키가 칸마다 흩어져 있어 **전부 확인** | 문제없음 |
| 이진 탐색 트리 | 빠름 | 가능 | 한쪽으로만 길어져 **줄 하나처럼** 됨 |
| **B+ 트리** | 빠름 (100만 건에 높이 5) | 시작점만 찾고 **옆 노드로 따라감** | 노드가 차면 나뉘며 균형 유지 |

범위 검색은 이렇게 동작합니다 (`minidb/bptree.py`). 노드 안의 키는 정렬돼 있고, 맨 아래 노드(잎)끼리 `next_leaf`로 이어져 있습니다.
```python
leaf = self._find_leaf(start)          # 시작값이 있을 잎까지 한 번만 내려감
i = bisect_left(leaf.keys, start)      # 잎 안에서 시작 위치
while leaf is not None:
    while i < len(leaf.keys):
        if leaf.keys[i] > end:         # 끝값을 넘으면 멈춤
            return result
        result.append((leaf.keys[i], leaf.values[i]))
        i += 1
    leaf = leaf.next_leaf              # 옆 잎으로 이동
    i = 0
```

실행기는 `WHERE id > 1` 같은 조건을 `range_search(2, ∞)`로 바꿔 부르고, 결과에 `used_index: true`를 붙입니다. id가 아닌 열(`name`, `age`)은 목차가 없어 전체 스캔합니다.

- **메모리에 위치만:** 트리에는 행이 아니라 파일 위치만 담고, 켤 때 데이터 파일로 다시 만들어 항상 일치시킵니다(100만 건에 약 1.9초, 서버는 켤 때 미리 만듦).
- **직접 만들어 보고 안 한계:** id가 순서대로만 들어와서, 나뉜 왼쪽 노드는 다시 채워지지 않고 절반만 찹니다.

### Phase 3: lock은 어디에, 왜 엔진에 걸었나요?

- **서버** (`server.py`): 연결을 받아 스레드에 나눠 주고, 엔진이 준 결과를 JSON으로 바꿔 돌려줍니다. SQL은 모릅니다.
- **엔진** (`engine.py`): 요청 **하나**(SQL 글자 한 덩어리)를 받아 lock을 잡고, 파싱해서 나온 문장들을 차례로 실행기에 넘기고, 결과를 dict로 바꿔 모은 뒤 lock을 놓습니다.
- **실행기** (`minidb/executor.py`): 파싱된 문장 **하나**를 받아 열과 타입을 확인하고, B+ 트리나 전체 스캔으로 파일을 읽거나 써서 `QueryResult`(열 이름, 행, B+ 트리를 썼는지)를 돌려줍니다.

```mermaid
sequenceDiagram
    autonumber
    participant S as 서버
    participant E as 엔진
    participant P as 파서
    participant X as 실행기
    participant B as B+ 트리
    participant F as users.tbl

    S->>E: execute(SQL 덩어리)
    rect rgba(255, 200, 120, 0.25)
    Note over E,F: 🔒 lock 안: 한 번에 한 요청만
    E->>P: parse
    P-->>E: [Insert, Select]
    E->>X: Insert
    X->>F: 끝에 한 줄 쓰기
    F-->>X: 위치 0
    X->>B: id 1 → 위치 0
    X-->>E: 새 id 1
    Note over E: dict로 바꿔 목록에 추가
    E->>X: Select id = 1
    X->>B: id 1 찾기
    B-->>X: 위치 0
    X->>F: 위치 0 한 줄 읽기
    F-->>X: 1, 현지, 25
    X-->>E: 찾은 행
    Note over E: dict로 바꿔 목록에 추가
    end
    E-->>S: 결과 목록 → JSON 응답
```

서버는 SQL을 `engine.execute(sql)`에 넘기기만 하고, lock은 엔진 입구 한 곳에만 있습니다.

- **lock이 지키는 것:** 여러 요청이 함께 쓰는 다음 id, B+ 트리, 파일 객체. INSERT("다음 id 읽기 → 쓰기 → id 올리기")나 SELECT("위치로 이동 → 읽기") 사이에 다른 스레드가 끼면 id가 겹치거나 엉뚱한 줄을 읽습니다.
- **엔진에 건 이유:** 요청 하나(문장 여러 개)를 통째로 묶을 수 있는 곳이 엔진이고, 그러면 실행기와 B+ 트리는 고치지 않아도 되며, 스레드가 없는 CLI에는 lock이 붙지 않습니다.

### Phase 3: 스레드는 왜 여럿이고, 왜 4개와 16칸인가요?

"느리다"는 세 가지로 나뉘고, 막는 장치도 각각 다릅니다.

| 무엇이 느린가 | 언제 | 예시 | 막는 장치 | 결과 |
| --- | --- | --- | --- | --- |
| **느린 연결**: 접속은 했는데 요청을 다 보내지 않은 클라이언트 | 받기 (lock 밖) | 느린 휴대폰 망, 보내다 멈춘 버그 | 스레드 여럿이 받기, 5초 넘으면 408 | 느린 연결 3개에도 다른 요청 0.7ms |
| **느린 쿼리 (id 조건)** | 실행 (lock 안) | `WHERE id = 7` | B+ 트리 | 1,364ms → 0.032ms |
| **느린 쿼리 (id가 아닌 조건)** | 실행 (lock 안) | `WHERE name = '현지'` | **없음** (목차가 id에만 있음) | 그동안 다른 요청도 차례를 기다림 → 대기열 한도와 503으로 버팀 |

| 느린 연결 | 스레드 | 다른 요청의 응답 |
| --- | --- | --- |
| 3개 | 4개 | 0.7ms |
| 4개 | 4개 | 664ms |
| 4개 | 8개 | 0.5ms |

- **스레드 4개:** 느린 연결은 스레드 하나를 붙잡습니다. 스레드가 느린 연결보다 많으면 남는 스레드가 다른 요청을 받고(0.7ms), 같으면 모두 붙잡혀 다들 기다립니다(664ms). 그래서 4개 = "느린 연결 3개까지 견딤"입니다. 더 늘려도 빨라지지 않습니다. 실행이 한 번에 하나라, 빠른 요청만 있을 때 스레드 1·4·16개가 44·70·68ms로 같았습니다.
- **대기열 16칸:** 짧으면 거절이 많고 길면 오래 기다리므로 그 사이에서 정한 판단입니다. 재 보니 4칸과 16칸은 거의 같았습니다([D35](docs/eungi/DECISIONS.md#step15)).
- **대기열을 직접 만든 이유:** 꽉 차면 바로 거절해야 하는데, 끝이 없는 대기열은 거절을 못 해서 요청 1000개 중 386개가 시간 초과로 실패했습니다. 직접 만든 대기열은 차는 순간 503을 보내 1.9초 만에 정리했습니다([D34](docs/eungi/DECISIONS.md#step15)).
- **실제 Redis처럼 스레드 하나(이벤트 루프)가 아닌 이유:** 이벤트 루프는 느린 연결 앞에서 기다리지 않지만, 명령 하나가 길면 모든 연결이 멈춥니다. Redis는 명령이 모두 짧아 맞지만, 우리는 1초 넘는 쿼리가 있을 수 있습니다.

측정은 `python3 bench/load_test.py`로 했고, 스레드 수와 대기열 칸 수는 `--workers`, `--queue`로 바꿀 수 있습니다. [`docs/study/threadpool_simulator.html`](docs/study/threadpool_simulator.html)을 내려받아 브라우저로 열면, 스레드 4개가 대기열에서 요청을 꺼내 가고 lock 앞에서 한 명씩 차례를 기다리는 모습을 눌러 볼 수 있습니다.

## 품질: 테스트와 엣지 케이스

```bash
pip install -r requirements-dev.txt && pytest   # 단위 테스트 313개 (SQL 처리기·B+ 트리·엔진·서버)
python3 checks/check_all.py                     # 기능 테스트 (INSERT·SELECT·인덱스 사용·열 순서·재시작 뒤 id 이어짐)
python3 checks/check_threadpool.py              # Thread Pool (여러 스레드가 나눠 받기, 대기열 포화 시 503)
python3 checks/check_errors.py                  # 오류 응답 (400·404·405·408·413·500·503)
python3 checks/check_guard.py                   # 엣지 방어 (느린 연결, Content-Length, 끄기)
```

### 요청이 틀리면 어디서 무엇이라고 답하나요?

요청은 관문 7개를 차례로 지납니다. 답의 모양은 모두 `{"error": {"code", "message"}}` 하나입니다.

| 관문 | 서버가 묻는 것 | 걸리면 |
| --- | --- | --- |
| ① 들어오기 | 받을 자리가 있나? | 503 `busy` |
| ② 받기 | 5초 안에 다 보냈나? | 408 `timeout` |
| ③ 크기 | 너무 크지 않나? (본문 1MB까지) | 413 `too_large` |
| ④ 형식 | HTTP 모양, Content-Length, JSON이 맞나? | 400 `bad_request` |
| ⑤ 주소·방식 | `POST /query`인가? | 404 / 405 |
| ⑥ SQL | SQL이 맞나? | 400 `bad_sql` + 앞 문장 결과 |
| ⑦ 실행 | 서버가 고장 나지 않았나? (파일 손상 포함) | 500 `internal` (자세한 내용은 로그에만) |

①\~⑥은 클라이언트 쪽 문제, ⑦만 서버 쪽 문제입니다. 받는 쪽 프로그램은 `error.code` 하나만 보고 "다시 보낼지, 보여 줄지, 관리자에게 알릴지"를 정합니다.


예를 들어 스레드와 대기열을 모두 채우면 세 번째 요청은 바로 503을 받습니다.
```bash
python3 server.py --workers 1 --queue 1    # 터미널 1: 스레드 1개, 대기열 1칸
(sleep 3 | nc localhost 8000 &) && (sleep 3 | nc localhost 8000 &) && sleep 0.3 && \
curl -s -X POST http://localhost:8000/query -d '{"sql": "SELECT * FROM users;"}'   # 터미널 2
```

## 참고

### 쓸 수 있는 SQL 문법

<details>
<summary>INSERT · SELECT · WHERE 문법과 규칙</summary>

```sql
INSERT INTO students (name, grade) VALUES ('Kim', 3);
INSERT INTO students VALUES ('Lee', 2);          -- 컬럼 생략 시 id 를 뺀 스키마 순서
SELECT * FROM students;
SELECT name, grade FROM students WHERE grade >= 2;
SELECT * FROM users WHERE id > 100;              -- id 범위 조건은 B+ 트리로
```

- 테이블 정의는 `data/schema.json`에 미리 적습니다 (`CREATE TABLE` 없음). 타입은 `INT`, `TEXT`. 첫 컬럼은 반드시 `id INT`이며 값은 자동 부여됩니다.
- 키워드는 대소문자 무관, 식별자는 소문자로 정규화. 문자열은 작은따옴표, 따옴표 자체는 `''`. 문장은 `;`로 끝나며 주석은 `--`.
- `WHERE`는 `컬럼 연산자 값` 하나만. 연산자는 `=` `!=` `<` `<=` `>` `>=`.
- 문법 오류가 하나라도 있으면 아무 문장도 실행하지 않습니다. 실행 오류가 나면 그 문장에서 멈추고, 앞 문장은 되돌리지 않습니다.

</details>

### 실제 DBMS와의 차이

<details>
<summary>MySQL·PostgreSQL과 무엇이 다르고, 왜 이렇게 만들었나</summary>

| 부분 | 실제 DBMS (MySQL, PostgreSQL) | mini-dbms | 그렇게 한 이유 |
| --- | --- | --- | --- |
| SQL 처리 | 토큰 → 구문 트리 → 실행 계획을 비교해 가장 빠른 방법 선택 | 토큰 → 구문 트리 → 바로 실행. id 조건이면 인덱스, 아니면 전체 스캔 | 테이블 하나를 조회하는 문장이라, 옵티마이저 없이도 SQL 처리 원리를 구현하기에 충분함 |
| 저장 방식 | 8\~16KB 페이지 단위. 자주 쓰는 페이지는 메모리에 캐시(버퍼 풀) | 한 줄에 한 행, 값은 탭으로 나눠 파일 끝에 붙임 | 파일을 눈으로 바로 확인할 수 있고, 값에 쉼표나 한글이 들어가도 깨지지 않음 |
| 인덱스 | B+ 트리를 디스크 페이지에 저장. 켤 때 다시 만들지 않음 | B+ 트리가 메모리에만 있음. 켤 때 파일을 읽어 다시 만듦 | 데이터 파일을 기준으로 다시 만들면 비정상 종료 뒤에도 항상 일치함 |
| 동시성 | 행 단위 잠금 + 읽는 쪽이 옛 버전을 보는 방식(MVCC) | 엔진 lock 하나[^1] | 기존 행을 고치지 않아 경합 지점이 다음 번호·파일 끝·인덱스뿐. 교착 상태가 없음. 대신 느린 쿼리는 다른 요청을 기다리게 함 |
| 트랜잭션·복구 | 여러 문장을 "모두 되거나 모두 안 되게" 묶음. 쓰기 전에 로그를 남겨(WAL) 꺼져도 복구 | 없음. 문장마다 바로 저장. 쓰다 만 마지막 줄만 켤 때 잘라 냄 | 파서·인덱스·서버에 집중. 대신 실행 중 오류면 앞 문장까지의 결과를 돌려줘 중복 재시도를 막음 |
| 연결 처리 | 자체 통신 방식 + 스레드 풀이나 프로세스 | HTTP + JSON + 직접 만든 Thread Pool | 브라우저·`curl`로 별도 드라이버 없이 테스트할 수 있고, 대기열 상한으로 503 과부하 방어를 직접 제어함 |
| 오류 | 표준 오류 코드(SQLSTATE) | 정해 둔 JSON 코드 `bad_sql`, `busy` 등 | `error.code` 하나로 원인을 구분하고, SQL 실수(400)와 서버 장애(500)를 나눠 내부 경로가 밖으로 나가지 않게 함 |

</details>

[^1]: 실제 DB의 행 단위 잠금은 기존 행을 고칠 때 그 행만 잠그는 방식입니다. 우리는 `UPDATE`·`DELETE`가 없어 고칠 행이 없고, INSERT끼리 다투는 건 테이블에 하나뿐인 다음 번호·파일 끝·B+ 트리입니다. SELECT끼리는 동시에 하게(읽기·쓰기 lock) 풀면 빨라질지도 재 봤는데, 1만 줄 전체 스캔 16개를 스레드 4개로 돌리니 209ms → 1,700ms로 오히려 느려졌습니다. 파이썬은 GIL 때문에 한 번에 한 스레드만 코드를 실행해서, 차례를 바꾸는 비용만 늘었습니다 ([STEP16](docs/eungi/STEP16.md)).

### 한계

- 인덱스는 `id`에만 있습니다. 다른 열로 찾으면 전체 스캔이고(100만 건에 1,364ms), 그동안 lock을 잡고 있어 다른 요청도 기다립니다. 다른 열에도 B+ 트리(보조 인덱스)를 만들 수 있지만, 같은 값이 여러 행에 있을 수 있고 INSERT마다 인덱스를 하나씩 더 고쳐야 해서 이번 범위에서는 하지 않았습니다.
- 열을 추가하면 이미 저장된 줄은 칸 수가 맞지 않아 읽을 수 없습니다(손상된 행 오류). 옛 줄에 기본값을 채우는 기능(`ALTER TABLE`)은 없습니다.
- 같은 데이터 폴더에 한 번에 한 프로세스만 쓴다고 가정합니다. 서버가 켜진 채로 같은 폴더에 CLI로 쓰는 것은 막지 못합니다.
- 범위가 넓으면(`id > 0`) 줄마다 위치로 읽어서 전체 스캔보다 느릴 수 있습니다. 비용을 따져 경로를 고르는 기능은 없습니다.
- 100만 건을 CLI로 넣을 때 메모리를 약 1.7GB 씁니다 (파일 전체를 먼저 해석하는 구조).
- `CREATE TABLE`, `UPDATE`, `DELETE`, NULL, `AND`/`OR`, `ORDER BY`, `LIMIT`, JOIN, 트랜잭션, WAL은 지원하지 않습니다.

### 문서

| 문서 | 이럴 때 읽기 |
| --- | --- |
| [왜 DBMS인가](docs/study/WHY_DBMS/WHY_DBMS.md) | DBMS가 어떤 문제를 풀려고 나왔는지 폴더 하나 예시로 보고 싶을 때. **처음이면 여기부터** |
| [전체 그림](docs/study/OVERVIEW.md) | SQL 한 줄이 파일에 저장되고 다시 꺼내지기까지를 코드로 따라가고 싶을 때 |
| [설계](docs/DESIGN.md) | 단계별로 무엇을 만들고, 언제 완료인지 볼 때 |
| [Phase 1 단계 문서](docs/steps/) | 토크나이저부터 엣지 케이스까지, SQL 처리기의 단계별 설계와 결정 |
| [Phase 2](docs/phase2.md) | B+ 트리를 실행기에 붙인 방법, 범위 검색, 100만 건 성능 비교 |
| [Phase 3](docs/eungi/) | Thread Pool([STEP15](docs/eungi/STEP15.md)), lock([STEP16](docs/eungi/STEP16.md)), 오류 응답([STEP17](docs/eungi/STEP17.md)) |
| [결정 기록](docs/eungi/DECISIONS.md) | "왜 이렇게 만들었나"를 결정 번호로. Phase 1(H1\~H12), Phase 2(S1\~S7), Phase 3(D30\~D48) |
| [학습 노트](docs/study/DBMS_study.md) | "왜 이렇게 만드나"를 설명할 수 있는지 스스로 확인할 때 |
| [과제 요구사항](docs/REQUIREMENTS.md) | 과제 원문 |
