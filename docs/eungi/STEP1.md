# 1단계: CLI

## 목표

터미널에서 SQL 파일을 넣으면 실행되게 합니다. `INSERT`는 ID를 붙여 파일에 한 줄 추가하고, `SELECT *`는 파일 전체를 보여 줍니다. `INSERT` 두 번 뒤 `SELECT * FROM users;`에 ID 1, 2가 붙은 줄이 나오고, CLI를 다시 실행해도 다음 ID가 이어지면 완료입니다.

## 핵심 문제: 엉성해도 경계는 진짜로

```
cli.py      SQL 파일을 읽어 engine.execute(sql)에 넘기고 결과를 출력
   │  engine.execute(sql)                  ← 접점 1
   ▼
engine.py   문장을 나누고 → 파서에 넘기고 → 결과를 접점 1 모양으로 모음
   │  parse(stmt) → Insert / Select        ← 접점 2
   ▼
parser.py   (임시) 정규식으로 예제 SQL만 처리
storage.py  파일 끝에 쓰기 · 위치로 한 줄 읽기 · 처음부터 읽기
```

- 파서는 엉성해도 되지만, 돌려주는 모양은 접점 2의 `Insert`, `Select` 그대로입니다. 그래야 4\~5단계에서 파서만 바꿔 끼울 수 있습니다.
- 엔진은 파일이 JSON인지 모릅니다. `storage.append`, `storage.scan`만 부릅니다.

## 질문과 정리

| 질문 | 정리 |
| --- | --- |
| 다음 ID는 어디서 알아내나 | 엔진을 만들 때 테이블 파일을 한 번 읽어 가장 큰 ID + 1로 정함. CLI는 실행할 때마다 새로 켜지므로, 이걸 안 하면 두 번째 실행에서 또 1부터 붙음 |
| 열 순서가 다르게 오면 | 실행기가 `schema.json`의 열 순서(id 제외)에 맞춰 값을 다시 배치함. 열 이름을 생략하면 그 순서 그대로 |
| 한 문장이 틀리면 | 그 문장만 `{"type": "error", ...}` 결과로 담고, 다음 문장은 계속 실행 |

## 이 단계에서 정한 것

| 관련 코드 | 정한 것 | 이유 |
| --- | --- | --- |
| `parser.py` `parse` | 임시 파서는 정규식으로 `INSERT INTO t [(열들)] VALUES (값들)`, `SELECT * FROM t [WHERE 열 = 값]`만 처리 | 지도 단계는 끝까지 도는 것이 우선 (DESIGN.md 제안과 같음) |
| `parser.py` `Where`, `Insert`, `Select` | 명령 구조는 `dataclass` | 접점 2 모양을 그대로 코드로 옮김. `stmt.table`처럼 이름으로 꺼냄 |
| `parser.py` `parse` | 열 이름을 생략하면 `columns=None` | DESIGN.md 접점 2에 맞춤 |
| `engine.py` `execute` | 문장 구분은 임시로 `sql.split(";")` | 4단계에서 토큰으로 자른 뒤 나누도록 바꿈 |
| `engine.py` `execute` | 실패한 문장은 결과에 `{"type": "error", "message": ...}`로 담고 계속 실행 | 접점 1 모양. 9단계 오류 처리의 최소한 |
| `engine.py` `__init__` | 엔진을 만들 때 테이블 파일을 읽어 다음 ID를 다시 정함 | CLI는 매번 새로 켜짐. 다음 ID = 가장 큰 ID + 1 (DESIGN.md 제안과 같음) |
| `engine.py` `next_id` | 다음 ID는 테이블마다 따로 셈 | 테이블이 둘 이상이면 번호가 섞이지 않게 |
| `engine.py` `_arrange` | 값을 `schema.json` 열 순서에 맞춰 배치. 없는 열이면 오류 | 열 순서를 바꿔 적어도 똑같이 저장됨 |
| `storage.py` `append` | 파일은 바이너리 추가 모드(`"ab"`)로 열고, 쓰기 전 `tell()`로 위치를 돌려줌 | 한글은 한 글자가 3바이트라 글자 수와 바이트 수가 다름. 2단계 인덱스가 이 위치를 씀 |
| `storage.py` `append` | 한 줄에 JSON 배열 하나 (`ensure_ascii=False`) | 쉼표·한글이 든 값도 안전하고 파일을 열어 읽을 수 있음 (DESIGN.md 제안과 같음) |

