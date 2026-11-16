# 인수인계: 지도 만들기(0\~3단계)

**누가**: 은기 · **브랜치**: `eungi` · **다음 담당**: Phase 1(SQL 처리기 4\~9단계), Phase 2(B+ 트리 10\~14단계)

처음 보는 분은 이 문서 하나만 읽고 시작하면 됩니다. 자세한 건 단계별 문서([STEP0](./STEP0.md) · [STEP1](./STEP1.md) · [STEP2](./STEP2.md) · [STEP3](./STEP3.md))와 [결정 기록](./DECISIONS.md)에 있습니다.

## 1. 지금 어디까지 됐나

엉성하지만 **SQL 넣기 → 파일에 저장 → id로 찾기 → 서버로 요청**까지 처음부터 끝까지 동작합니다.

| 단계 | 된 것 |
| --- | --- |
| 0. 준비 | `data/schema.json`(테이블 모양), `examples/`(확인용 SQL) |
| 1. CLI | 터미널에서 SQL 파일 실행. `INSERT`하면 id가 1, 2, 3… 자동으로 붙고, 다시 켜도 이어짐 |
| 2. 임시 인덱스 | `WHERE id = ?`는 dict 목차로 그 한 줄만 읽음. 다른 열은 처음부터 읽으며 거름 |
| 3. API 서버 | `POST /query`로 SQL을 받아 CLI와 같은 결과를 JSON으로 돌려줌 (스레드 하나) |

두 검토자(설계 쪽, 구현 쪽)가 서로 따로 코드를 돌려 보고 교차 검토했고, 둘 다 "지금 고칠 것"으로 꼽은 문제는 고친 상태입니다.

## 2. 3분 안에 돌려 보기

저장소 맨 위 폴더(`mini-dbms`)에서 실행합니다. 설치할 것은 없습니다 (파이썬 3.8 이상).

```bash
rm -f data/users.tbl
python3 cli.py examples/step1.sql      # id 1, 2가 붙고 전체 두 줄
python3 cli.py examples/step2.sql      # 민수 한 줄, used_index: True
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
```

| 파일 | 하는 일 | 다른 파일과의 약속 (DESIGN 2절 접점) |
| --- | --- | --- |
| `cli.py` | SQL 파일을 읽어 엔진에 넘기고 출력 | `engine.execute(sql)` |
| `server.py` | HTTP로 받은 SQL을 엔진에 넘기고 JSON으로 응답 | 접점 4: `POST /query` `{"sql": "..."}` |
| `engine.py` | 문장 나누기, 파서 부르기, 실행(검사, id 붙이기, 목차/파일 사용) | 접점 1: 결과는 `{"type": "insert" / "select" / "error", ...}` |
| `parser.py` | SQL 문장 → `Insert` / `Select` / `Where` | 접점 2: 이 모양 그대로 |
| `storage.py` | `append` (끝에 쓰고 위치 반환), `read_at` (위치로 한 줄), `scan` (처음부터) | 엔진만 씀 |
| `index.py` | `insert(id, 위치)`, `search(id)` → 위치 또는 `None` | 접점 3 |

파일 이름과 나누는 방식은 아직 **제안**입니다. 회의에서 바뀌면 이름만 고치면 됩니다.

## 4. ⚠️ 알고 써야 할 것

| 상황 | 무슨 일 | 어떻게 |
| --- | --- | --- |
| 서버를 켜 둔 채로 CLI로 `INSERT` | id가 겹침 (서버가 다음 번호를 따로 기억하고 있어서) | **쓰는 건 둘 중 하나만.** 서버가 켜져 있으면 INSERT는 서버로. CLI로 넣었으면 서버를 다시 켜기 |
| 글자 값 안에 `;`, `,` (예: `'김,철수'`, `'a;b'`) | 임시 파서가 잘못 자름. `;` 뒤가 따로 실행될 수도 있음 | 4단계 진짜 토크나이저에서 해결. 그 전엔 쓰지 않기 |
| `SELECT name FROM ...` (열 고르기), `WHERE id > 3` | 오류: 아직 처리 안 함 | 6단계(열 고르기), 20단계(범위 검색) |
| 숫자 열에 글자 넣기 (`age`에 `'abc'`) | 그냥 저장됨 | 6단계 타입 검사 |
| `data/users.tbl`을 손으로 고쳐서 빈 줄이나 깨진 줄이 생김 | 엔진이 안 켜짐 | 8단계에서 처리. 그 전엔 파일을 지우고 다시 |

## 5. 다음 담당자가 바꿀 곳

| 담당 | 단계 | 바꿀 파일 | 지켜야 할 것 |
| --- | --- | --- | --- |
| Phase 1 | 4. 토크나이저 | 새 `tokenizer.py`, `engine.py`의 문장 나누기 | 지금 `sql.split(";")` → "단어로 자른 뒤 `;`로 나누기". 글자 값 안의 `;`, `,`, `''`(따옴표 안의 따옴표) |
| Phase 1 | 5. 파서 | `parser.py` | 돌려주는 모양은 접점 2 그대로 (`Insert`, `Select`, `Where`). 그러면 실행 부분은 안 고쳐도 됨 |
| Phase 1 | 6. 열 구성 검사 | `engine.py` (또는 새 `executor.py`) | 타입 검사 추가. `SELECT 열들` 구현 (지금은 오류로 막아 둠) |
| Phase 1 | 7\~9 | `storage.py`, `engine.py` | 저장 형식은 이미 JSON 배열. 8단계: 빈 줄/깨진 줄 처리 |
| Phase 2 | 10\~12. B+ 트리 | 새 `bptree.py`, `engine.py`에서 `DictIndex`를 부르는 두 줄만 | `insert(id, 위치)`, `search(id)` → 없으면 `None`. **키는 항상 숫자**, 같은 키를 다시 넣으면 **덮어쓰기** |
| Phase 2 | 13\~14 | 새 스크립트 | 100만 건은 CLI로 넣기 (**서버는 끈 상태로**). 다른 열 검색은 이미 거르기가 돼 있어서 바로 비교 가능 |
| Phase 3 (은기) | 16 → 15 → 17 | `engine.py`(lock), `server.py` | lock을 먼저 걸고 Thread Pool. 서버 응답은 `_send` 하나로 |

## 6. 회의에서 정할 것

1. 파일 나누기와 접점 1\~4를 이대로 갈지 (DESIGN 2절)
2. DESIGN 4절의 "전체" 결정 4줄 (파이썬, 지도부터, 표준 라이브러리만, CLI와 서버가 같은 `execute`)
3. 위 4번의 "쓰는 건 하나만" 규칙으로 갈지
4. API에서 SQL 오류를 400으로 할지 200 + 결과 안 `error`로 할지 (9단계 전까지)

나머지 정할 거리는 [결정 기록](./DECISIONS.md) 맨 아래 "팀이 정해야 할 것"에 있습니다.
