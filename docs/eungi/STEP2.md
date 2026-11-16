# 지도 만들기(2단계): 임시 인덱스

> **한 줄 요약**: `WHERE id = 2`로 찾을 때 파일을 처음부터 다 읽지 않고, 그 한 줄로 바로 가서 읽게 만들었습니다.

## 왜 필요한가

지도 만들기(1단계)까지는 무엇을 찾든 **파일을 처음부터 끝까지 한 줄씩** 읽었습니다. 데이터가 100만 줄이면 id 999,999번을 찾으려고 거의 100만 줄을 읽어야 합니다.

과제 요구사항은 이것입니다.
- **id로 찾을 때는 인덱스를 써서 빨리 찾기**
- **다른 열로 찾을 때는 처음부터 읽기**
- 그리고 둘의 속도를 비교하기: Phase 2(14단계)

## 인덱스가 뭔가요?

인덱스는 **"id → 그 줄이 파일의 몇 바이트째에 있는지"를 적어 둔 표**입니다.

지도 만들기(1단계)에서 한 줄을 쓸 때마다 시작 위치(바이트)를 기억해 두었습니다. 그 숫자를 모아 둔 것이 인덱스입니다.

```
data/users.tbl                      인덱스
 0바이트째   [1, "현지", 25]          id 1 → 0
18바이트째   [2, "민수", 31]          id 2 → 18
```

`SELECT * FROM users WHERE id = 2;`가 오면 이렇게 처리합니다.

```
1. 인덱스에서 id 2를 찾음 → 18
2. 파일의 18바이트째로 바로 감
3. 그 한 줄만 읽음 → [2, "민수", 31]
```

## 왜 "임시" 인덱스인가요?

지금 인덱스는 **파이썬 `dict`**로 만들었습니다. `dict`는 파이썬에 기본으로 있는 "키 → 값" 표입니다.

```python
{1: 0, 2: 18}    # id 1은 0바이트째, id 2는 18바이트째
```

과제는 **B+ 트리**로 인덱스를 만들라고 합니다. B+ 트리는 Phase 2 담당이 10\~12단계에서 직접 만듭니다. 그 전까지 끝까지 돌아가게 하려고 `dict`를 임시로 쓴 것입니다.

## 나중에 B+ 트리로 어떻게 바꾸나요?

엔진이 `dict`를 직접 만지지 않게 하고, **함수 두 개로만 쓰게** 감쌌습니다.

```python
class DictIndex:
    def insert(self, key, value):   # 적기: id와 위치를 저장
        ...
    def search(self, key):          # 찾기: id로 위치를 꺼냄. 없으면 None
        ...
```

엔진은 이 두 함수만 부릅니다.

```python
self.index["users"].insert(2, 18)       # INSERT할 때
offset = self.index["users"].search(2)  # WHERE id = 2 일 때 → 18
```

그래서 B+ 트리도 `insert`와 `search` 두 함수를 똑같이 만들면, 엔진은 **인덱스를 만드는 줄만 바꾸면** 됩니다. 이 두 함수의 약속이 DESIGN 2절의 **접점 3**입니다.

지금 코드 기준으로 B+ 트리가 지켜야 할 것:
- 키는 항상 숫자(int)입니다.
- 못 찾으면 `None`을 돌려줍니다.
- 같은 키를 다시 `insert`하면 값을 덮어씁니다.

## 엔진을 껐다 켜면 인덱스는요?

인덱스는 **메모리에만** 있어서 끄면 사라집니다. 그래서 지도 만들기(1단계)에서 "켜질 때 파일을 읽어 다음 번호를 정한다"고 했던 그때, **인덱스도 같이 다시 만듭니다.**

```
엔진이 켜질 때:
  파일을 처음부터 읽으면서
    [1, "현지", 25] (0바이트째) → 인덱스에 1 → 0
    [2, "민수", 31] (18바이트째) → 인덱스에 2 → 18
  가장 큰 id = 2 → 다음 번호 = 3
```

