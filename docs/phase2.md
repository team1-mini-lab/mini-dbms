# Phase 2: B+ 트리 인덱스 이식 (7~10단계)

## 목표

`SELECT * FROM users WHERE id = 777777;` 이 들어왔을 때, 100만 줄 파일을 처음부터 읽지 않고 그 한 줄만 바로 읽는다.

이 문서가 끝나면 가능한 것:
- `WHERE id = 값` 조회가 행 수와 거의 상관없이 일정하게 빠르다. (100만 건에서 0.03ms, 전체 스캔보다 약 4만 배)
- CLI를 다시 실행해도 인덱스가 파일에서 다시 만들어진다.
- 1만, 10만, 100만 건에서 두 경로를 비교하는 벤치마크를 한 줄로 돌릴 수 있다.

아직 안 되는 것:
- `id` 가 아닌 컬럼(`name`, `grade` 등)으로 찾기는 여전히 전체 스캔이다.
- `id != 값` 은 전체 스캔이다. (거의 모든 행이 해당하므로 인덱스가 이득이 없다)
- 인덱스는 메모리에만 있다. 디스크에 저장하지 않으므로 실행할 때마다 다시 만든다.

somang 브랜치의 B+ 트리와 벤치마크를 hnjee 브랜치의 Phase 1 구조(파서, 실행기, 저장소 세 층)에 옮겨 심은 결과다.

## 이 단계의 위치

Phase 1에서 만든 여섯 순서 그대로다.

```
SQL 파일 → ① CLI 입력 → ② 토크나이저 → ③ 파서 → ④ 실행기 → ⑤ 저장소 → ⑥ CLI 출력
```

바뀌는 곳은 **④ 실행기 한 곳**이다. 실행기가 저장소를 부르기 직전에 "트리로 찾을까, 처음부터 읽을까"를 고르는 갈림길이 생긴다.

```
SELECT * FROM students WHERE id = 3;
                │
          ④ 실행기: 조건이 id = 값 인가? (범위 조건은 2절 ⑤)
           ├─ 예  → B+ 트리.search(3) → 오프셋 → 저장소.read_at(오프셋)   (한 줄만 읽음)
           └─ 아니오 → 저장소.scan()  → 한 줄씩 조건 검사                    (Phase 1 그대로)
```

⑤ 저장소는 고치지 않았다. Phase 1에서 "줄이 시작하는 바이트 위치를 행의 주소(오프셋)로 쓴다", "append 가 오프셋을 돌려준다", "read_at(오프셋) 으로 한 줄만 읽는다"를 미리 정해 두었기 때문에, 인덱스는 그 오프셋을 저장하기만 하면 된다.

## 1. somang 브랜치에서 무엇을 가져왔나

somang 브랜치는 Phase 1 초기 버전(루트의 `parser.py`, `storage.py`, `cli.py`) 위에서 만들어졌다. 그래서 파일을 통째로 합치지 않고, Phase 2에만 해당하는 부분을 골라 옮겼다.

| somang 원본 | 이식 결과 | 처리 |
| --- | --- | --- |
| `index.py` 의 `BPlusTree`, `Node` | [minidb/bptree.py](../minidb/bptree.py) | **그대로** 옮김. 바뀐 것은 위치와 파일 맨 위 설명뿐 |
| `engine.py` 의 인덱스 로직 | [minidb/executor.py](../minidb/executor.py) | **로직만** 실행기의 해당 자리에 옮김 (2절) |
| `checks/check_bptree.py`, `checks/check_index.py` | [tests/test_bptree.py](../tests/test_bptree.py) | 검사 내용 그대로 pytest 로 옮김 |
| `bench/make_sql.py` | [bench/make_sql.py](../bench/make_sql.py) | 그대로. 사용법 문구만 수정 |
| `bench/run_bench.py` | [bench/run_bench.py](../bench/run_bench.py) | 측정 방식과 출력 표는 그대로. Engine → minidb 실행기, `cli.py` → `python -m minidb` 로 교체 |

가져오지 않은 것과 이유:

