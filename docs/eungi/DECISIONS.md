# 개인 결정 기록 (은기)

각 단계에서 정한 것을 모읍니다. 각 단계 문서(STEPn.md)의 "이 단계에서 정한 것"과 같은 내용입니다. DESIGN.md의 결정 참고사항은 제안이므로, 따르기로 한 것도 여기에 적고 이유 칸에 "(DESIGN.md 제안과 같음)"을 붙입니다. 이 기록을 팀 회의에 가져가 팀 합의가 필요한 것만 논의한 뒤 DESIGN.md에 옮깁니다.

- 단계 번호는 DESIGN.md 3번의 개발 단계와 같습니다.
- 결정을 바꿀 때는 그 줄을 고치고, 이유 칸에 "(변경: 이전에는 ...)"을 덧붙입니다.

| 단계 | 관련 코드 | 정한 것 | 이유 |
| --- | --- | --- | --- |
| 0 | 프로젝트 전체 | 파이썬 표준 라이브러리만 사용. 가상환경과 `requirements.txt`는 두지 않음 | 설치 없이 바로 실행됨. 파서, 인덱스, 서버를 직접 만들어 설명할 수 있음 (DESIGN.md 제안과 같음) |
| 0 | `data/schema.json` | 테이블의 열 구성은 `schema.json`에 미리 적어 둠. 타입은 `INT`, `TEXT` 두 가지 | `CREATE TABLE`이 없으므로 열과 타입을 알 곳이 필요 (DESIGN.md 제안과 같음) |
| 0 | `data/schema.json` | 모든 테이블의 첫 열은 `id INT` | 자동 ID와 인덱스의 기준 (DESIGN.md 제안과 같음) |
| 0 | `data/` | `schema.json`과 테이블 파일(`users.tbl`)을 `data/` 폴더 하나에 둠 | 엔진은 폴더 하나만 받으면 됨 (`Engine("data")`, 접점 1) |
| 0 | `examples/` | 단계마다 확인용 SQL 파일을 하나씩 둠 (`step1.sql`, `step2.sql`) | 완료 테스트를 같은 명령으로 반복할 수 있음 |
| 1 | `parser.py` `parse` | 임시 파서는 정규식으로 `INSERT INTO t [(열들)] VALUES (값들)`, `SELECT * FROM t [WHERE 열 = 값]`만 처리 | 지도 단계는 끝까지 도는 것이 우선 (DESIGN.md 제안과 같음) |
| 1 | `parser.py` `Where`, `Insert`, `Select` | 명령 구조는 `dataclass` | 접점 2 모양을 그대로 코드로 옮김. `stmt.table`처럼 이름으로 꺼냄 |
| 1 | `parser.py` `parse` | 열 이름을 생략하면 `columns=None` | DESIGN.md 접점 2에 맞춤 |
| 1 | `engine.py` `execute` | 문장 구분은 임시로 `sql.split(";")` | 4단계에서 토큰으로 자른 뒤 나누도록 바꿈 |
| 1 | `engine.py` `execute` | 실패한 문장은 결과에 `{"type": "error", "message": ...}`로 담고 계속 실행 | 접점 1 모양. 9단계 오류 처리의 최소한 |
| 1 | `engine.py` `__init__` | 엔진을 만들 때 테이블 파일을 읽어 다음 ID를 다시 정함 | CLI는 매번 새로 켜짐. 다음 ID = 가장 큰 ID + 1 (DESIGN.md 제안과 같음) |
| 1 | `engine.py` `next_id` | 다음 ID는 테이블마다 따로 셈 | 테이블이 둘 이상이면 번호가 섞이지 않게 |
| 1 | `engine.py` `_arrange` | 값을 `schema.json` 열 순서에 맞춰 배치. 없는 열이면 오류 | 열 순서를 바꿔 적어도 똑같이 저장됨 |
| 1 | `storage.py` `append` | 파일은 바이너리 추가 모드(`"ab"`)로 열고, 쓰기 전 `tell()`로 위치를 돌려줌 | 한글은 한 글자가 3바이트라 글자 수와 바이트 수가 다름. 2단계 인덱스가 이 위치를 씀 |
| 1 | `storage.py` `append` | 한 줄에 JSON 배열 하나 (`ensure_ascii=False`) | 쉼표·한글이 든 값도 안전하고 파일을 열어 읽을 수 있음 (DESIGN.md 제안과 같음) |
| 2 | `index.py` `DictIndex` | 임시 인덱스는 `dict`이고, B+ 트리와 같은 `insert`/`search` 함수로 감쌈 | 12단계에서 클래스만 바꾸면 되도록 (DESIGN.md 제안과 같음) |
| 2 | `index.py` `search` | 없으면 `None` | 접점 3 |
| 2 | `engine.py` `_run` | `WHERE id = ?`일 때만 인덱스, 나머지는 처음부터 읽기 | 과제의 비교 조건과 같음 (DESIGN.md 제안과 같음) |
| 2 | `engine.py` `__init__` | 켤 때 `scan`으로 목차를 다시 만듦 | 인덱스는 메모리에만 둠. 파일이 원본이라 둘이 어긋나지 않음 (DESIGN.md 제안과 같음) |
| 2 | `engine.py` 결과 | 인덱스를 썼으면 `used_index: True` | 완료 기준 "인덱스를 썼다고 표시됨". 14단계 속도 비교에서도 씀 |
| 3 | `server.py` | HTTP 서버는 표준 `http.server`. 주소는 `POST /query` 하나 | SQL 자체에 동작이 담겨 있음 (DESIGN.md 제안과 같음) |
| 3 | `server.py` 맨 아래 | 서버 포트는 8000 | macOS에서 5000번은 AirPlay와 겹칠 수 있음. mini-redis와 같은 포트 |
| 3 | `server.py` `engine = Engine("data")` | 엔진은 서버가 켜질 때 하나만 만듦 | 모든 요청이 같은 다음 ID와 목차를 봐야 함 |
| 3 | `server.py` 응답 | `{"results": engine.execute(sql)}`, 한글은 그대로 (`ensure_ascii=False`) | 접점 4. `curl`에서 바로 읽힘 |
| 3 | `server.py` `do_POST` | `/query`가 아닌 주소는 일단 `send_error(404)` | JSON 오류 응답은 17단계 |
