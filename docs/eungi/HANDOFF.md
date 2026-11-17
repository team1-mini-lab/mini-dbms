# 인수인계: 지도 만들기(0\~3단계)

**누가**: 은기 · **브랜치**: `eungi` · **다음 담당**: Phase 1(SQL 처리기, 4\~9단계), Phase 2(B+ 트리, 10\~14단계)

**읽는 순서**: 이 문서 → [DESIGN 2절 접점](../DESIGN.md#2-구조)(파일끼리의 약속) → [DESIGN 3절](../DESIGN.md#3-개발-순서)에서 내 Phase의 표. 단계별 자세한 설명은 [STEP0](./STEP0.md) · [STEP1](./STEP1.md) · [STEP2](./STEP2.md) · [STEP3](./STEP3.md), Phase 3는 [STEP16](./STEP16.md) · [STEP15](./STEP15.md), 정한 것의 전체 목록은 [결정 기록](./DECISIONS.md), **팀원 Q&A 보충은 [QA](./QA.md)**에 있습니다.

## 🔄 수정사항 (처음 공유한 뒤 바뀐 것)

처음 공유한 뒤 아래가 바뀌었습니다. **코드 동작이 바뀐 것은 1번 하나**이고, 나머지는 문서와 확인 도구입니다.

| # | 무엇이 | 어떻게 바뀌었나 | 영향 |
| --- | --- | --- | --- |
| 1 | **서버의 틀린 SQL 응답** | 전에는 200을 보내고 뒤 문장도 계속 실행했습니다. 이제는 **첫 오류에서 멈추고 400**을 보내며, 그 전까지 실행된(이미 저장된) 문장의 결과를 `results`에 같이 담습니다. DESIGN 접점 4, 결정 9와 맞췄습니다. CLI는 그대로 계속 실행합니다 | `engine.execute(sql, stop_on_error=False)` 인자가 생김 (기본값이라 기존 호출은 그대로). `server.py`의 `do_POST`. [STEP3](./STEP3.md#잘못-보내면-어떻게-되나요), [D30](./DECISIONS.md) |
| 2 | 단계 표기 | "4단계" → "Phase 1(4단계)"처럼 Phase를 붙여 씁니다. 0–3단계는 "지도 만들기(1단계)" | 문서 전체, DESIGN, OVERVIEW |
| 3 | 핵심 코드 설명 | STEP1–3에 "핵심 코드" 절을 추가하고, 이 문서 5·6절에 각자 고칠 코드를 넣었습니다 | 문서만 |
| 4 | 확인 스크립트 | `checks/` 폴더 추가 (`check_all`, `check_parser`, `check_index`) | 새 파일. 기존 코드는 안 바뀜 |
| 5 | OVERVIEW 1절 그림 | "모든 단계가 끝난 뒤의 모습"이라는 안내와, 지금 코드와의 차이 표를 넣었습니다 | 문서만 |
| 6 | 결정 기록 | 결정마다 번호(D1–D30)를 붙였습니다 | 문서만 |

## 먼저 알아 둘 네 가지

1. **id는 사람이 안 넣고 엔진이 1, 2, 3… 붙입니다.** 엔진은 켜질 때 데이터 파일을 읽어서 다음 번호를 다시 정하므로, 껐다 켜도 번호가 이어집니다.
2. **id로 찾으면 목차(인덱스)를 쓰고, 다른 열로 찾으면 파일을 처음부터 읽습니다.** 이 둘의 속도 차이를 Phase 2(14단계)에서 잽니다.
3. **CLI와 서버 중 데이터를 쓰는 건 하나만 켜고 씁니다.** CLI와 서버는 따로 실행되어서 "다음 번호"를 각자 기억합니다. 둘이 같이 쓰면 id가 겹칠 수 있습니다.
4. **엔진은 항상 `engine.execute`로만 부릅니다.** Phase 3(16단계)의 lock이 `execute`에 걸려 있어서, 엔진 밖에서 `_run`이나 `storage`, `index`를 직접 부르면 동시 요청에서 id가 겹칠 수 있습니다 ([STEP16](./STEP16.md)).

## 1. 지금 어디까지 됐나

엉성하지만 **SQL 넣기 → 파일에 저장 → id로 찾기 → 서버로 요청**까지 처음부터 끝까지 동작합니다.

| 단계 | 된 것 |
| --- | --- |
| 0. 준비 | `data/schema.json`(테이블 모양), `examples/`(확인용 SQL) |
| 1. CLI | 터미널에서 SQL 파일 실행. `INSERT`하면 id가 자동으로 붙고, 다시 켜도 이어짐 |
| 2. 임시 인덱스 | `WHERE id = ?`는 dict 목차로 그 한 줄만 읽음. 다른 열은 처음부터 읽으며 거름 |
| 3. API 서버 | `POST /query`로 SQL을 받아 CLI와 같은 결과를 JSON으로 돌려줌 (한 번에 요청 하나) |

두 검토자(설계 쪽, 구현 쪽)가 서로 따로 코드를 돌려 보고 교차 검토해서 아래를 고쳤습니다: 다른 열 WHERE 거르기, 틀린 INSERT가 번호를 건너뛰지 않게, INSERT 열 검사(없는 열·빠진 열·중복·id 직접 넣기), WHERE 값 타입 검사, 잘못된 요청에 400 응답.

## 2. 3분 안에 돌려 보기

**코드 받기** (처음 한 번). 내 작업 브랜치는 `eungi`에서 갈라서 만듭니다. 브랜치 이름은 예시입니다.
```bash
cd ~/dev/mini-dbms          # 저장소가 있는 곳
git fetch
git checkout -b phase1 origin/eungi     # Phase 2라면 phase2
```

저장소 맨 위 폴더(`mini-dbms`)에서 실행합니다. 설치할 것은 없습니다 (파이썬 3.8 이상).

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql      # id 1, 2가 붙고 전체 두 줄
python3 cli.py examples/step2.sql      # 민수 한 줄, used_index: True
```

| 결과에 보이는 것 | 뜻 |
| --- | --- |
| `'type': 'insert', 'id': 1` | 저장됐고 엔진이 id 1을 붙임 |
| `'rows': [[1, '현지', 25], ...]` | 찾은 행들. 한 행 = `[id, 이름, 나이]` |
| `'used_index': True` | 목차로 바로 찾음. `False`면 파일을 처음부터 읽음 |

**전체가 잘 도는지 한 번에 확인**: 아래 명령은 지금 되는 것 11개와 나중 단계에서 될 것 4개를 확인합니다. 임시 폴더에서 돌아서 `data/users.tbl`은 건드리지 않습니다.
```bash
python3 checks/check_all.py      # "지금 통과해야 하는 것: 11/11"이면 정상
```

서버는 터미널 두 개로:
```bash
python3 server.py                                                                       # 터미널 1
curl -X POST http://localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id = 2;"}'  # 터미널 2
```

## 3. 파일 지도

```
cli.py ─┐
        ├─→ engine.py ─→ parser.py   (임시 파서: 정규식)
server.py┘     │
               ├─→ storage.py        (파일 쓰기/읽기)
               └─→ index.py          (dict 목차)

checks/        내 작업이 기존 동작을 깨지 않았는지 확인하는 스크립트 (5절, 6절)
```

**접점** = 파일끼리 주고받는 약속(함수 이름, 넘기는 값, 돌려받는 값). 약속만 지키면 파일 안을 바꿔도 다른 파일은 안 고쳐도 됩니다. 원본은 [DESIGN 2절](../DESIGN.md#2-구조)이고, 아직 **제안** 상태라 첫 회의에서 정합니다. 지금 코드는 이 제안대로 만들어져 있습니다.

| 파일 | 하는 일 | 다른 파일과의 약속 |
| --- | --- | --- |
| `cli.py` | SQL 파일을 읽어 엔진에 넘기고 출력 | `engine.execute(sql)` |
| `server.py` | HTTP로 받은 SQL을 엔진에 넘기고 JSON으로 응답 | 접점 4: `POST /query` `{"sql": "..."}` |
| `engine.py` | 문장 나누기, 파서 부르기, **실행**(검사, id 붙이기, 목차/파일 사용) | 접점 1: 결과는 `{"type": "insert" / "select" / "error", ...}` |
| `parser.py` | SQL 문장 → 정해진 모양(`Insert` / `Select` / `Where`) | 접점 2 (아래 5절에 예시) |
| `storage.py` | `append` (끝에 쓰고 위치 반환), `read_at` (위치로 한 줄), `scan` (처음부터) | 엔진만 씀 |
| `index.py` | `insert(id, 위치)`, `search(id)` → 위치 또는 `None` | 접점 3 |

**[전체 그림(OVERVIEW) 1절](../study/OVERVIEW.md)의 그림과 다른 이유**: 그 그림은 모든 단계가 끝난 뒤의 모습입니다. 지금은 아래 넷이 아직 없습니다. `tokenizer.py`는 Phase 1(4단계), `executor.py`는 Phase 1(6단계)에 생기고 그 전까지는 `engine.py` 안에 있습니다. `bptree.py`는 Phase 2(12단계)에 `index.py`를 대신하고, lock은 Phase 3(16단계)에 생깁니다. 차이 표는 OVERVIEW 1절 그림 바로 아래에 있습니다.

"실행기"는 `engine.py` 안의 `_run`처럼 **파서가 만든 명령을 실제로 수행하는 부분**을 말합니다. 지금은 `engine.py` 안에 있고, 나중에 `executor.py`로 떼어 낼 수 있습니다.

## 4. ⚠️ 알고 써야 할 것

| 상황 | 무슨 일 | 어떻게 |
| --- | --- | --- |
| 서버를 켜 둔 채로 CLI로 `INSERT` | id가 겹침 | **쓰는 건 둘 중 하나만.** 서버가 켜져 있으면 INSERT는 서버로. CLI로 넣었으면 서버를 다시 켜기 |
| 글자 값 안에 `;`, `,` (예: `'김,철수'`, `'a;b'`) | 임시 파서가 잘못 자름. `;` 뒤가 따로 실행될 수도 있음 | Phase 1(4단계) 진짜 토크나이저에서 해결. 그 전엔 쓰지 않기 |
| `SELECT name FROM ...`(열 고르기), `WHERE id > 3` | 오류: 아직 처리 안 함 | 열 고르기는 Phase 1(6단계), 범위 검색은 차별화(20단계) |
| 숫자 열에 글자 넣기 (`age`에 `'abc'`) | 그냥 저장됨 | Phase 1(6단계) 타입 검사 |
| `data/users.tbl`을 손으로 고쳐 빈 줄이나 잘린 줄이 생김 | 엔진이 안 켜짐 | Phase 1(8단계)에서 처리. 그 전엔 파일을 지우고 다시 |

## 5. Phase 1 담당 (4\~9단계)

**약속 (접점 2, 제안)**: DESIGN 2절에 제안으로 적힌 모양이고, 지금 코드는 이 모양으로 동작합니다. 첫 회의에서 이대로 갈지 정합니다. 바뀌면 이 표와 `parser.py`, `engine.py`를 같이 고칩니다. 회의 전에 Phase 1을 시작한다면 일단 이 모양에 맞춰 두면, 바뀌더라도 이름만 고치면 됩니다.

| SQL | 파서가 돌려줄 모양 |
| --- | --- |
| `INSERT INTO users (name, age) VALUES ('현지', 25);` | `Insert(table="users", columns=["name", "age"], values=["현지", 25])` |
| `INSERT INTO users VALUES ('현지', 25);` (열 이름 생략) | `Insert(table="users", columns=None, values=["현지", 25])` |
| `SELECT * FROM users;` | `Select(table="users", columns=["*"], where=None)` |
| `SELECT name FROM users WHERE id = 3;` | `Select(table="users", columns=["name"], where=Where("id", "=", 3))` |

숫자 값은 `int`, 글자 값은 `str`로 넣습니다. 이 클래스들은 지금 `parser.py`에 있습니다.

**내 파서가 위 모양을 돌려주는지 확인**: 엔진을 몰라도 됩니다.
```bash
python3 checks/check_parser.py   # 지금 임시 파서는 6/10. Phase 1(5단계)이 끝나면 10/10
```
Phase 1(4단계)에서 `parse`가 글자 대신 단어 목록을 받기로 정했다면, 이 파일 맨 위의 `to_input()` 한 곳만 고치면 됩니다.

**엔진에서 바꿀 곳**: Phase 1 작업이 엔진에 닿는 곳은 아래뿐입니다. 나머지 엔진 코드는 안 건드려도 됩니다. 코드 설명은 [STEP1 핵심 코드](./STEP1.md#핵심-코드)와 [STEP2 핵심 코드](./STEP2.md#핵심-코드)에 있습니다.

**Phase 1(4–5단계): 문장 나누기와 파서 부르기** · [`engine.py`](../../engine.py)의 `execute`
```python
for stmt in [s.strip() for s in sql.split(";") if s.strip()]:   # ← 4단계: 단어로 자른 뒤 ; 단어에서 나누도록
    try:
        results.append(self._run(parse(stmt)))                  # ← 5단계: parse에 넘기는 값만 맞추면 됨
```
- 지금은 `;` 글자에서 그냥 자릅니다. 따옴표 안의 `;`도 잘라서 `'a;b'`가 깨집니다.
- 엔진이 파서를 부르는 곳은 `parse(stmt)` 한 곳뿐입니다. `parser.py`는 통째로 바꿔도 되고, `Insert(...)`/`Select(...)`만 위 표의 모양대로 돌려주면 됩니다.
- `parse`가 단어 목록을 받기로 정했다면 여기서 `parse(tokens)`처럼 넘기는 값만 바꿉니다.

**Phase 1(6단계): 열 고르기와 타입 검사** · [`engine.py`](../../engine.py)의 `_run`, `_arrange`
```python
# _run: 지금은 SELECT * 만 받도록 막아 둠 → 열 고르기를 만들고 이 두 줄을 지움
if cmd.columns != ["*"]:
    raise ValueError("아직 SELECT * 만 처리합니다")

# _arrange: 열 검사(없는 열, 빠진 열, 중복, id 직접)는 이미 있음 → 값 타입 검사를 추가
by_name = dict(zip(given, cmd.values))
return [by_name[name] for name in names]
```
- 열 고르기를 만들면 `_run` 끝의 `rows`에서 고른 열만 남기고, 결과의 `columns`도 고른 열로 바꿉니다.
- 타입 검사에는 `engine.py` 맨 위의 `TYPES = {"INT": int, "TEXT": str}`를 쓰면 됩니다. WHERE 값 검사가 같은 방식으로 이미 되어 있습니다.

**Phase 1(8단계): 깨진 줄이 있어도 켜지게** · [`storage.py`](../../storage.py)의 `scan`
```python
while True:
    offset = f.tell()
    line = f.readline()
    if not line:
        break
    yield offset, json.loads(line)     # ← 빈 줄이나 [5, "민 처럼 잘린 줄에서 오류가 남
```
- 엔진은 켤 때 `scan`으로 파일 전체를 읽습니다. 쓰다가 꺼져서 마지막 줄이 잘리면 `json.loads`에서 오류가 나 엔진이 안 켜집니다.

**바꾼 뒤에는** `python3 checks/check_all.py`를 돌려서 "지금 통과해야 하는 것"이 11/11 그대로인지 봅니다. 줄어들었으면 내가 바꾼 곳이 기존 동작을 깨뜨린 것입니다.

**단계별 할 일** (완료 기준은 DESIGN 3절 그대로)

| 단계 | DESIGN 완료 기준 | 이미 된 것 | 남은 것 |
| --- | --- | --- | --- |
| 4. 토크나이저 | 글자 값 안에 공백·쉼표·`;`가 있어도 정확히 나뉨 | 일부만. 글자 안의 공백은 됨. 하지만 `;`와 쉼표는 따옴표 안인지 안 보고 잘라서, `'a;b'`, `'김,철수'`는 오류 | 새 `tokenizer.py`. `engine.py`의 `sql.split(";")`를 "단어로 자른 뒤 `;` 단어에서 나누기"로. SQL에서 `'It''s'`는 값 `It's` (작은따옴표 두 개 = 글자 `'` 하나) |
| 5. 파서 | 접점 2의 예시가 그대로 나오고, 문법이 틀린 문장은 오류 | 임시 파서가 위 표의 앞 세 줄만 처리 | 재귀 하강 파서로 교체. 위 표 네 줄 모두 |
| 6. 열 구성 검사 | 없는 테이블·열, 열 수나 타입이 틀린 INSERT가 오류 | 없는 테이블·열, 열 수, 빠진 열, 중복, id 직접 넣기, WHERE 값 타입 | INSERT 값의 타입 검사(숫자 열에 숫자인지). `SELECT 열들`(지금은 오류로 막아 둠) |
| 7. 저장 형식 | 한글이나 쉼표가 든 값도 깨지지 않음 | 한 줄에 JSON 배열, 위치로 한 줄 읽기 | Phase 1(4단계)가 끝나면 쉼표 든 값으로 확인만 |
| 8. 껐다 켜기 | 껐다 켜도 데이터가 남고, 다음 ID가 이어짐 | 켤 때 파일을 읽어 다음 번호와 목차를 다시 만듦 | 빈 줄, 쓰다 꺼져서 `[5, "민`처럼 잘린 마지막 줄이 있어도 켜지게 |
| 9. 오류 처리 | 잘못된 문장이 섞인 파일에서 나머지는 실행되고, 무엇이 틀렸는지 보임 | 틀린 문장은 오류로 담고 다음 문장 계속(CLI). 서버는 첫 오류에서 멈추고 400 + 그때까지의 결과 | 메시지를 더 알아보기 쉽게 |

공부 자료: [학습 노트 1-1 토크나이저, 1-2 파서(재귀 하강)](../study/DBMS_study.md)

## 6. Phase 2 담당 (10\~14단계)

**약속 (접점 3, 제안)**: `insert(key, value)`, `search(key)` 두 함수. `search`는 없으면 `None`. DESIGN 2절에 제안으로 적힌 모양이고, 지금 코드(dict 목차)는 이 모양으로 동작합니다. 첫 회의에서 이대로 갈지 정합니다. 바뀌면 `index.py`(나중엔 `bptree.py`)와 `engine.py`를 같이 고칩니다. 회의 전에 Phase 2를 시작한다면 일단 이 두 함수에 맞춰 두면, 바뀌더라도 이름만 고치면 됩니다.

**B+ 트리가 받는 입력의 특징**
- 키는 항상 숫자(`int`) id이고, **1, 2, 3… 늘어나는 순서로만** 들어옵니다.
- 값은 그 줄이 파일의 몇 바이트째에 있는지(`int`)입니다.
- 같은 키를 다시 넣으면 **덮어쓰기**합니다 (지금 dict와 같은 동작).
- 삭제(DELETE)는 없습니다.
- 엔진을 켤 때 파일 전체를 읽으며 `insert`를 다시 합니다. 100만 건이면 켤 때마다 100만 번입니다.

**내 B+ 트리가 약속을 지키는지 확인**: 엔진에 붙이기 전에 따로 확인할 수 있습니다. 순서대로 넣기, 무작위로 넣기, 덮어쓰기, 없는 키, 값이 0인 경우를 봅니다.
```bash
python3 checks/check_index.py                     # 지금 dict 인덱스: 6/6
python3 checks/check_index.py bptree BPlusTree    # 내 B+ 트리 (파일 이름, 클래스 이름)
```
클래스에 `height()` 함수를 만들어 두면 트리 높이도 같이 출력합니다. Phase 2(11단계)의 완료 기준입니다.

**바꿀 곳**: `engine.py`에서 이 두 줄만 바꾸면 됩니다.
```python
from index import DictIndex            # → from bptree import BPlusTree
self.index[table] = DictIndex()        # → self.index[table] = BPlusTree()
```

**엔진이 인덱스를 부르는 곳** (B+ 트리가 받게 될 호출) · [`engine.py`](../../engine.py)
```python
# __init__ (켤 때): 파일 전체를 읽으며 insert. 100만 건이면 100만 번
for offset, row in self.storage.scan(table):
    self.index[table].insert(row[0], offset)

# _run, INSERT 때: 방금 쓴 줄의 id와 위치
self.index[cmd.table].insert(new_id, offset)

# _run, WHERE id = ? 때: 위치를 꺼내고, None이면 빈 결과
offset = self.index[cmd.table].search(where.value)
rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]
```
- `key`는 항상 숫자(int) id이고, `value`는 그 줄이 파일의 몇 바이트째에서 시작하는지(int)입니다.
- 엔진은 이 세 곳에서만 인덱스를 씁니다. 설명은 [STEP2 핵심 코드](./STEP2.md#핵심-코드)에 있습니다.

**단계별 할 일** (완료 기준은 DESIGN 3절 그대로)

| 단계 | 만드는 것 | 이것이 보이면 완료 |
| --- | --- | --- |
| 10. B+ 트리 찾기 | 노드 모양과 찾기 (엔진과 따로) | 손으로 만든 작은 트리에서 키를 찾음 |
| 11. B+ 트리 넣기 | 넣기와 노드 나누기 | 키 1만 개를 무작위 순서로 넣어도 모두 찾고, 트리 높이가 출력됨 |
| 12. 인덱스 교체 | dict → B+ 트리 (위 두 줄) | `examples/step2.sql` 결과가 지금과 똑같고, `python3 checks/check_all.py`가 11/11 그대로 |
| 13. 100만 건 만들기 | `INSERT` 100만 줄짜리 SQL 파일을 만드는 스크립트 | 만든 파일을 CLI로 실행하면 100만 건이 들어감. **서버는 끈 상태로** (위 "먼저 알아 둘 세 가지" 3번) |
| 14. 성능 비교 | id로 찾기(`WHERE id = ?`)와 다른 열로 찾기(`WHERE name = ?`)의 시간 측정. 시간은 파이썬 `time.perf_counter()`로 잼 (`used_index`는 목차를 썼는지만 알려 줌) | 1만, 10만, 100만 건에서의 비교가 표로 정리됨 |

다른 열 찾기는 이미 조건대로 거르게 고쳐 두어서, Phase 2(14단계) 비교를 바로 할 수 있습니다.

공부 자료: [학습 노트 2. B+ 트리 인덱스](../study/DBMS_study.md), [전체 그림 2절 "인덱스: B+ 트리"](../study/OVERVIEW.md)

## 7. Phase 3 (은기, 15\~17단계)

Phase 3 안에서는 16단계(lock) → 15단계(Thread Pool) → 17단계(오류 응답 JSON) 순서로 합니다. lock 없이 스레드부터 늘리면 그 사이 id가 겹칠 수 있어서, 잠금을 먼저 겁니다.

| 단계 | 상태 | 작업 기록 | 결정 |
| --- | --- | --- | --- |
| Phase 3(16단계) lock | 완료. 스레드 100개 동시 INSERT → id 1\~100 빠짐없이 | [STEP16](./STEP16.md) | [D31\~D33](./DECISIONS.md#step16) |
| Phase 3(15단계) Thread Pool | 완료. 스레드 4개가 동시 요청을 나눠 처리, 큐가 차면 503, 5초 timeout | [STEP15](./STEP15.md) | [D34\~D37, D40, D41](./DECISIONS.md#step15) |
| Phase 3(17단계) API 오류 응답 | 완료. 400·404·405·408·413·500·503 JSON 통일 + 1MB/전체시간 제한 + 부하 테스트 | [STEP17](./STEP17.md) | [D38\~D39, D42\~D46](./DECISIONS.md#step17) |

**Phase 1·2에게**: lock은 `execute` 위에 `@locked` 한 줄로 걸었습니다. `execute` 안을 고쳐도 충돌하지 않습니다. 엔진이 한 번에 하나씩만 실행하므로 B+ 트리는 동시성을 신경 쓰지 않아도 됩니다.

## 8. 지금 코드가 따르는 것 / 바뀔 가능성이 큰 것

| 지금 코드가 이렇게 동작함 (회의에서 확정 전) | 회의에서 바뀔 가능성이 큰 것 |
| --- | --- |
| 접점 1\~3의 모양 (위 표들) | 파일 이름과 나누는 방식 (`executor.py`를 떼어 낼지 등) |
| `schema.json` 모양, 저장 형식(JSON 배열) | API 오류 응답 규칙 |

모두 아직 팀 합의 전입니다. 왼쪽은 지금 코드가 이미 이렇게 되어 있어서, 회의 전에 시작한다면 일단 맞춰 두면 되는 것들입니다.

**DESIGN과 지금 코드가 다른 곳**

| 내용 | DESIGN | 지금 코드 | 이유 |
| --- | --- | --- | --- |
| 지도 만들기(1단계) 임시 파서 | "공백·쉼표로 나누는 수준" | 정규식 | 같은 역할. 정규식이 예제를 더 안정적으로 읽음 |

## 9. 시작 전에 정할 것

| 누가 | 정할 것 | 언제까지 |
| --- | --- | --- |
| Phase 1 | 파서가 SQL 글자를 받을지, 토큰(단어) 목록을 받을지. 토큰은 문자열 리스트인지 (종류, 값) 쌍인지 | Phase 1(4단계) 시작 전 |
| Phase 1 | 닫히지 않은 따옴표(`'abc`)를 만나면 남은 문장을 실행할지 | Phase 1(4단계) |
| Phase 1 | 테이블·열 이름의 대소문자를 가릴지 (지금은 가림. `ID`는 없는 열) | Phase 1(5단계) |
| Phase 1 | 실행기를 `executor.py`로 떼어 낼지, 다음 번호와 목차를 누가 가질지. Phase 1(6단계) 담당이 정하고 DECISIONS에 기록 | Phase 1(6단계) |
| 팀 회의 | 파일 나누기와 접점 1\~4를 이대로 갈지 | 첫 회의 |
| 팀 회의 | DESIGN 4절 "전체" 결정 4줄 (파이썬, 지도부터, 표준 라이브러리만, CLI와 서버가 같은 `execute`) | 첫 회의 |
| 팀 회의 | CLI와 서버를 같이 쓸 때 id 겹침을 규칙으로 둘지 코드로 막을지 | Phase 3(16단계) 전 |