| somang 원본 | 이유 |
| --- | --- |
| `parser.py`, `storage.py`, `cli.py` | `minidb/` 의 같은 층과 역할이 겹친다. Phase 1 쪽이 오류 위치 보고, 이스케이프, 잘린 행 복구 등을 이미 다룬다 |
| `engine.py` 의 나머지 (`split(";")`, `_arrange`, 타입 검사) | 각각 minidb 의 파서, `_resolve_insert_values`, `_literal_matches` 가 이미 한다 |
| `engine.py` 의 `SELECT *` 만, `=` 만 제한 | 실행기 안에 넣으면서 필요 없어졌다 (2절 ③) |
| `DictIndex` | B+ 트리 전의 임시 대역 |
| `engine.py` 의 `threading.Lock`, `@locked`, `stop_on_error`, `server.py`, `checks/check_concurrency.py` | Phase 3(서버, 동시성) 몫이다. Phase 3 이식 때 다룬다 |
| `data/schema.json` (리스트 형식) | minidb 의 카탈로그 형식과 다르다. 벤치마크용 `users` 테이블은 벤치마크 스크립트가 임시 폴더에 직접 만든다 |

## 2. 실행기에서 바뀐 곳

somang 의 `Engine` 이 하던 인덱스 일 세 가지를, minidb 실행기에서 같은 일을 하던 자리에 하나씩 넣었다.

### ① 테이블을 처음 쓸 때 트리 만들기 (8단계: 재시작 복구)

**왜 필요한가.** 트리는 메모리에만 있다. CLI는 실행할 때마다 새 프로세스이므로, 지난번에 넣은 100만 건의 트리는 사라지고 파일만 남는다. 그래서 시작할 때 파일을 한 번 읽어 트리를 다시 만들어야 한다.

| | somang | 이식 후 |
| --- | --- | --- |
| 언제 | `Engine.__init__` 에서 **모든 테이블**을 시작하자마자 | 그 테이블을 **처음 쓸 때** (`_load`) |
| 무엇을 | 스캔하며 트리와 next_id 를 같이 만듦 | 같음 |

Phase 1의 `_next_id` 는 이미 "테이블을 처음 쓸 때 한 번 스캔해서 최대 id 를 찾는" 일을 하고 있었다. 이 스캔에 `index.insert(id, offset)` 한 줄을 더하고, 이름을 `_load` 로 바꿨다.

이름을 바꾼 이유는, 이제 이 함수가 INSERT 전용이 아니기 때문이다. 재시작 직후 첫 문장이 `SELECT ... WHERE id = 1` 이면 INSERT 를 거치지 않으므로, SELECT 도 `_load` 를 불러 트리를 만들어야 한다.

처음 쓸 때 만드는 방식을 유지한 이유: 테이블이 여러 개일 때 이번 실행에서 쓰지 않는 테이블까지 읽을 필요가 없다.

### ② INSERT 할 때 트리에 등록하기 (8단계)

```python
offset = self.storage.table(table.name).append(row)   # Phase 1 에서는 돌려받은 offset 을 버렸다
self._next_ids[table.name] = new_id + 1
index.insert(new_id, offset)
```

**순서가 중요하다.** 파일에 먼저 쓰고, 성공했을 때만 번호를 올리고 트리에 등록한다. 쓰기가 실패하면(디스크 가득 참 등) 예외가 나서 아래 두 줄이 실행되지 않으므로, 트리에는 파일에 없는 행이 등록되지 않는다.

이 과정에서 Phase 1과 달라진 점이 하나 있다. Phase 1은 쓰기 **전에** 번호를 올렸기 때문에, 쓰기가 실패하면 그 번호를 건너뛰었다. somang 엔진처럼 쓰기 **후에** 올리도록 바꿨다. (`test_failed_write_does_not_consume_id`)

### ③ SELECT 경로 선택 (9단계: 가장 단순한 옵티마이저)

Phase 1에서 "9단계에서 이 자리에 들어간다"고 주석으로 비워 둔 전체 스캔 반복문 자리다.

```python
predicate = self._make_predicate(table, stmt.where)    # 컬럼, 타입 검증은 경로와 무관하게 먼저
if cond is not None and cond.column == "id" and cond.op == "=":
    offset = self._load(table).search(cond.value)
    candidates = [] if offset is None else [table_file.read_at(offset)]
    used_index = True
else:
    candidates = (row for _offset, row in table_file.scan())
    used_index = False
rows = [... for row in candidates if predicate(row)]
```

세 가지를 의도했다.

- **검증을 먼저 한다.** 갈림길을 `_make_predicate` 뒤에 두었으므로 `WHERE id = 'abc'` 는 인덱스 경로로 가기 전에 타입 오류가 난다.
- **오프셋 0 을 '없음' 과 구별한다.** 첫 행의 오프셋은 0 이다. `if offset:` 으로 쓰면 첫 행을 못 찾는다. 그래서 `is None` 으로 확인한다.
- **나머지 처리는 두 경로가 같다.** 인덱스 경로도 후보 행을 같은 `predicate` 와 컬럼 고르기에 통과시킨다. 그래서 somang 엔진에 있던 "`SELECT *` 만", "`=` 만" 제한이 사라졌고, `SELECT name, grade FROM students WHERE id = 4;` 도 인덱스를 탄다.

