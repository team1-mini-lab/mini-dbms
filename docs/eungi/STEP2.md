# 2단계: 임시 인덱스 (목차)

## 이 문서에 나오는 말

| 말 | 뜻 |
| --- | --- |
| 인덱스 (목차) | "id 2는 파일의 18바이트째에 있다"처럼 위치를 적어 둔 표. 이걸 보면 파일을 처음부터 안 읽어도 됨 |
| `dict` | 파이썬의 "키 → 값" 표. 여기서는 `{1: 0, 2: 18}`처럼 "id → 위치" |
| B+ 트리 | 10\~12단계에서 dict 대신 쓸 목차 구조. 데이터가 많아도 빨리 찾음 |
| 선형 탐색 | 파일을 처음부터 끝까지 한 줄씩 읽으며 찾는 것 |
| `None` | 파이썬에서 "없음" |
| `tell()`, `seek(n)` | 파일에서 "지금 몇 바이트째인지" 알려 주는 함수, "n바이트째로 바로 이동"하는 함수 |

## 이 단계에서 한 일

`WHERE id = ?`로 찾을 때, 파일을 처음부터 읽지 않고 **목차(인덱스)에서 위치를 찾아 그 한 줄만** 읽게 만들었습니다. 목차는 일단 파이썬 `dict`로 만들고, 10\~12단계에서 B+ 트리로 바꿉니다.

```
users.tbl                       목차 (dict)
   0바이트  [1, "현지", 25]       {1: 0,
  18바이트  [2, "민수", 31]        2: 18}

SELECT * FROM users WHERE id = 2;
→ 목차에서 2 → 18 → 파일의 18바이트로 바로 가서 그 줄만 읽음
```

id가 아닌 열(`WHERE name = '민수'`)은 목차가 없으므로, **처음부터 읽으면서 조건에 맞는 줄만** 남깁니다.

## 파일들이 서로 하는 일

```
engine.py   INSERT                 → index.insert(id, 위치)
            SELECT ... WHERE id = ? → index.search(id) → storage.read_at(위치)
            SELECT ... WHERE 다른 열 → storage.scan으로 처음부터 읽으며 거름
   │  insert / search              ← 접점 3 (DESIGN 2절)
   ▼
index.py    (임시) 파이썬 dict
```

엔진은 목차가 `dict`인지 모릅니다. `insert`, `search` 두 함수만 부릅니다. 그래서 12단계에서 B+ 트리로 바꿀 때 엔진은 그대로입니다.

## 헷갈리기 쉬운 것

**Q. 목차에는 무엇이 들어 있나요?**
데이터가 아니라 **"id → 파일의 몇 바이트째"**만 들어 있습니다. 1단계 `storage.append`가 돌려준 위치입니다.

**Q. CLI를 새로 켜면 목차가 사라지지 않나요?**
목차는 메모리에만 있어서 끄면 사라집니다. 그래서 1단계에서 다음 번호를 다시 정할 때, 파일을 읽으면서 목차도 같이 다시 만듭니다.

**Q. 이런 SQL은 어떻게 되나요?**

| SQL | 결과 |
| --- | --- |
| `SELECT * FROM users WHERE id = 2;` | 민수 한 줄, `used_index: True` (목차 사용) |
| `SELECT * FROM users WHERE id = 99;` | `rows: []` (없는 id) |
| `SELECT * FROM users WHERE name = '민수';` | 민수인 줄만, `used_index: False` (처음부터 읽음) |
| `SELECT * FROM users WHERE email = 'x';` | 오류: `users 테이블에 없는 열입니다: email` |
| `SELECT * FROM users WHERE id = '2';` | 오류: `id 열은 INT 값과 비교해야 합니다` |
| `SELECT name FROM users;` | 오류: 아직 처리할 수 없는 SQL (열 고르기는 6단계) |

`WHERE id = '2'`(글자)를 오류로 막는 이유: B+ 트리는 "찾는 키가 이 노드의 키보다 작은가?"를 비교하며 내려갑니다. 그런데 파이썬은 `2 < '2'`처럼 숫자와 글자를 비교하면 `TypeError`를 냅니다. 지금 `dict`는 그냥 "없음"을 돌려주니 차이가 안 보이지만, 미리 막아 두면 12단계에서 B+ 트리로 바꿔도 결과가 똑같습니다.

## 이 단계에서 정한 것