데이터 파일이 원본이고 인덱스는 거기서 다시 만드는 것이라, 둘이 어긋날 일이 없습니다.

## id가 아닌 열로 찾으면요?

`WHERE name = '민수'`처럼 id가 아닌 열에는 인덱스가 없습니다. 그래서 **파일을 처음부터 읽으면서 조건에 맞는 줄만** 남깁니다.

처음 만들었을 때는 이 "거르기"가 빠져서 전부 돌려주는 실수가 있었습니다. 교차 검토 때 찾아서 고쳤습니다.

## 인덱스를 썼는지 어떻게 아나요?

SELECT 결과 끝에 `used_index`를 붙였습니다.

| 값 | 뜻 |
| --- | --- |
| `used_index: True` | 인덱스로 그 한 줄만 읽었음 |
| `used_index: False` | 파일을 처음부터 읽었음 |

눈으로 확인하는 용도이고, Phase 2(14단계)에서 두 방법의 속도를 비교할 때도 씁니다.

## 이런 SQL은 어떻게 되나요?

`step1.sql`로 현지(id 1), 민수(id 2)를 넣은 상태라고 가정합니다.

| SQL | 결과 |
| --- | --- |
| `SELECT * FROM users WHERE id = 2;` | 민수 한 줄, `used_index: True` |
| `SELECT * FROM users WHERE id = 99;` | 빈 결과 `rows: []`, `used_index: True` |
| `SELECT * FROM users WHERE name = '민수';` | 민수 한 줄, `used_index: False` |
| `SELECT * FROM users;` | 전체, `used_index: False` |
| `SELECT * FROM users WHERE email = 'x';` | 오류: 없는 열 |
| `SELECT * FROM users WHERE id = '2';` | 오류: id는 숫자와 비교해야 함 |
| `SELECT name FROM users;` | 오류: 아직 처리할 수 없음. 열 고르기는 Phase 1(6단계) |

**`WHERE id = '2'`를 왜 막나요?** `'2'`는 숫자가 아니라 글자입니다. 지금 `dict`는 그냥 "없음"을 돌려주지만, B+ 트리는 "찾는 값이 이 값보다 작은가?"를 비교하며 내려갑니다. 파이썬은 숫자와 글자를 크기 비교하면 오류를 냅니다. 미리 막아 두면 B+ 트리로 바꿔도 결과가 같습니다.

## 핵심 코드

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다.

### ① 인덱스 · [`index.py`](../../index.py)의 `DictIndex`

```python
class DictIndex:
    def __init__(self):
        self._d = {}                   # 빈 dict

    def insert(self, key, value):
        self._d[key] = value           # insert(2, 18) → {2: 18}. 같은 키면 덮어씀

    def search(self, key):
        return self._d.get(key)        # search(2) → 18. 없는 키면 None
```

- `insert`, `search`는 우리가 만든 함수입니다. 엔진은 `self._d`(dict)를 직접 만지지 않고 이 두 함수만 부릅니다. 이 약속이 **접점 3**입니다.
- `dict.get(key)`는 키가 없으면 오류 대신 `None`을 돌려줍니다. 엔진은 `None`을 보고 "없는 id"라고 판단합니다.
- Phase 2(10–12단계)에서 같은 두 함수를 가진 B+ 트리로 바꿉니다. 엔진은 아래 두 줄만 바꾸면 됩니다.

```python
from index import DictIndex          # engine.py 맨 위  → from bptree import BPlusTree
self.index[table] = DictIndex()      # engine.py __init__ → self.index[table] = BPlusTree()
```

### ② 엔진이 인덱스를 부르는 세 곳 · [`engine.py`](../../engine.py)

```python
# __init__ (켤 때): 파일을 읽으며 인덱스를 다시 만듦
for offset, row in self.storage.scan(table):
    self.index[table].insert(row[0], offset)       # id → 위치

# _run, INSERT 할 때: 방금 쓴 줄을 적음
offset = self.storage.append(cmd.table, [new_id] + values)
self.index[cmd.table].insert(new_id, offset)

# _run, SELECT ... WHERE id = ? 할 때: 위치를 꺼냄
offset = self.index[cmd.table].search(where.value)
```

