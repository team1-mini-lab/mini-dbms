# 2단계: 임시 인덱스

## 목표

`WHERE id = ?`일 때 파일을 처음부터 읽지 않고, 목차(인덱스)에서 위치를 찾아 그 한 줄만 읽습니다. `WHERE id = 2`에 그 줄 하나만 나오고 `used_index: True`가 보이면 완료입니다.

## 핵심 문제: 목차는 함수 두 개로만

```
engine.py   INSERT → index.insert(id, offset)
            SELECT ... WHERE id = ? → index.search(id) → storage.read_at(offset)
   │  insert / search                      ← 접점 3
   ▼
index.py    (임시) 파이썬 dict
```

- 엔진은 목차가 `dict`인지 모릅니다. `insert`, `search` 두 함수만 부릅니다.
- 그래서 12단계에서 B+ 트리로 바꿀 때 엔진은 그대로입니다.

## 질문과 정리

| 질문 | 정리 |
| --- | --- |
| 목차에 무엇을 담나 | 데이터가 아니라 "ID → 파일 위치(바이트)". 1단계 `storage.append`가 돌려준 위치 |
| 없는 ID를 찾으면 | `search`는 `None`, 결과는 `rows: []` |
| 다른 열(`WHERE name = ...`)이면 | 이 단계에서는 처리하지 않음. 4\~9단계에서 처음부터 읽기로 처리 |
| 다시 켜면 목차는 | 메모리에만 있어서 사라짐. 1단계에서 다음 ID를 다시 정할 때 같이 다시 만듦 |

## 이 단계에서 정한 것

| 관련 코드 | 정한 것 | 이유 |
| --- | --- | --- |
| `index.py` `DictIndex` | 임시 인덱스는 `dict`이고, B+ 트리와 같은 `insert`/`search` 함수로 감쌈 | 12단계에서 클래스만 바꾸면 되도록 (DESIGN.md 제안과 같음) |
| `index.py` `search` | 없으면 `None` | 접점 3 |
| `engine.py` `_run` | `WHERE id = ?`일 때만 인덱스, 나머지는 처음부터 읽기 | 과제의 비교 조건과 같음 (DESIGN.md 제안과 같음) |
| `engine.py` `__init__` | 켤 때 `scan`으로 목차를 다시 만듦 | 인덱스는 메모리에만 둠. 파일이 원본이라 둘이 어긋나지 않음 (DESIGN.md 제안과 같음) |
| `engine.py` 결과 | 인덱스를 썼으면 `used_index: True` | 완료 기준 "인덱스를 썼다고 표시됨". 14단계 속도 비교에서도 씀 |

## 만드는 파일

| 파일 | 내용 |
| --- | --- |
| `index.py` (새로 만듦) | `DictIndex` 클래스. `insert(key, value)`, `search(key)` |
| `engine.py` (고침) | 테이블마다 `DictIndex` 하나. `INSERT` 때 `insert`, `WHERE id = ?`일 때 `search` + `read_at` |

## 완료 테스트

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql
python3 cli.py examples/step2.sql
```

```
{'type': 'select', 'columns': ['id', 'name', 'age'], 'rows': [[2, '민수', 31]], 'used_index': True}
```

| 확인 방법 | 기대 결과 |
| --- | --- |
| 위 명령 (CLI를 따로 두 번 실행) | 민수 한 줄, `used_index: True`. CLI를 새로 켰는데도 찾았으므로, 켤 때 목차가 다시 만들어졌다는 뜻 |
| `SELECT * FROM users WHERE id = 99;` | `rows: []`, `used_index: True` |
| `SELECT * FROM users;` | 전체, `used_index: False` |

## 나중에 바꿔 끼울 곳

| 지금 (임시) | 바뀌는 단계 | 바뀌는 모습 | 안 고쳐도 되는 곳 |
| --- | --- | --- | --- |
| `DictIndex` (dict) | 10\~12단계 | 같은 `insert`/`search`를 가진 B+ 트리 | 엔진. 접점 3이 같음 |
| `WHERE id = ?`만 | 4\~9단계 | 다른 열은 `storage.scan`으로 처음부터 읽기 | 인덱스 |
| 켤 때마다 목차를 다시 만듦 | 24단계 (시간이 남으면) | 목차를 파일로 저장 | 엔진의 `search` 부르는 곳 |

## 문제가 생기면

| 증상 | 해결 |
| --- | --- |
| 다시 켠 뒤 `WHERE id = 2`가 `rows: []` | `__init__`에서 `scan`하며 `index.insert(row[0], offset)`을 하는지 확인 |
| 엉뚱한 줄이 나옴 | `append`가 쓰기 **전**의 `tell()`을 돌려주는지, 파일을 바이너리로 여는지 확인 |
