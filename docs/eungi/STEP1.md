# 지도 만들기(1단계): CLI (터미널에서 SQL 실행하기)

> **한 줄 요약**: SQL 파일을 터미널에서 실행하면 데이터가 파일에 저장되고, 조회도 되게 만들었습니다. id는 자동으로 붙습니다.

## CLI가 뭔가요?

CLI는 **터미널에 명령을 쳐서 실행하는 방식**입니다. 이 단계가 끝나면 이렇게 쓸 수 있습니다.

```bash
python3 cli.py examples/step1.sql
```

```
{'type': 'insert', 'id': 1}
{'type': 'insert', 'id': 2}
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[1, '현지', 25], [2, '민수', 31]], 'used_index': False}
```

SQL 한 문장마다 결과가 한 줄씩 나옵니다.
- `'type': 'insert', 'id': 1`: 넣었고, id 1이 붙었다는 뜻입니다.
- `'type': 'select'`: 찾은 결과입니다. `rows` 안에 찾은 데이터가 있습니다.
- `used_index`는 지도 만들기(2단계)에서 설명합니다.

## 목표: 엉성해도 끝까지 한 번 돌게

이 단계에서는 완벽하게 만들지 않았습니다. **"SQL을 넣으면 → 저장되고 → 다시 꺼낼 수 있다"가 처음부터 끝까지 한 번 이어지는 것**이 목표였습니다. 엉성한 부분은 Phase 1(4\~9단계) 담당이 제대로 된 것으로 바꿉니다.

## SQL 한 줄이 처리되는 순서

```
examples/step1.sql
      │
      ▼
 cli.py       파일을 읽어서 엔진에 넘기고, 결과를 화면에 출력
      │
      ▼
 engine.py    ① 문장을 ; 로 나눔
              ② 문장 하나씩 파서에 넘김
              ③ 파서가 돌려준 명령을 실행 (검사, id 붙이기, 저장)
      │
      ├──→ parser.py    SQL 글자를 읽어서 "무슨 명령인지" 정리
      └──→ storage.py   파일에 쓰고 읽기
```

### 파서(parser.py)는 무엇을 하나요?

SQL은 사람이 쓴 **글자**입니다. 엔진이 바로 쓰기 어렵기 때문에, 파서가 글자를 읽어서 **정리된 모양**으로 바꿔 줍니다.

```python
# 파서에 들어가는 것 (글자)
"INSERT INTO users (name, age) VALUES ('현지', 25)"

# 파서가 돌려주는 것 (정리된 모양)
Insert(table='users', columns=['name', 'age'], values=['현지', 25])
```

```python
"SELECT * FROM users WHERE id = 2"
→ Select(table='users', columns=['*'], where=Where(column='id', op='=', value=2))
```

엔진은 이 정리된 모양만 보고 일합니다. 그래서 **파서를 다른 방식으로 통째로 바꿔도, 돌려주는 모양만 같으면 엔진은 안 고쳐도 됩니다.** 이 "돌려주는 모양"이 DESIGN 2절의 **접점 2**입니다.

### "임시 파서", "정규식 파서"가 무슨 말인가요?

지금 파서는 **정규식**이라는 파이썬 기능으로 만든 임시 파서입니다.

정규식은 **"이런 모양의 글자를 찾아라"라고 규칙을 적는 기능**입니다. 예를 들어 아래 코드는 "`SELECT * FROM` 다음에 오는 단어"를 꺼냅니다.

```python
import re
m = re.match(r"SELECT \* FROM (\w+)", "SELECT * FROM users")
print(m.group(1))   # users
```

`(\w+)`는 "글자나 숫자가 이어진 부분을 꺼내라"는 뜻입니다.

지금 파서는 이런 규칙 두 개만 가지고 있습니다.
- `INSERT INTO 테이블 (열들) VALUES (값들)` 모양
- `SELECT * FROM 테이블` 모양 (뒤에 `WHERE 열 = 값`이 붙어도 됨)

이 두 모양이 아니면 전부 "아직 처리할 수 없는 SQL" 오류가 납니다. 예제 SQL만 돌리기에는 충분하지만 약점이 많아서 **임시**입니다. Phase 1이 4\~5단계에서 SQL을 단어 단위로 쪼개 읽는 제대로 된 파서로 바꿉니다.

## id는 어떻게 붙나요?

**"지금 파일에 있는 가장 큰 id + 1"**이 다음 id입니다. 빈 파일이면 1부터 시작합니다.