처음 이식할 때는 DESIGN.md 9단계의 범위(`WHERE id = ?`)대로 `=` 만 인덱스를 썼다. 이후 범위 조건을 추가했다 (⑤).

### ④ 결과에 경로 표시: `QueryResult.used_index`

**왜 필요한가.** 인덱스가 실제로 쓰였는지 결과만 봐서는 알 수 없다. 두 경로는 같은 행을 돌려주기 때문이다. 테스트와 벤치마크가 "id 조회는 인덱스를, name 조회는 스캔을 탔다"를 확인하려면 표시가 필요하다. somang 엔진의 결과 딕셔너리에 있던 `used_index` 를 `QueryResult` 필드로 옮겼다.

```python
used_index: bool = field(default=False, compare=False)
```

- `default=False`: INSERT 결과와 기존 코드는 손대지 않아도 된다.
- `compare=False`: `==` 비교에서 뺀다. "인덱스로 찾은 결과 == 스캔으로 찾은 결과" 를 그대로 비교할 수 있고, Phase 1 테스트 223개도 고칠 필요가 없다.

CLI 출력은 바꾸지 않았다. 사용자에게 보이는 결과는 경로와 상관없이 같아야 하기 때문이다.

### ⑤ id 범위 조건도 인덱스로 (Phase 3 이관 전 추가)

**왜 필요한가.** `id < 10`, `id >= 999990` 처럼 id 구간을 찾는 조건도 전체 스캔이었다. somang 트리에는 리프 연결을 따라가는 `range_search(start, end)` 가 이미 있었으므로, 실행기 갈림길에 한 갈래만 더했다.

```python
elif cond is not None and cond.column == "id" and cond.op in ("<", "<=", ">", ">="):
    start, end = _id_bounds(cond.op, cond.value)          # 예: id < 10 → [-inf, 9]
    pairs = self._load(table).range_search(start, end)
    candidates = (table_file.read_at(off) for off in sorted(off for _key, off in pairs))
    used_index = True
```

- **구간 바꾸기.** `range_search` 는 양끝을 포함한다. id 는 정수이므로 `< v` 는 `<= v-1`, `> v` 는 `>= v+1` 로 바꾸고, 열린 쪽은 무한대로 둔다.
- **파일 순서로 읽는다.** 트리는 id 순으로 돌려주지만, 오프셋을 정렬해서 읽으면 스캔과 같은 순서(파일 순서)가 된다. 파일을 직접 편집해 id 순서가 섞여 있어도 두 경로의 결과가 같다. (`test_range_keeps_file_order_with_unsorted_ids`)
- **검증과 마무리는 `=` 경로와 같다.** 타입 검사가 먼저이고, 후보 행은 같은 `predicate` 를 한 번 더 통과한다.
- **`!=` 는 스캔으로 둔다.** 거의 모든 행이 해당해서 트리를 거쳐도 이득이 없다.

범위가 넓으면(예: `id > 0`) 결국 모든 행을 `read_at` 으로 하나씩 읽으므로 스캔보다 느릴 수 있다. 비용으로 경로를 고르는 옵티마이저는 범위 밖이다.

## 3. 바꾸지 않은 곳

| 파일 | 이유 |
| --- | --- |
| `storage.py` | `append` 의 오프셋 반환, `read_at` 이 Phase 1에 이미 있다 |
| `lexer.py`, `parser.py`, `ast.py` | 문법이 그대로다 |
| `catalog.py`, `data/schema.json` | 테이블 정의 방식이 그대로다 |
| `cli.py` | 실행기만 부르므로 인덱스를 몰라도 된다 |

인덱스를 아는 층은 실행기 하나뿐이다. Phase 1에서 "실행기만 카탈로그와 저장소를 둘 다 안다"고 경계를 정해 둔 덕분에, 기능 하나를 붙이는 데 고칠 곳이 한 파일로 모였다.

## 4. 벤치마크 결과 (10단계)

```sh
python bench/run_bench.py 1000 10000 100000
python bench/run_bench.py 1000000
```

2026-11-18, 이 저장소의 .venv (Python 3.13) 로 측정:

| 건수 | CLI로 넣기 | 첫 조회(B+ 트리 다시 만들기 포함) | 트리 높이 | id로 찾기 (인덱스) | name으로 찾기 (전체 스캔) | 배 |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 0.1초 | 0.00초 | 3 | 0.028ms | 1.2ms | 42배 |
| 10,000 | 0.5초 | 0.02초 | 4 | 0.031ms | 12.3ms | 391배 |
| 100,000 | 4.5초 | 0.17초 | 4 | 0.031ms | 131.7ms | 4,233배 |
| 1,000,000 | 48.4초 | 1.87초 | 5 | 0.032ms | 1364.1ms | 43,094배 |

