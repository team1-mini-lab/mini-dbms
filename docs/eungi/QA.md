# 회의록 보충: 실제 코드(`eungi` 브랜치)와 함께 보는 2가지 핵심 정리

> 기준 브랜치: `team1-mini-lab/mini-dbms` (`eungi` 브랜치) · 상위 안내 문서: [HANDOFF](./HANDOFF.md)

---

## 1. 파서(`INSERT`, `SELECT`)가 엔진과 어떻게 연결되는가

파서(`parser.py`)는 `schema.json`이나 파일을 전혀 보지 않고, **SQL 글자를 `Insert`, `Select`라는 정해진 파이썬 상자에 담아 돌려주기만** 합니다.

실제로 `parser.py` **5~23줄**과 **33~44줄**을 보면 파일이나 스키마를 읽는 코드가 전혀 없고, 문자열을 받아 `Insert(...)`나 `Select(...)` 객체만 만들어 `return`합니다.

```python
# parser.py (5~23줄) — 엔진과 약속한 반환 상자 모양
@dataclass
class Where:
    column: str
    op: str
    value: object

@dataclass
class Insert:
    table: str
    columns: list
    values: list

@dataclass
class Select:
    table: str
    columns: list
    where: object
```

```python
# parser.py (33~44줄) — SQL 글자를 위 상자에 담아 돌려줌
def parse(stmt):
    m = re.match(r"INSERT\s+INTO\s+(\w+)\s*(?:\((.*?)\))?\s*VALUES\s*\((.*)\)\s*$", stmt, re.I | re.S)
    if m:
        columns = [c.strip() for c in m.group(2).split(",")] if m.group(2) else None
        values = [_value(v) for v in m.group(3).split(",")]
        return Insert(m.group(1), columns, values)
    m = re.match(r"SELECT\s+\*\s+FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*(\S+))?\s*$", stmt, re.I | re.S)
    if m:
        where = Where(m.group(2), "=", _value(m.group(3))) if m.group(2) else None
        return Select(m.group(1), ["*"], where)
    raise ValueError(f"아직 처리할 수 없는 SQL입니다: {stmt}")
```

이렇게 만든 `parse` 함수를 `engine.py` **5줄**에서 직접 가져와(`from parser import Insert, parse`), `execute` 함수(**30~32줄**)에서 호출합니다.

```python
# engine.py (5줄, 27~37줄)
from parser import Insert, parse
...
    def execute(self, sql, stop_on_error=False):
        results = []
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:   # 30줄: ;(세미콜론) 기준으로 한 문장(stmt)씩 자름
            try:
                results.append(self._run(parse(stmt)))                  # 32줄: parse(stmt) 결과를 바로 _run()에 넘김
            except Exception as e:
                results.append({"type": "error", "message": str(e)})
                if stop_on_error:
                    break
        return results
```

- **30줄**에서 전체 `sql`을 `;` 기준으로 한 문장씩 잘라 `stmt`에 담습니다.
- **32줄** 안쪽 `parse(stmt)`가 SQL 한 문장을 `Insert(...)`나 `Select(...)` 상자로 바꿔주고, 바깥쪽 `self._run(...)`이 그 상자를 받아 실제 DB 작업을 실행합니다.

그다음 `_run(self, cmd)`(**39~72줄**)에서는 넘어온 `cmd` 상자가 `Insert`인지 `Select`인지 보고 아래처럼 분기합니다.

```python
# engine.py (44~50줄, 53~72줄)
        if isinstance(cmd, Insert):
            values = self._arrange(columns, cmd)                         # schema.json 기준 열 검사 & 순서 정렬
            new_id = self.next_id[cmd.table]
            offset = self.storage.append(cmd.table, [new_id] + values)   # 파일 끝에 쓰고 위치(offset) 받음
            self.next_id[cmd.table] += 1
            self.index[cmd.table].insert(new_id, offset)                 # 인덱스에 등록
            return {"type": "insert", "id": new_id}

        # Select일 때
        if cmd.columns != ["*"]:                                         # 53~54줄: 아직 SELECT * 만 허용
            raise ValueError("아직 SELECT * 만 처리합니다")
        ...
        if where and where.column == "id":                               # 66~69줄: id 검색이면 인덱스 사용
            offset = self.index[cmd.table].search(where.value)
            rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]
            return {"type": "select", "columns": columns, "rows": rows, "used_index": True}

        rows = [row for _, row in self.storage.scan(cmd.table) if not where or row[i] == where.value]  # 71~72줄: 그 외엔 처음부터 읽기
        return {"type": "select", "columns": columns, "rows": rows, "used_index": False}
```

- **Phase 1 담당자 작업 범위**: `schema.json`과 비교해 없는 열·빠진 열·중복·`id` 직접 입력을 막는 검사는 이미 `engine.py`의 `_arrange`(**74~91줄**)에 다 구현되어 있습니다.
- 따라서 토크나이저와 파서를 새로 짤 때는 `Insert`·`Select` 상자 모양만 똑같이 맞춰 `python3 checks/check_parser.py`가 `10/10` 통과하게 만든 뒤, `engine.py` **30줄**의 `sql.split(";")` 부분만 토크나이저로 연결하고 **53~54줄**의 `SELECT *` 제한을 풀면 됩니다.