**Q. CLI를 두 번 실행하면 id가 또 1부터 붙지 않나요?**

안 붙습니다. CLI는 실행할 때마다 새로 켜지고, 끝나면 기억이 사라집니다. 그래서 엔진은 **켜질 때마다 데이터 파일을 한 번 읽어서** 가장 큰 id를 확인합니다.

```
1번째 실행: 파일이 비어 있음 → id 1, 2를 붙임
2번째 실행: 파일을 읽어 보니 가장 큰 id가 2 → id 3, 4를 붙임
```

## 데이터는 어떻게 저장되나요?

`data/users.tbl` 파일에 **한 줄에 한 사람씩** 저장합니다. 새 데이터는 항상 파일 맨 끝에 붙습니다.

```
[1, "현지", 25]
[2, "민수", 31]
```

순서는 `schema.json`에 적힌 열 순서(id, name, age)와 같습니다. 직접 열어 보려면 `cat data/users.tbl`을 실행하면 됩니다.

한 줄을 쓸 때 **그 줄이 파일의 몇 번째 바이트에서 시작하는지**도 기억해 둡니다. 위 예에서 1번 줄은 0바이트째, 2번 줄은 18바이트째입니다. 이 숫자는 지도 만들기(2단계)에서 "id 2는 18바이트째에 있다"처럼 바로 찾아갈 때 씁니다. 한글은 한 글자가 3바이트라서, 글자 수가 아니라 바이트 수로 셉니다.

## 열 순서를 바꿔 쓰거나 틀리게 쓰면요?

**순서를 바꿔 써도 됩니다.** 엔진이 `schema.json` 순서에 맞춰 다시 놓습니다. 열 이름을 아예 안 쓰면 `schema.json` 순서대로 넣습니다.

```sql
INSERT INTO users (age, name) VALUES (31, '지영');   -- 저장: [3, "지영", 31]
INSERT INTO users VALUES ('하늘', 22);               -- 저장: [4, "하늘", 22]
```

**틀리게 쓰면 오류가 납니다.**

| SQL | 오류 내용 |
| --- | --- |
| `INSERT INTO users (email) VALUES ('x');` | `users 테이블에 없는 열입니다: email` |
| `INSERT INTO users (name) VALUES ('혼자');` | 빠진 열이 있음 (age). 모든 열을 넣어야 함 |
| `INSERT INTO users (name, name) VALUES ('a', 'b');` | 같은 열이 두 번 있음 |
| `INSERT INTO users (id, name, age) VALUES (9, 'x', 1);` | id는 자동으로 붙으므로 직접 넣을 수 없음 |
| `INSERT INTO users (name, age) VALUES ('a');` | 열 수와 값 수가 다름 |

숫자 열에 글자를 넣는 실수(`age`에 `'스물'`)는 아직 잡지 못합니다. Phase 1(6단계)에서 추가합니다.

## 문장 하나가 틀리면 전부 멈추나요?

아니요. **틀린 문장만 오류로 표시하고 다음 문장은 계속 실행합니다.**

```bash
python3 cli.py examples/step1_error.sql
```
```
{'type': 'insert', 'id': 1}
{'type': 'error', 'message': 'users 테이블에 없는 열입니다: email'}
{'type': 'insert', 'id': 2}
```

틀린 문장이 **번호를 쓰지 않은 것**을 보세요. 세 번째 문장이 3이 아니라 2를 받았습니다. 이렇게 되도록 INSERT를 아래 순서로 처리합니다.

```
① 검사 (열이 맞나?)   ← 여기서 틀리면 바로 멈춤. 번호는 그대로
② 파일에 쓰기
③ 다음 번호를 1 올리기
```

처음에는 번호를 먼저 올리는 실수가 있어서 1, 3처럼 건너뛰었는데, 교차 검토 때 찾아서 고쳤습니다.

## 핵심 코드

위에서 말로 설명한 내용이 실제 코드에서 어디에 어떻게 있는지 정리했습니다. 위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다. 줄 번호는 코드를 고치면 금방 밀리기 때문입니다.

### ① 터미널 입구 · [`cli.py`](../../cli.py)의 `main`

```python
def main():
    engine = Engine("data")                          # 엔진을 만듦
    with open(sys.argv[1], encoding="utf-8") as f:   # 명령에 적은 SQL 파일을 엶
        for result in engine.execute(f.read()):      # 파일 내용 전체를 엔진에 넘김
            print(result)                            # 결과를 한 줄씩 출력
```