| 언제 | 정한 것 | 왜 (안 하면 생기는 일) | 출처 |
| --- | --- | --- | --- |
| 목차를 만들 때 | 일단 파이썬 `dict`로 만들고, 바깥에서는 `insert`(적기), `search`(찾기) 두 함수로만 쓰게 감쌈 | 엔진이 dict를 직접 만지면, 10\~12단계에서 B+ 트리로 바꿀 때 엔진도 고쳐야 함 | DESIGN.md 제안과 같음 |
| 목차에서 못 찾았을 때 | `None`(없음)을 돌려줌 | DESIGN 접점 3과 같게. 결과는 빈 목록 `rows: []` | DESIGN.md 제안과 같음 |
| SELECT에 `WHERE id = ?`가 있을 때 | 목차로 위치를 찾아 그 한 줄만 읽음 | 과제가 "id는 인덱스로 찾기"를 요구함 | DESIGN.md 제안과 같음 |
| SELECT에 다른 열 조건이 있을 때 (`WHERE name = ...`) | 파일을 처음부터 읽으면서 조건에 맞는 줄만 남김 | 과제가 "다른 열은 처음부터 읽기(선형 탐색)"와 속도를 비교하라고 함. 거르지 않으면 틀린 결과가 나옴 | DESIGN.md 제안과 같음 + 교차 검토로 거르기 추가 |
| WHERE의 열과 값을 볼 때 | 그 열이 `schema.json`에 있는지, 값의 종류(숫자/글자)가 맞는지 확인. 틀리면 오류 | 없는 열을 쓰면 전부 돌려주던 문제를 막음. 숫자 id에 글자(`'2'`)로 찾는 것도 막아서, B+ 트리로 바꿨을 때 결과가 달라지지 않게 함 | 교차 검토로 정함 |
| 아직 못 하는 SELECT가 들어왔을 때 | `SELECT name`(열 고르기), `WHERE id > 3`(크기 비교)은 "아직 처리하지 않음" 오류 | 나중에 진짜 파서가 들어와도 엔진이 조용히 틀린 결과를 내지 않게 미리 막음 | 교차 검토로 정함 |
| 엔진을 켤 때 | 데이터 파일을 읽으면서 목차도 다시 만듦 | 목차는 메모리에만 있어서 끄면 사라짐. 파일이 원본이라 다시 만들면 항상 맞음 | DESIGN.md 제안과 같음 |
| 결과를 돌려줄 때 | 목차를 썼으면 `used_index: True`, 처음부터 읽었으면 `False` | 목차를 썼는지 눈으로 확인할 수 있음. 14단계 속도 비교에도 씀 | 새로 정함 |

## 만든 파일

| 파일 | 내용 |
| --- | --- |
| `index.py` (새로) | `DictIndex`: `insert(키, 값)`, `search(키)` |
| `engine.py` (고침) | 테이블마다 목차 하나. INSERT 때 `insert`, `WHERE id`일 때 `search` + `read_at`, 다른 열은 `scan`하며 거름 |

## 완료 확인

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql
python3 cli.py examples/step2.sql
```
```
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[2, '민수', 31]], 'used_index': True}
```

| 확인 | 이렇게 나오면 완료 |
| --- | --- |
| 위 명령 (CLI를 따로 두 번 실행) | 민수 한 줄, `used_index: True`. CLI를 새로 켰는데도 찾았으니 목차가 다시 만들어졌다는 뜻 |
| `SELECT * FROM users WHERE id = 99;` | `rows: []`, `used_index: True` |
| `SELECT * FROM users WHERE name = '민수';` | 민수인 줄만, `used_index: False` |
| `SELECT * FROM users;` | 전체, `used_index: False` |

## 나중에 바꿀 곳

| 지금 (임시) | 언제 | 어떻게 바뀌나 | 안 고쳐도 되는 곳 |
| --- | --- | --- | --- |
| `DictIndex` (dict) | 10\~12단계 | 같은 `insert`/`search`를 가진 B+ 트리로 교체 (`engine.py`에서 `DictIndex`를 부르는 두 줄만 바뀜) | 엔진의 나머지 |
| `SELECT *`만 | 6단계 | `SELECT name, age`처럼 열 고르기 | 목차 |
| 켤 때마다 목차를 다시 만듦 | 24단계 (시간 남으면) | 목차를 파일로 저장 | 엔진의 `search` 부르는 곳 |

**B+ 트리 담당에게**: 엔진은 `search`에 항상 **숫자(int) 키**만 넘깁니다. 같은 키를 다시 `insert`하면 **값을 덮어쓰면** 됩니다 (지금 dict와 같은 동작).

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| 다시 켠 뒤 `WHERE id = 2`가 `rows: []` | 엔진을 켤 때 `scan`하면서 `index.insert(행[0], 위치)`를 하는지 확인 |
| 엉뚱한 줄이 나옴 | `append`가 쓰기 **전**의 `tell()`을 돌려주는지, 파일을 바이너리 모드(`'ab'`, `'rb'`)로 여는지 확인. 글자 모드로 열면 한글 때문에 위치가 어긋날 수 있음 |