---

## 2. `next_id`, 파일 위치(`offset`), 메모리 인덱스·삭제 동작

먼저 **`id`와 파일 위치(`offset`)는 다른 값**입니다. `id`는 우리가 붙이는 `1, 2, 3` 같은 번호고, `offset`은 그 한 줄이 `users.tbl` 파일의 **몇 바이트째에서 시작하는지** 나타내는 위치 숫자입니다. (`storage.py` **12~23줄**)

```python
# storage.py (12~23줄)
    def append(self, table, row):
        """파일 끝에 한 줄 쓰고, 그 줄이 시작하는 바이트 위치(offset)를 돌려준다."""
        with open(self._path(table), "ab") as f:                     # 14줄: "ab" (끝에 붙이기 + 바이트 모드)
            offset = f.tell()                                        # 15줄: 쓰기 직전 파일 위치 = 이 줄의 offset
            f.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        return offset

    def read_at(self, table, offset):
        """offset 위치의 한 줄만 읽는다."""
        with open(self._path(table), "rb") as f:                     # 21줄: "rb" (바이트 모드 읽기)
            f.seek(offset)                                           # 22줄: 해당 바이트 위치로 바로 점프
            return json.loads(f.readline())
```

- 한글은 1글자가 3바이트라서 `"ab"`, `"rb"` 바이트 모드로 열어 `f.tell()`과 `f.seek(offset)`이 정확히 맞물리게 처리합니다.

그리고 파일(`users.tbl`)에 남는 건 실제 데이터 줄(`1, 2, 3...`)뿐이고, **`next_id`랑 인덱스(`id → offset`)는 파이썬 변수(메모리)에만** 들어 있습니다.
- 파이썬 변수는 **프로그램(CLI/서버)이 꺼지면 싹 날아갑니다.**
- 만약 복구를 안 하면, 다음 날 다시 실행했을 때 `next_id`가 다시 `1`로 돌아가서 **기존 1번과 `id`가 겹치고**, `index`도 `{}`로 비어서 **기존 데이터를 `WHERE id = 2`로 못 찾게** 됩니다.
- 그래서 **`Engine("data")`가 켜지는 순간(`__init__`, `engine.py` 12~25줄)** 디스크에 남은 `users.tbl` 파일을 처음부터 한 번 쭉 읽어서, 비어 있는 `self.index`와 `self.next_id` 변수를 이전 상태로 다시 채워 넣는 것입니다.

```python
# engine.py (12~25줄)
    def __init__(self, data_dir):
        self.storage = Storage(data_dir)
        with open(os.path.join(data_dir, "schema.json"), encoding="utf-8") as f:
            self.schema = json.load(f)
        self.index = {}
        self.next_id = {}
        # CLI는 실행할 때마다 새로 켜지므로, 켤 때 파일을 읽어 목차와 다음 번호를 다시 만든다
        for table in self.schema:
            self.index[table] = DictIndex()                          # 20줄: 방금 켜져서 비어 있는 메모리 인덱스
            last = 0
            for offset, row in self.storage.scan(table):             # 22줄: 디스크 파일을 처음부터 끝까지 읽음
                self.index[table].insert(row[0], offset)             # 23줄: id(row[0]) → offset 다시 채움
                last = max(last, row[0])
            self.next_id[table] = last + 1                           # 25줄: 제일 큰 id + 1 로 다음 번호 복구
```

> **주의**: `cli.py`와 `server.py`를 보면 두 프로그램이 각각 따로 `Engine("data")`를 만들어 자기 메모리에 `next_id`를 들고 있습니다. 그래서 서버를 켜 둔 채로 CLI로 `INSERT`하면 `id`가 겹치므로, 쓰는 작업은 둘 중 하나만 해야 합니다.

```python
# cli.py (6~10줄) — 실행할 때마다 새로 생성 후 종료 시 메모리 해제
def main():
    engine = Engine("data")
    with open(sys.argv[1], encoding="utf-8") as f:
        for result in engine.execute(f.read()):
            print(result)

# server.py의 main() — 서버 켜질 때 1번 생성해서 메모리에 계속 유지 (Phase 3에서 맨 위 → main() 안으로 옮김, D41)
        engine = Engine("data")
```

또 **파일 위치 삭제나 수정이 없는 이유**는, `storage.py` 전체(**1~35줄**)에 `append`, `read_at`, `scan` 3개만 있고 `DELETE`/`UPDATE` 함수가 아예 없기 때문입니다. **14줄**처럼 `"ab"` 모드로 파일 맨 끝에 붙이기만 하므로, 중간 줄이 지워지거나 바뀌지 않아 한 번 쓴 줄의 `offset`이 절대 밀리지 않고 인덱스에서 삭제할 일도 없습니다.