- `python3 cli.py examples/step1.sql`이라고 치면 `sys.argv[1]`에 `"examples/step1.sql"`이 들어갑니다.
- `Engine("data")`의 `"data"`는 폴더가 아니라 **폴더 이름(글자)**입니다. 엔진은 이 글자로 `data/schema.json`, `data/users.tbl` 같은 경로를 만듭니다.
- CLI는 실행할 때마다 엔진을 새로 만들고, 끝나면 사라집니다. 그래서 엔진은 켜질 때마다 파일을 읽어 다음 번호를 다시 정해야 합니다 (③).

### ② 엔진의 입구 · [`engine.py`](../../engine.py)의 `execute`

```python
def execute(self, sql, stop_on_error=False):
    results = []
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:   # ;로 문장을 나눔 (임시)
        try:
            results.append(self._run(parse(stmt)))     # 파서로 모양을 바꿔서 실행
        except Exception as e:
            results.append({"type": "error", "message": str(e)})   # 틀리면 오류로 담고
            if stop_on_error:                          # 서버가 부를 때만 여기서 멈춤
                break
    return results
```

- CLI와 서버가 부르는 **유일한 입구**입니다. SQL 글자 전체를 받아서 문장마다 결과 하나씩 담은 목록을 돌려줍니다.
- `sql.split(";")`는 `;`가 나올 때마다 그냥 자릅니다. 따옴표 안인지 보지 않아서 `'a;b'`도 잘라 버립니다. Phase 1(4단계)에서 토크나이저로 바꿉니다.
- 파서를 부르는 곳은 `parse(stmt)` **한 곳뿐**입니다. 그래서 파서를 통째로 바꿔도 이 줄만 맞추면 됩니다.
- 문장 하나에서 오류가 나면 `except`로 잡아서 그 자리에 오류를 담고, `for`는 다음 문장으로 계속 갑니다. CLI는 이렇게 씁니다.
- 🔄 `stop_on_error=True`로 부르면 첫 오류에서 `break`로 멈춥니다. 서버가 이렇게 씁니다 ([STEP3](./STEP3.md#잘못-보내면-어떻게-되나요), D30). 기본값이 `False`라서 `execute(sql)`처럼 부르는 기존 코드는 그대로 동작합니다.

### ③ id 자동 부여 (켤 때) · [`engine.py`](../../engine.py)의 `__init__`

```python
def __init__(self, data_dir):
    self.storage = Storage(data_dir)
    with open(os.path.join(data_dir, "schema.json"), encoding="utf-8") as f:
        self.schema = json.load(f)                     # {"users": [["id","INT"], ...]}
    self.index = {}
    self.next_id = {}
    for table in self.schema:
        self.index[table] = DictIndex()                # (지도 만들기 2단계에서 추가)
        last = 0
        for offset, row in self.storage.scan(table):   # 파일을 처음부터 한 줄씩 읽으며
            self.index[table].insert(row[0], offset)   # (지도 만들기 2단계에서 추가)
            last = max(last, row[0])                   # 첫 칸(id) 중 가장 큰 값을 기억
        self.next_id[table] = last + 1                 # 다음 번호 = 가장 큰 id + 1
```

- `json.load`가 `schema.json`을 파이썬 dict로 바꿉니다. 엔진은 이 dict에서 테이블 이름과 열 목록을 꺼내 씁니다.
- `row[0]`은 줄의 첫 값, 곧 id입니다. 그래서 **첫 열은 항상 id**여야 합니다.
- 파일이 비어 있으면 `last`는 0이고, 다음 번호는 1이 됩니다.
- `next_id`를 테이블마다 따로 두어서, 테이블이 늘어도 번호가 섞이지 않습니다.

### ④ INSERT 처리 순서 · [`engine.py`](../../engine.py)의 `_run` 앞부분

```python
def _run(self, cmd):
    if cmd.table not in self.schema:
        raise ValueError(f"{cmd.table} 테이블이 없습니다")
    columns = [name for name, _ in self.schema[cmd.table]]   # ['id', 'name', 'age']

    if isinstance(cmd, Insert):
        values = self._arrange(columns, cmd)           # ① 검사 + schema 순서로 정렬
        new_id = self.next_id[cmd.table]               # ② 다음 번호를 꺼냄
        offset = self.storage.append(cmd.table, [new_id] + values)   # ③ 파일에 쓰고 위치를 받음
        self.next_id[cmd.table] += 1                   # ④ 번호를 올림
        self.index[cmd.table].insert(new_id, offset)   # ⑤ 인덱스에 적음 (지도 만들기 2단계)
        return {"type": "insert", "id": new_id}
```

- `cmd`는 파서가 돌려준 `Insert(...)`입니다. `cmd.table`, `cmd.columns`, `cmd.values`처럼 칸을 꺼내 씁니다.
- **검사(①)를 맨 앞에 둔 이유**: ①에서 실패하면 `raise`로 바로 빠져나가서 ②–⑤가 실행되지 않습니다. 그래서 틀린 INSERT는 번호를 쓰지 않습니다.

```
정상 INSERT ('지영', 28)   : ① 통과 → ② 3 꺼냄 → ③ [3, "지영", 28] 씀 → ④ 4로 올림 → ⑤ 3 → 위치
틀린 INSERT (email)        : ① 오류 → 빠져나감. 다음 번호는 그대로 3
처음 코드 (번호를 먼저 올림): 3 → 4로 올림 → 검사 오류 → 3번은 아무도 안 썼는데 다음은 4 (건너뜀)
```

- 번호를 파일에 쓴 **뒤에** 올리는 것도 같은 이유입니다. 파일 쓰기가 실패하면 번호가 올라가지 않습니다.

### ⑤ INSERT 검사와 정렬 · [`engine.py`](../../engine.py)의 `_arrange`

```python
def _arrange(self, columns, cmd):
    names = columns[1:]                       # ['name', 'age'] (id는 엔진이 붙이므로 뺌)
    given = cmd.columns or names              # 사람이 쓴 열. 안 썼으면(None) schema 순서
    if len(given) != len(cmd.values):
        raise ValueError("열 수와 값 수가 다릅니다")
    if columns[0] in given:
        raise ValueError(f"{columns[0]}는 자동으로 붙으므로 직접 넣을 수 없습니다")
    if len(set(given)) != len(given):         # set은 중복을 없앰. 길이가 줄면 중복이 있었다는 뜻
        raise ValueError("같은 열이 두 번 있습니다")
    unknown = set(given) - set(names)         # 쓴 열 중 schema에 없는 것
    if unknown:
        raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {', '.join(sorted(unknown))}")
    missing = set(names) - set(given)         # schema 열 중 안 쓴 것
    if missing:
        raise ValueError(f"빠진 열이 있습니다: {', '.join(sorted(missing))}")
    by_name = dict(zip(given, cmd.values))    # 열 이름 → 값 표
    return [by_name[name] for name in names]  # schema 순서로 꺼냄
```

- 위에서부터 다섯 가지를 검사합니다: 열 수와 값 수, id 직접 넣기, 같은 열 두 번, 없는 열, 빠진 열.
- 마지막 두 줄이 **순서를 바로잡는** 부분입니다.

```
INSERT INTO users (age, name) VALUES (28, '지영');

given      = ["age", "name"]               사람이 쓴 열 순서
cmd.values = [28, "지영"]                   사람이 쓴 값 순서
zip        → ("age", 28), ("name", "지영")  같은 자리끼리 짝짓기
dict       → {"age": 28, "name": "지영"}    열 이름으로 꺼낼 수 있는 표
names 순서 → ["지영", 28]                   schema 순서(name, age)로 꺼냄
파일       → [3, "지영", 28]                ④에서 엔진이 id를 앞에 붙임
```

이 과정이 없으면 `[3, 28, "지영"]`처럼 이름 자리에 나이가 저장됩니다.

### ⑥ SQL 글자 → 정해진 모양 · [`parser.py`](../../parser.py)

**모양 정의** (접점 2)

```python
@dataclass
class Where:
    column: str      # 어느 열     "id"
    op: str          # 비교 방법   "="
    value: object    # 비교할 값   2

@dataclass
class Insert:
    table: str       # "users"
    columns: list    # ["name", "age"]. 열 이름을 안 쓰면 None
    values: list     # ["현지", 25]

@dataclass
class Select:
    table: str       # "users"
    columns: list    # ["*"]
    where: object    # Where(...) 또는 None
```

- `Insert`, `Select`, `Where`는 SQL 명령어가 아니라 **우리가 만든 파이썬 클래스**입니다. SQL 한 줄을 칸별로 나눠 담는 상자입니다.
- `@dataclass`는 칸 이름만 적으면 `Insert("users", [...], [...])`처럼 바로 만들 수 있게 해 주는 파이썬 기능입니다.

**값 하나 바꾸기** `_value`

```python
def _value(text):
    text = text.strip()            # " '현지'" → "'현지'" (앞뒤 공백 제거)
    if text.startswith("'"):
        return text.strip("'")     # 따옴표로 시작하면 글자: "현지"
    return int(text)               # 아니면 숫자: "25" → 25
```

**임시 파서** `parse`

```python
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

정규식(`re.match`)은 "이런 모양의 글자에서 괄호 친 부분을 꺼내라"는 규칙입니다. INSERT 규칙을 조각별로 보면 이렇습니다.

| 정규식 조각 | 뜻 | `INSERT INTO users (name, age) VALUES ('현지', 25)`에서 꺼낸 것 |
| --- | --- | --- |
| `\s+` | 공백 한 개 이상 | |
| `(\w+)` | 영문·숫자 단어 → `group(1)` | `users` |
| `(?:\((.*?)\))?` | 괄호 안 → `group(2)`. 끝의 `?`는 "없어도 됨" | `name, age` |
| `VALUES\s*\((.*)\)` | VALUES 뒤 괄호 안 → `group(3)` | `'현지', 25` |
| `re.I` | 대소문자 무시 | `insert`라고 써도 됨 |

꺼낸 조각을 쉼표로 나누고(`split(",")`), 값은 `_value`로 숫자나 글자로 바꿔서 `Insert(...)`에 담습니다.

```
"INSERT INTO users (name, age) VALUES ('현지', 25)" → Insert(table='users', columns=['name', 'age'], values=['현지', 25])
"INSERT INTO users VALUES ('현지', 25)"             → Insert(table='users', columns=None, values=['현지', 25])
"SELECT * FROM users"                               → Select(table='users', columns=['*'], where=None)
"SELECT * FROM users WHERE id = 2"                  → Select(table='users', columns=['*'], where=Where('id', '=', 2))
```

- 정규식을 쓴 이유는 **임시**이기 때문입니다. 예제 SQL 두 모양만 읽으면 되고, 설치 없이 가장 짧게 만들 수 있습니다.
- 값을 쉼표로 그냥 나눠서 `'김,철수'`는 `'김`과 `철수'`로 잘립니다. 이런 약점 때문에 Phase 1(4–5단계)에서 통째로 바꿉니다.

### ⑦ 파일에 쓰기와 읽기 · [`storage.py`](../../storage.py)의 `append`, `scan`

```python
def _path(self, table):
    return os.path.join(self.data_dir, f"{table}.tbl")     # "users" → "data/users.tbl"

def append(self, table, row):
    with open(self._path(table), "ab") as f:               # a = 끝에 덧붙이기, b = 바이트 모드
        offset = f.tell()                                  # 쓰기 직전 파일 크기 = 새 줄의 시작 위치
        f.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    return offset

def scan(self, table):
    if not os.path.exists(self._path(table)):              # 파일이 아직 없으면 (처음 실행)
        return                                             #   아무것도 안 돌려줌
    with open(self._path(table), "rb") as f:
        while True:
            offset = f.tell()                              # 이 줄의 시작 위치
            line = f.readline()                            # 한 줄 읽기
            if not line:                                   # 끝이면 멈춤
                break
            yield offset, json.loads(line)                 # (위치, 줄)을 하나씩 돌려줌
```

- `json.dumps(row)`는 파이썬 목록 `[1, "현지", 25]`를 글자 `'[1, "현지", 25]'`로 바꿉니다. 뒤에 `"\n"`을 붙여서 한 줄에 한 건이 됩니다.
- `ensure_ascii=False`는 한글을 `현`처럼 바꾸지 않고 그대로 저장하라는 뜻입니다. `cat data/users.tbl`로 열었을 때 사람이 읽을 수 있습니다.
- `"ab"`로 열면 쓰는 위치가 항상 파일 맨 끝입니다. 그래서 쓰기 직전의 `f.tell()`(지금 파일 크기)이 곧 새 줄의 시작 위치입니다. 이 숫자를 지도 만들기(2단계)의 인덱스가 씁니다.
- 바이트 모드(`b`)를 쓰는 이유: 한글은 한 글자가 3바이트라서 글자 수와 바이트 수가 다릅니다. 위치를 바이트로 정확히 세려면 바이트 모드로 열어야 합니다.

```
[1, "현지", 25]\n   ← 0바이트째 시작  (이 줄 길이 18바이트. 현지 = 2글자 × 3바이트)
[2, "민수", 31]\n   ← 18바이트째 시작

append → 0, 18을 돌려줌
scan   → (0, [1, '현지', 25]), (18, [2, '민수', 31])
```

- `yield`는 결과를 한꺼번에 만들지 않고 한 줄씩 넘겨 주는 파이썬 기능입니다. 100만 줄이어도 메모리를 한꺼번에 쓰지 않습니다.

## 이 단계에서 정한 것

자세한 이유는 [결정 기록의 지도 만들기(1단계) 절](./DECISIONS.md#step1)에 있습니다.

- **D6** 파서는 지금은 임시입니다. 예제의 두 가지 모양만 읽습니다.
- **D7** 파서는 `Insert(...)`, `Select(...)`라는 정해진 모양으로 넘깁니다 (접점 2).
- **D8** 문장은 지금은 `;`가 나올 때마다 자릅니다 (임시).
- **D9** 문장 하나가 틀려도 다음 문장은 계속 실행합니다.
- **D10** 켜질 때 파일을 읽어서 "가장 큰 id + 1"을 다음 번호로 정합니다.
- **D11** 다음 번호는 테이블마다 따로 셉니다.
- **D12** INSERT는 검사 → 쓰기 → 번호 올리기 순서입니다.
- **D13** 열 순서를 `schema.json`에 맞춰 다시 놓고, 잘못된 열은 오류로 막습니다.
- **D14** 파일에는 한 줄에 `[1, "현지", 25]` 모양으로 저장합니다.
- **D15** 각 줄이 몇 바이트째에서 시작하는지 기억합니다.

## 만든 파일

| 파일 | 하는 일 |
| --- | --- |
| `cli.py` | SQL 파일을 읽어서 엔진에 넘기고, 결과를 한 줄씩 출력 |
| `engine.py` | 문장 나누기, 파서 부르기, 검사, id 붙이기, 저장 |
| `parser.py` | (임시) SQL 글자 → `Insert` / `Select` |
| `storage.py` | 파일 끝에 한 줄 쓰기(`append`), 처음부터 끝까지 읽기(`scan`), 정해진 위치의 한 줄 읽기(`read_at`, 지도 만들기(2단계)에서 씀) |

## 직접 확인해 보기

```bash
rm -f data/users.tbl                 # 데이터 파일을 지우고 처음부터
python3 cli.py examples/step1.sql
```

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| 위 명령 | id 1, 2가 붙고, SELECT에 두 사람이 나옴 |
| `cat data/users.tbl` | `[1, "현지", 25]`, `[2, "민수", 31]` 두 줄 |
| `python3 cli.py examples/step1.sql`을 한 번 더 | id가 3, 4로 이어지고, SELECT에 네 줄 |
| `rm -f data/users.tbl` 후 `python3 cli.py examples/step1_error.sql` | id 1 → 오류 → id 2 (번호가 안 건너뜀) |

## 아직 엉성한 곳 (나중에 바뀜)

| 지금 | 문제 | 언제 고치나 |
| --- | --- | --- |
| 정규식 임시 파서 | 정해진 두 모양 말고는 못 읽음 | Phase 1(4\~5단계) |
| `;`가 나오면 그냥 자름 | `VALUES ('메모;메모', 7)`처럼 글자 안에 `;`가 있어도 잘라 버림 | Phase 1(4단계) |
| 값 안의 쉼표 | `'김,철수'`처럼 글자 안에 쉼표가 있으면 오류 | Phase 1(4단계) |
| 따옴표가 안 닫힌 SQL | `'abc`처럼 써도 그냥 받아들임 | Phase 1(4단계) |
| 타입 검사 없음 | 숫자 열에 글자를 넣어도 저장됨 | Phase 1(6단계) |
| 파일 끝이 깨졌을 때 | 쓰다가 꺼져서 마지막 줄이 `[5, "민`처럼 잘리면 엔진이 안 켜짐 | Phase 1(8단계) |

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| 두 번째 실행에서 id가 다시 1부터 | 엔진이 켜질 때 파일을 읽어 다음 번호를 정하는지 확인 (`engine.py`의 `__init__`) |
| `cat data/users.tbl`에서 한글이 `현`처럼 보임 | 저장할 때 `json.dumps(..., ensure_ascii=False)`인지 확인 |
| `schema.json`을 못 찾는다는 오류 | 저장소 맨 위 폴더(`mini-dbms`)에서 실행했는지 확인 |
