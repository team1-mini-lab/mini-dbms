# 0단계: 프로젝트 골격

## 목표

처리기가 "students 테이블이 무엇인지"를 알 수 있게 하고, 잘못된 요청을 "어떤 종류의 오류"로 돌려줄지 정한다.

이 단계가 끝나면 코드에서 `catalog.table("students")`로 컬럼 순서와 타입을 조회할 수 있고, 없는 테이블이나 컬럼을 물으면 `TableNotFoundError`, `ColumnNotFoundError`가 난다. SQL은 아직 한 글자도 처리하지 못한다. 대신 1단계부터 4단계까지가 기댈 발판이 생긴다.

## 이 단계의 위치

Phase 1이 끝나면 다음과 같은 SQL 파일을 CLI로 넘겼을 때, 실제로 파일에 행이 저장되고 조건에 맞는 행이 출력되어야 한다.

```sql
-- queries.sql
INSERT INTO students (name, grade) VALUES ('Kim', 3);
INSERT INTO students (name, grade) VALUES ('Lee', 2);
SELECT * FROM students WHERE id = 1;
```

```
$ python -m minidb queries.sql
1 row inserted (id=1)
1 row inserted (id=2)
id | name | grade
---+------+------
1  | Kim  | 3
```

이 일이 일어나려면 SQL 문장 하나가 여섯 단계를 거친다. 괄호는 그 일을 맡는 구현 단계다.

| 순서 | 하는 일 | 예시 `SELECT * FROM students WHERE id = 1;` 에서 |
| --- | --- | --- |
| 1 | CLI가 파일에서 문장을 꺼낸다 (5단계) | 세 번째 문장을 꺼낸다 |
| 2 | 토크나이저가 문자열을 토큰으로 자른다 (1단계) | `SELECT` `*` `FROM` `students` `WHERE` `id` `=` `1` `;` |
| 3 | 파서가 토큰 열을 구조화된 객체로 만든다 (2단계) | "SELECT 문, 전체 컬럼, 테이블 students, 조건 id = 1" |
| 4 | 실행기가 무엇을 할지 정하고 저장소에 시킨다 (4단계) | students가 있는지, id가 INT인지 확인하고 전체 행을 순회해 id가 1인 것만 고른다 |
| 5 | 저장소가 파일을 읽고 쓴다 (3단계) | `data/students.tbl`을 한 줄씩 읽어 행으로 돌려준다 |
| 6 | CLI가 결과를 화면에 찍는다 (5단계) | 위의 표 출력 |

**0단계는 이 여섯 순서 중 어디에도 없다.** 대신 4번이 돌아가기 위한 전제 두 가지를 만든다.

- 4번에서 실행기는 "students 테이블이 있는가", "id 컬럼은 INT인가", "`*`는 어떤 컬럼들인가"를 알아야 한다. 이 정보가 **카탈로그**다.
- 4번에서 테이블이 없거나 타입이 안 맞으면 실행기는 멈추지 않고 "무엇이 잘못됐는지"를 돌려줘야 한다. 그 형식이 **오류 타입**이다.

이 둘은 특정 단계의 부품이 아니라 모든 단계가 공유하는 전제라서, 가장 먼저 만든다.

## 1. 카탈로그: "students가 뭔지"를 어디서 아는가

### 왜 필요한가

저장소가 쓰는 테이블 파일은 이런 모습이다.

```
1	Kim	3
2	Lee	2
```

이 줄만 보면 알 수 없는 것들이 있다.

- 세 번째 값 `3`은 숫자인가, 문자열 "3"인가. `WHERE grade = 3`에서 숫자로 비교해야 하는지 문자열로 비교해야 하는지가 달라진다.
- 두 번째 값이 `name` 컬럼인가. `SELECT name FROM students`가 몇 번째 값을 꺼내야 하는지 알아야 한다.
- `INSERT INTO students (name, grade) VALUES ('Kim', 3)`에서 `grade`라는 컬럼이 존재하기는 하는가. 오타라면 파일에 쓰기 전에 거절해야 한다.
- `INSERT INTO students VALUES ('Kim', 3)`처럼 컬럼을 생략했을 때 값 두 개를 어느 컬럼에 넣어야 하는가.

즉 "students 테이블은 id INT, name TEXT, grade INT 세 컬럼이고 이 순서다"라는 정보가 파일 바깥 어딘가에 있어야 한다. 이것을 모아 둔 것이 **카탈로그**(스키마)다. 실제 DBMS는 CREATE TABLE 문을 받았을 때 이 정보를 자기 내부에 기록한다.

### 과제에서는 사람이 직접 적는다

과제는 CREATE TABLE을 구현하지 않아도 된다고 했다. 그렇다면 CREATE TABLE이 남겼을 결과물을 사람이 미리 적어 두면 된다. 그 파일이 `data/schema.json`이고, 처리기는 이 파일을 **읽기만** 한다. "테이블은 이미 존재한다고 가정"이라는 조건을 코드로 옮긴 것이 이 파일이다.

```json
{
  "students": {
    "columns": [
      {"name": "id",    "type": "INT"},
      {"name": "name",  "type": "TEXT"},
      {"name": "grade", "type": "INT"}
    ]
  }
}
```

### 읽을 때 검증하는 이유