- 인덱스는 **메모리에만** 있습니다. 파일(`users.tbl`)에는 `[1, "현지", 25]` 같은 데이터만 있고, 위치 숫자(0, 18)는 저장되지 않습니다.
- 그래서 켤 때마다 `scan`으로 파일을 처음부터 읽으면서 위치를 다시 재고, 인덱스를 다시 만듭니다. 꺼져 있는 동안 파일은 바뀌지 않으므로, 다시 재도 같은 숫자가 나옵니다.
- B+ 트리 입장에서는 엔진이 켜질 때 `insert`를 파일 줄 수만큼 연달아 받습니다. 100만 건이면 100만 번입니다.

```
users.tbl (파일, 끄면 남음)         self.index (메모리, 끄면 사라짐)
[1, "현지", 25]   ← 0바이트째        {1: 0,
[2, "민수", 31]   ← 18바이트째        2: 18}
                                   ↑ 켤 때 파일을 읽으며 다시 만듦
```

### ③ SELECT 검사 · [`engine.py`](../../engine.py)의 `_run` 중간

```python
if cmd.columns != ["*"]:                              # SELECT name 같은 것 (아직 못 함)
    raise ValueError("아직 SELECT * 만 처리합니다")
where = cmd.where
if where:
    if where.op != "=":                               # WHERE id > 3 같은 것 (아직 못 함)
        raise ValueError("아직 = 조건만 처리합니다")
    if where.column not in columns:                   # WHERE email = ... (schema에 없는 열)
        raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {where.column}")
    i = columns.index(where.column)                   # 그 열이 몇 번째 칸인지 (name → 1)
    expected = TYPES[self.schema[cmd.table][i][1]]    # 그 열의 타입 ("TEXT" → str)
    if not isinstance(where.value, expected):         # WHERE id = '2' (타입이 다름)
        raise ValueError(f"{where.column} 열은 {self.schema[cmd.table][i][1]} 값과 비교해야 합니다")
```

- **위 두 검사 = 아직 못 하는 것.** 지원하는 것(`SELECT *`, `=`)을 정해 두고, 그 밖은 전부 오류로 막습니다. 지금 임시 파서는 `SELECT name`을 애초에 못 읽지만, Phase 1의 새 파서가 `columns=["name"]`을 넘기게 되면 이 줄이 없을 때 엔진이 조용히 전체 열을 돌려줍니다. 그래서 미리 막아 두었습니다. 열 고르기를 만드는 Phase 1(6단계)에서 첫 검사를 지웁니다.
- **아래 두 검사 = WHERE 검사** (교차 검토로 추가). "WHERE에 쓴 열"은 `WHERE name = '민수'`의 `name`입니다. 이 열이 `schema.json`에 있는지, 값 타입이 열과 맞는지 확인합니다.
  - 처음에는 이 검사가 없어서, `WHERE email = 'x'`처럼 없는 열로 찾으면 오류 없이 테이블 전체를 돌려줬습니다.
  - `WHERE id = '2'`(글자)를 막는 이유: B+ 트리는 값을 크기로 비교하며 내려가는데, 파이썬은 숫자와 글자를 크기 비교하면 오류를 냅니다. 미리 막아 두면 B+ 트리로 바꿔도 결과가 같습니다.

### ④ SELECT 두 갈래 · [`engine.py`](../../engine.py)의 `_run` 끝부분

```python
if where and where.column == "id":                        # id로 찾으면
    offset = self.index[cmd.table].search(where.value)    #   인덱스에서 위치를 꺼내고
    rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]   # 그 줄만 읽음
    return {"type": "select", "columns": columns, "rows": rows, "used_index": True}

rows = [row for _, row in self.storage.scan(cmd.table)    # 아니면 처음부터 읽으며
        if not where or row[i] == where.value]            #   조건이 없거나 맞는 줄만 남김
return {"type": "select", "columns": columns, "rows": rows, "used_index": False}
```