읽는 법:
- **id 로 찾기는 행 수가 1000배가 돼도 거의 같다.** 트리 높이는 3 → 5 로 두 칸만 늘었다. 노드당 키가 최대 32개라서 한 칸 내려갈 때마다 후보가 수십 분의 일로 준다.
- **name 으로 찾기는 행 수에 정비례한다.** 1만 → 10만 → 100만에서 12 → 132 → 1364ms. 전체 스캔이기 때문이다.
- **재시작 비용은 행 수에 비례한다.** 100만 건이면 첫 조회에 약 1.9초가 든다. 인덱스를 메모리에만 두는 대가다.
- 시간은 파싱 + 실행 전체 기준이다. id 조회 0.03ms 의 상당 부분은 파싱이다.

## 5. 남은 문제 (다음 결정거리)

**100만 건 적재 시 메모리 1.7GB.** `/usr/bin/time -l` 로 100만 줄 SQL 파일 적재를 재 보니 최대 메모리가 약 1.7GB 였다. CLI가 "파일 전체를 먼저 파싱하고, 문법 오류가 없으면 실행한다"(Phase 1 2단계 결정)이기 때문에, 100만 개 문장의 토큰과 AST 를 한꺼번에 메모리에 들고 있다. 동작은 하지만 1000만 건이면 버티기 어렵다. 선택지:
- 문장 단위로 파싱하고 바로 실행하는 경로를 추가한다. 대신 "문법 오류가 있으면 아무것도 실행하지 않는다" 규칙을 포기하거나 두 번 읽어야 한다.
- 벤치마크 적재만 CLI 대신 실행기를 직접 부른다. 과제 요구("SQL 처리기로 넣기")와의 관계를 따져야 한다.

**INSERT 마다 flush.** 100만 번 시스템 호출이 일어난다. 적재 48초 중 얼마가 flush 인지는 아직 따로 재지 않았다. DESIGN.md 10단계의 "쓰기 버퍼링" 주제다.

**같은 id 가 파일에 두 번 있으면.** 실행기는 같은 id 를 두 번 만들지 않지만, 파일을 직접 편집하면 생길 수 있다. 그때 트리는 덮어쓰기(somang 트리의 규칙)라서 마지막 줄만 가리키고, 스캔은 두 줄을 모두 낸다. 인덱스 경로와 스캔 경로의 결과가 달라질 수 있다. 같은 키가 들어오면 오류를 내도록 바꿀지 정할 수 있다.

**인덱스 삽입 비용.** DESIGN.md 10단계는 "인덱스가 있을 때와 없을 때 INSERT 속도 차이"도 재라고 한다. 아직 측정하지 않았다.

## 6. 산출물과 완료 기준

| 파일 | 내용 |
| --- | --- |
| `minidb/bptree.py` | 새 파일. somang 의 BPlusTree |
| `minidb/executor.py` | `_load` (구 `_next_id`), INSERT 후 등록, SELECT 경로 선택, `QueryResult.used_index` |
| `tests/test_bptree.py` | 새 파일. 트리 단독 테스트 16개 (somang 의 check 스크립트 이식) |
| `tests/test_index.py` | 새 파일. 실행기 연동 테스트 55개 (범위 조건 포함) |
| `bench/make_sql.py`, `bench/run_bench.py` | 새 파일. somang 의 벤치마크를 minidb 에 맞춤 |
| `docs/DESIGN.md`, `README.md` | 프로젝트 구조(`scripts/` → `bench/`)와 벤치마크 실행법 |

완료 기준:
- `pytest` 전체 통과: Phase 1 223개 + Phase 2 71개 = 294개.
- `WHERE id = 값` 은 `used_index=True` 이고 scan 을 부르지 않는다. (`test_index_lookup_does_not_scan`)
- `WHERE id < / <= / > / >= 값` 도 인덱스를 타고, 결과가 스캔과 같다. (`test_range_index_matches_scan`, `test_range_lookup_does_not_scan`)
- 같은 행을 id 와 name 으로 찾은 결과가 같다. (`test_index_and_scan_give_same_row`)
- 실행기를 새로 만들어도(재시작) id 조회가 된다. (`test_restart_rebuilds_index`, `test_select_first_after_restart_builds_index`)
- `python bench/run_bench.py 1000000` 이 끝까지 돈다.