[DECISIONS.md](./DECISIONS.md)에도 같은 내용이 모여 있습니다.

## 만드는 파일

| 파일 | 내용 |
| --- | --- |
| `storage.py` | `Storage` 클래스. `append(table, row) -> offset`, `read_at(table, offset)`, `scan(table)` |
| `parser.py` | `Where`, `Insert`, `Select`와 임시 `parse(stmt)` |
| `engine.py` | `Engine(data_dir)`, `execute(sql)`, `close()` (접점 1) |
| `cli.py` | 파일 이름을 받아 `engine.execute`의 결과를 한 줄씩 출력 |

만드는 순서는 아래쪽부터입니다: `storage.py` → `parser.py` → `engine.py` → `cli.py`.

## 완료 테스트

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql
```

```
{'type': 'insert', 'id': 1}
{'type': 'insert', 'id': 2}
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[1, '현지', 25], [2, '민수', 31]], 'used_index': False}
```

| 확인 방법 | 기대 결과 |
| --- | --- |
| 위 명령 | ID 1, 2가 붙은 두 줄 |
| `cat data/users.tbl` | `[1, "현지", 25]`와 `[2, "민수", 31]` 두 줄 |
| `python3 cli.py examples/step1.sql`을 한 번 더 | `id`가 3, 4로 이어지고 `rows`가 네 줄 (아래 실제 결과) |
| `INSERT INTO users (age, name) VALUES (31, '민수');` | 파일에 `[n, "민수", 31]`로 저장됨 (순서가 바뀌어도 맞게) |
| `INSERT INTO users (email) VALUES ('x');` | `{'type': 'error', 'message': 'users 테이블에 없는 열입니다: email'}` |

실제로 두 번째 실행한 결과입니다.

```
{'type': 'insert', 'id': 3}
{'type': 'insert', 'id': 4}
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[1, '현지', 25], [2, '민수', 31], [3, '현지', 25], [4, '민수', 31]], 'used_index': False}
```

처음부터 다시 확인하려면 `rm data/users.tbl`로 데이터 파일을 지웁니다. ID가 다시 1부터 시작합니다.

## 나중에 바꿔 끼울 곳

| 지금 (임시) | 바뀌는 단계 | 바뀌는 모습 | 안 고쳐도 되는 곳 |
| --- | --- | --- | --- |
| 정규식 임시 파서 | 4\~5단계 | 토크나이저 + 재귀 하강 파서 | 엔진. 접점 2 모양이 같음 |
| `sql.split(";")` | 4단계 | 토큰으로 자른 뒤 `;`로 나눔 (`'a;b'` 안의 `;`를 안 자름) | `execute`의 결과 모양 |
| 열 검사는 "없는 열"만 | 6단계 | 타입(INT/TEXT), 열 수까지 검사 | 파서 |
| 오류는 예외 메시지 그대로 | 9단계 | 무엇이 틀렸는지 알아보기 쉬운 메시지 | 접점 1 모양 |
| 켤 때 파일을 다시 읽기 (간단히) | 8단계 | 깨진 마지막 줄 처리 등 재시작 상황 전체 | 엔진 바깥 |

## 문제가 생기면

| 증상 | 해결 |
| --- | --- |
| 두 번째 실행에서 ID가 다시 1부터 | `Engine.__init__`에서 `storage.scan`으로 다음 ID를 다시 정하는지 확인 |
| 한글이 `현`처럼 보임 | `json.dumps(..., ensure_ascii=False)`인지 확인 |
| `KeyError: 'users'` | `data/schema.json`이 있는지, 실행 위치가 `mini-dbms` 폴더인지 확인 |

## 코드에서 알아 둘 것

- `@dataclass`: `Insert(table="users", columns=[...], values=[...])`처럼 이름 붙은 칸을 가진 클래스를 짧게 만듭니다.
- `f.tell()`: 지금 파일의 몇 바이트째인지 알려 줍니다. 추가 모드에서는 파일 끝 위치예요.
- `scan`은 `yield`로 한 줄씩 돌려줍니다. 100만 줄이어도 한꺼번에 메모리에 올리지 않습니다.