- 위쪽이 **인덱스로 찾기**, 아래쪽이 **처음부터 읽기**입니다. Phase 2(14단계)에서 이 두 갈래의 시간을 비교합니다.
- `row[i] == where.value`: `i`는 ③에서 구한 열 번호입니다. `name`이면 `i = 1`이라서 각 줄의 `row[1]`(이름)을 비교합니다.
- `used_index`는 어느 갈래로 갔는지 결과에 표시합니다.

### ⑤ 위치로 한 줄 읽기 · [`storage.py`](../../storage.py)의 `read_at`

```python
def read_at(self, table, offset):
    with open(self._path(table), "rb") as f:   # data/users.tbl을 바이트 모드로 엶
        f.seek(offset)                         # offset 바이트째로 바로 건너뜀
        return json.loads(f.readline())        # 그 한 줄만 읽고, 글자 → 파이썬 목록
```

- 테이블로 이동하는 함수가 아니라, **그 테이블의 파일을 열고 그 바이트 위치로 건너뛰어 한 줄만 읽는** 함수입니다.
- `read_at("users", 18)` → 18바이트째로 건너뜀 → `'[2, "민수", 31]'` 한 줄 → `[2, '민수', 31]`

## 이 단계에서 정한 것

자세한 이유는 [DECISIONS](./DECISIONS.md)의 해당 번호에 있습니다.

- **D16** 인덱스는 `dict`로 만들고, `insert`와 `search` 두 함수로만 씁니다 (접점 3).
- **D17** 못 찾으면 `None`을 돌려주고, SELECT 결과는 빈 목록입니다.
- **D18** `WHERE id = 숫자`일 때만 인덱스를 씁니다.
- **D19** 다른 열은 처음부터 읽으면서 조건에 맞는 줄만 남깁니다.
- **D20** WHERE의 열이 있는지, 값의 종류가 맞는지 확인합니다.
- **D21** 아직 못 하는 SELECT는 오류로 막습니다.
- **D22** 엔진이 켜질 때 인덱스를 다시 만듭니다.
- **D23** 결과에 `used_index`를 붙입니다.

## 만든 파일

| 파일 | 하는 일 |
| --- | --- |
| `index.py` (새로 만듦) | `DictIndex`: `insert(키, 값)`, `search(키)` |
| `engine.py` (고침) | INSERT 때 인덱스에 적기. `WHERE id`면 인덱스로 찾아 그 줄만 읽기. 다른 열이면 처음부터 읽으며 거르기 |

## 직접 확인해 보기

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql
python3 cli.py examples/step2.sql
```
```
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[2, '민수', 31]], 'used_index': True}
```

CLI를 두 번 따로 실행했는데도 두 번째 실행에서 인덱스로 찾았습니다. 켜질 때 인덱스를 다시 만들었다는 뜻입니다.

## 아직 엉성한 곳 (나중에 바뀜)

| 지금 | 언제 | 어떻게 |
| --- | --- | --- |
| `dict` 인덱스 | Phase 2(10\~12단계) | 같은 `insert` / `search`를 가진 B+ 트리로 교체 |
| `SELECT *`만 됨 | Phase 1(6단계) | `SELECT name, age`처럼 열 고르기 |
| 켤 때마다 인덱스를 다시 만듦 | 시간이 남으면 (차별화) | 인덱스를 파일로 저장 |

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| 다시 켠 뒤 `WHERE id = 2`가 빈 결과 | 엔진이 켜질 때 파일을 읽으면서 `index.insert(id, 위치)`를 하는지 확인 |
| 엉뚱한 줄이 나옴 | 파일을 바이너리 모드(`'ab'`, `'rb'`)로 여는지 확인. 글자 모드로 열면 한글 때문에 위치가 어긋날 수 있음 |