사람이 편집하는 파일이라 실수가 들어온다. 잘못된 정의를 그대로 믿고 4번 실행기까지 가면 엉뚱한 곳에서 터진다. 그래서 읽는 시점에 규칙을 검사하고, 어기면 `SchemaError`를 낸다.

| 규칙 | 어기면 뒤에서 무슨 일이 생기나 |
| --- | --- |
| 첫 컬럼은 반드시 `id INT` | id는 처리기가 자동 부여하고 Phase 2 인덱스 키가 된다. 없으면 INSERT가 어디에 id를 넣을지 모른다 |
| 타입은 `INT` 또는 `TEXT` | 그 외 타입은 비교 규칙도 직렬화 규칙도 정해 두지 않았다 |
| 컬럼명 중복 금지 | `SELECT name`이 어느 값을 꺼낼지 모호해진다 |
| 테이블당 컬럼 2개 이상 | id만 있으면 INSERT로 넣을 값이 없다 |
| 테이블명과 컬럼명은 소문자 식별자 | SQL 방언이 식별자를 소문자로 정규화하므로, 카탈로그에 대문자가 있으면 영원히 매칭되지 않는다 |

### 코드 구조 (`minidb/catalog.py`)

- `Column(name, type)`: 컬럼 하나.
- `Table(name, columns)`: 테이블 하나. 실행기가 자주 묻는 것들을 메서드로 둔다.
  - `column(name)`: 이 이름의 컬럼이 있는가, 타입은 무엇인가. 없으면 `ColumnNotFoundError`.
  - `column_index(name)`: 행 안에서 몇 번째 값인가. `SELECT name`이 값을 꺼낼 때 쓴다.
  - `user_columns`: id를 뺀 컬럼 목록. 컬럼을 생략한 INSERT의 값들을 여기에 순서대로 맞춘다.
- `Catalog(tables)`: `table(name)`으로 테이블을 찾는다. 없으면 `TableNotFoundError`.
- `Catalog.load(path)`: JSON 파일을 읽고 위 규칙을 검증한다.

카탈로그는 테이블 파일의 경로도 저장 포맷도 모른다. "어떤 테이블에 어떤 컬럼이 어떤 순서로 있는가"만 안다.

## 2. 오류 타입: "잘못됐다"를 어떻게 돌려주는가

### 왜 필요한가

앞의 예시에서 `SELECT * FROM teachers;`가 들어오면 어떻게 해야 하는가. 프로그램이 죽으면 안 되고, 다음 문장은 계속 실행되어야 하며, 사용자에게는 "teachers 테이블이 없다"고 알려야 한다.

여기에 Phase 3을 미리 생각하면 요구가 하나 더 생긴다. 같은 오류를 CLI는 화면에 문장으로 찍고, 서버는 HTTP 응답 코드와 JSON으로 돌려줘야 한다. 그러려면 오류를 "메시지 문자열"이 아니라 **종류를 구분할 수 있는 객체**로 돌려줘야 한다.

### 계층

```
MiniDBError                 # 사용자 입력 때문에 생긴 모든 오류의 부모
├── ParseError              # SQL 문법이 틀림 (1, 2단계)
├── SchemaError             # 카탈로그가 잘못됐거나 없는 것을 참조함 (0단계)
│   ├── TableNotFoundError
│   └── ColumnNotFoundError
├── TypeMismatchError       # 값과 컬럼 타입이 안 맞음 (4단계)
└── StorageError            # 파일 읽기/쓰기 문제 (3단계)
```

CLI와 서버는 `MiniDBError` 하나만 잡는다. 그 아래 종류를 보고 메시지나 응답 코드를 정한다.

이 구분에는 또 하나의 쓸모가 있다. `MiniDBError`가 아닌 예외(예: Python의 `KeyError`)가 밖으로 새어 나오면 그것은 사용자 입력 문제가 아니라 **우리 코드의 버그**다. 테스트에서 "사용자 실수는 MiniDBError로 돌아오고, 그 외 예외는 절대 나오지 않는다"를 확인할 수 있다.

## 3. 테스트 환경

- `pytest`만 개발 의존성으로 둔다 (`requirements-dev.txt`).
- `pytest.ini`로 테스트 디렉터리를 `tests/`로 고정한다.
- `tests/conftest.py`에 students 카탈로그 픽스처를 둔다. 이후 모든 단계의 테스트가 같은 테이블을 쓴다.

## 산출물

```
minidb/
├── __init__.py
├── errors.py      # 오류 타입 계층
└── catalog.py     # schema.json 읽기와 검증
data/
└── schema.json    # students 테이블 정의
tests/
├── conftest.py    # 공용 픽스처
└── test_catalog.py
pytest.ini
requirements-dev.txt
```

## 완료 기준

```sh
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

- `data/schema.json`이 로딩되고 students 테이블의 컬럼 순서와 타입이 코드에서 조회된다.
- 위 검증 규칙을 어긴 스키마는 모두 `SchemaError`로 거절된다.
- 없는 테이블과 컬럼 조회는 각각 `TableNotFoundError`, `ColumnNotFoundError`다.

## 다음 단계

1단계 토크나이저. 위 표의 2번, 즉 SQL 문자열을 토큰 열로 자르는 부분을 만든다.