마지막으로 `INSERT`할 때도 **`engine.py` 45~49줄** 순서처럼 **열 검사(`_arrange`)를 맨 먼저 하고 → 파일에 쓰고(`append`) → 그다음에 `next_id`를 1 올리게** 짜여 있어서, 중간에 틀린 SQL이 들어와도 `id` 번호가 1에서 3으로 건너뛰지 않습니다.

```python
# engine.py (44~50줄)
        if isinstance(cmd, Insert):
            values = self._arrange(columns, cmd)                         # 45줄: 검사 먼저! 실패 시 예외 → 아래 실행 안 됨
            new_id = self.next_id[cmd.table]                             # 46줄: 다음 번호 꺼냄
            offset = self.storage.append(cmd.table, [new_id] + values)   # 47줄: 파일에 먼저 씀
            self.next_id[cmd.table] += 1                                 # 48줄: 쓰기 성공 후 번호 올림
            self.index[cmd.table].insert(new_id, offset)                 # 49줄: 인덱스 등록
            return {"type": "insert", "id": new_id}
```


## 3. 같은 `insert` / `search`를 가진 B+ 트리로 교체하는 부분

쉽게 말하면 "나중에 임시 `dict`를 B+ 트리로 갈아끼울 때, `engine.py`를 다 뜯어고치지 않게 미리 사용법만 똑같이 맞춰놨다" 는 뜻입니다.

지금은 인덱스를 파이썬 `dict`로 만들었지만, 곧 **B+ 트리**로 바꿔야 합니다. 만약 `engine.py`에 `dict` 문법을 직접 써놨다면, 나중에 B+ 트리로 바꿀 때 `engine.py` 코드들을 전부 찾아 고쳐야 합니다. 그래서 지금 `index.py`(**1~11줄**)는 일부러 `DictIndex`라는 껍데기 클래스를 만들어서, **무조건 `insert`(넣기)와 `search`(찾기) 두 함수만 쓰게** 해두었습니다.

```python
# index.py (1~11줄)
class DictIndex:
    """2단계 임시 인덱스. 12단계에서 같은 두 함수를 가진 B+ 트리로 바꾼다."""

    def __init__(self):
        self._d = {}

    def insert(self, key, value):   # 넣기: id와 파일 위치(offset) 저장
        self._d[key] = value

    def search(self, key):          # 찾기: id 주면 파일 위치 돌려줌 (없으면 None)
        return self._d.get(key)
```

덕분에 `engine.py`는 인덱스 속이 `dict`인지 B+ 트리인지 알 필요가 없고, 전체 코드 중 **딱 세 군데(23줄, 49줄, 67줄)에서 `.insert(...)`와 `.search(...)`만** 부릅니다.

```python
# engine.py 내 인덱스 사용 3곳 전부
# 1) __init__ (23줄): 켜질 때 파일 읽으면서 넣기
self.index[table].insert(row[0], offset)

# 2) _run - INSERT (49줄): 방금 쓴 줄의 id와 위치 넣기
self.index[cmd.table].insert(new_id, offset)

# 3) _run - SELECT WHERE id = ? (67~68줄): id로 위치 찾기
offset = self.index[cmd.table].search(where.value)
rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]
```

- **68줄**(`if offset is None`): 파일 맨 첫 줄의 위치는 `0`입니다. 그래서 B+ 트리도 못 찾았을 때는 `0`이나 `False`가 아니라 반드시 **`None`**을 돌려줘야 "첫 줄(`0`)"과 "없음(`None`)"을 구별할 수 있습니다.

따라서 B+ 트리 담당자(김소망 님)는 `bptree.py`에 `BPlusTree` 클래스를 만드실 때, 안의 트리 구조는 자유롭게 짜시되 **겉에 보이는 `insert(key, value)`와 `search(key)` 함수 이름·동작만 `index.py`와 똑같이** 맞춰 주시면 됩니다.

엔진에 붙이기 전에 아래 명령어로 혼자 먼저 테스트해 볼 수 있습니다:

```bash
python3 checks/check_index.py bptree BPlusTree
```

- 비었을 때 `None` 나오는지, 1만 개를 순서대로/무작위로 넣어도 다 찾는지, 같은 `id`를 다시 넣으면 덮어쓰는지, 위치 `0`도 잘 찾는지 총 6가지를 자동으로 확인해 줍니다.

테스트를 다 통과하면, 마지막에 `engine.py`에서 `DictIndex`라고 적힌 **딱 두 줄(4줄, 20줄)만** `BPlusTree`로 바꾸면 나머지 코드는 한 줄도 안 고치고 교체가 끝납니다!

```python
# engine.py (4줄, 20줄)
# 변경 전
from index import DictIndex          # 4줄
...
self.index[table] = DictIndex()      # 20줄

# 변경 후
from bptree import BPlusTree         # 4줄
...
self.index[table] = BPlusTree()      # 20줄
```
