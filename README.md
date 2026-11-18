# mini-dbms

세 단계(SQL 처리기 → B+ 트리 인덱스 → API 서버)로 만드는 미니 DBMS. 설계와 단계 계획은 [docs/DESIGN.md](docs/DESIGN.md), 단계별 설명은 [docs/steps/](docs/steps/)에 있다.

## 실행

```sh
source .venv/bin/activate
pip install -r requirements-dev.txt     # pytest 만 설치된다
pytest                                  # 전체 테스트

python -m minidb examples/students.sql  # SQL 파일 실행 (데이터는 data/ 에 저장)
python -m minidb q.sql --data-dir /tmp/mydb --schema data/schema.json
```

종료 코드: 0 성공, 1 입력 문제(파일 없음, 문법 오류), 2 실행 문제(카탈로그, 없는 테이블, 타입 불일치). 결과는 표준 출력, 오류는 표준 에러로 나간다.

## B+ 트리 인덱스 (Phase 2)

`WHERE id = 값` 조회는 메모리의 B+ 트리로 행의 파일 위치를 찾아 그 한 줄만 읽는다. 그 외 조건은 전체 스캔이다. 트리는 실행할 때마다 파일에서 다시 만든다. 자세한 내용은 [docs/phase2.md](docs/phase2.md).

```sh
python bench/run_bench.py 10000 100000     # id(인덱스) vs name(전체 스캔) 조회 시간 비교
python bench/run_bench.py                  # 1만, 10만, 100만 건 (100만 건은 약 1분, 메모리 약 1.7GB)
```

## API 서버 (Phase 3)

다른 프로그램이 HTTP로 SQL을 보내면 엔진이 실행해 JSON으로 답한다. 자세한 내용은 [docs/eungi/](docs/eungi/) (STEP15 Thread Pool, STEP16 lock, STEP17 오류 응답).

```sh
python3 server.py                          # http://localhost:8000 (브라우저로 열면 테스트 페이지)
curl -s -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id > 1;"}'
```

```
HTTP → 받는 스레드 → 대기열(16칸, 차면 503) → 일하는 스레드 4개 → 🔒 engine.execute → minidb 실행기 → B+ 트리 / 파일
```

- **Thread Pool:** 요청을 읽고 응답을 쓰는 일은 스레드 4개가 동시에 한다. 느린 연결 3개가 스레드를 붙잡아도 다른 요청은 처리된다. 5초 안에 요청을 다 보내지 않으면 408.
- **lock:** minidb 실행기는 스레드 안전하지 않아서(다음 id, B+ 트리, 파일 append), 엔진 입구(`execute`) 하나를 lock으로 묶어 한 번에 한 요청만 실행한다. 실행기는 서버 전체가 하나를 같이 쓴다.
- **오류:** 모두 `{"error": {"code", "message"}}` 모양. SQL이 틀리면 400 `bad_sql`(앞 문장 결과 포함), 파일 손상 등 서버 문제는 500.

```sh
python3 checks/check_concurrency.py        # lock 끔 → id 중복, lock 켬 → 1~100
python3 checks/check_threadpool.py         # 여러 스레드가 나눠 처리, 대기열이 차면 503
python3 checks/check_errors.py             # 오류 응답 모양 (400·404·405·408·413·500·503)
python3 checks/check_guard.py              # 엣지 방어 (느린 연결, Content-Length, 끄기)
```

## 지원 SQL

```sql
INSERT INTO students (name, grade) VALUES ('Kim', 3);
INSERT INTO students VALUES ('Lee', 2);          -- 컬럼 생략 시 id 를 뺀 스키마 순서
SELECT * FROM students;
SELECT name, grade FROM students WHERE grade >= 2;
SELECT name FROM students WHERE name = 'Kim';
```

- 테이블 정의는 `data/schema.json` 에 미리 적는다 (`CREATE TABLE` 없음). 타입은 `INT`, `TEXT`. 첫 컬럼은 반드시 `id INT` 이며 값은 자동 부여된다.
- 키워드는 대소문자 무관, 식별자는 소문자로 정규화. 문자열은 작은따옴표, 따옴표 자체는 `''`. 문장은 `;` 로 끝나며 주석은 `--`.
- `WHERE` 는 `컬럼 연산자 값` 하나만. 연산자는 `=` `!=` `<` `<=` `>` `>=`. INT 는 숫자 비교, TEXT 는 대소문자를 구분하는 문자열 비교.
- 문법 오류가 하나라도 있으면 아무 문장도 실행하지 않는다. 실행 오류가 나면 그 문장에서 멈추고, 앞 문장은 되돌리지 않는다.

## 한계 (의도된 범위 밖)

같은 데이터 폴더에 대해 한 번에 한 프로세스만 실행한다고 가정한다. CLI 두 개를 동시에 실행하면 같은 id 가 부여될 수 있다. Phase 3 서버는 엔진을 가진 프로세스 하나가 요청을 받고 lock으로 줄 세워 이 문제를 막는다. 다만 서버가 켜진 채로 같은 폴더에 CLI로 쓰는 것은 막지 못한다.

`CREATE TABLE`, `UPDATE`, `DELETE`, NULL, `AND`/`OR`, `ORDER BY`, `LIMIT`, JOIN, 트랜잭션, WAL. 쓰다 만 마지막 행은 다음 실행 때 잘라 낸다. 표 출력에서 한글 등 전각 문자의 폭은 맞추지 않는다.
