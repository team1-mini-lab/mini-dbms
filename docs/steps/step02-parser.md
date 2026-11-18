# 2단계: 파서

## 목표

토큰 열을 읽어 "이것은 어떤 문장이고, 테이블은 무엇이며, 컬럼과 값과 조건은 무엇인가"를 담은 구조화된 객체(AST)로 바꾼다.

이 단계가 끝나면 `parse("SELECT name FROM students WHERE id = 1;")`가 `Select(table="students", columns=("name",), where=Condition("id", "=", 1))`을 돌려준다. SQL 파일 전체를 넘기면 문장 객체의 리스트가 나오고, 문법이 틀린 문장이 하나라도 있으면 위치가 붙은 `ParseError`가 난다. `students`가 실제로 있는 테이블인지, `id`가 INT인지는 아직 모른다. 그것은 카탈로그를 아는 4단계 실행기의 일이다.

## 이 단계의 위치

0단계 문서의 여섯 순서 중 **3번**이다.

| 순서 | 하는 일 |
| --- | --- |
| 1 | CLI가 파일에서 문장을 꺼낸다 (5단계) |
| 2 | 토크나이저가 문자열을 토큰으로 자른다 (1단계) |
| **3** | **파서가 토큰 열을 구조화된 객체로 만든다 (2단계)** |
| 4 | 실행기가 무엇을 할지 정하고 저장소에 시킨다 (4단계) |
| 5 | 저장소가 파일을 읽고 쓴다 (3단계) |
| 6 | CLI가 결과를 화면에 찍는다 (5단계) |

입력은 1단계의 토큰 리스트, 출력은 문장 객체의 리스트다. 1단계의 `tokenize`는 파서 안에서 호출하므로, 바깥에서는 SQL 문자열을 바로 `parse`에 넘긴다.

## 1. 왜 토큰 열을 그대로 실행하면 안 되는가

토큰 열은 여전히 "순서대로 나열된 조각"일 뿐이다. 실행기가 이것을 직접 받으면 다음을 전부 실행기가 해야 한다.

- 첫 토큰이 `SELECT`인지 `INSERT`인지 보고 분기한다.
- `FROM` 뒤의 토큰이 테이블 이름이라는 것을 안다.
- `WHERE`가 있는지 없는지 보고, 있으면 그 뒤 세 토큰이 조건이라는 것을 안다.
- `SELECT name, grade FROM`에서 쉼표를 건너뛰며 컬럼 이름만 모은다.
- 괄호가 짝이 맞는지, 세미콜론이 있는지 확인한다.

이것은 "SQL 문법 지식"이고, 실행기가 할 일인 "저장소에 무엇을 시킬까"와 전혀 다른 일이다. 둘을 한 코드에 두면 문법을 바꿀 때 실행 로직이 깨지고, 실행 로직을 바꿀 때 문법 처리가 깨진다.

파서는 문법 지식을 혼자 떠안고, 그 결과를 **실행기가 필요한 질문에 바로 답할 수 있는 모양**으로 넘긴다. 실행기는 `stmt.table`, `stmt.where.column`처럼 이름으로 꺼내 쓸 뿐 토큰이 어떤 순서로 왔는지 모른다.

## 2. 문법

DESIGN.md의 SQL 방언을 규칙으로 적으면 다음과 같다. 대괄호는 생략 가능, 별표는 0회 이상 반복이다.

```
program    := statement* EOF
statement  := ( insert | select ) ';'

insert     := INSERT INTO identifier [ '(' id_list ')' ] VALUES '(' literal_list ')'
select     := SELECT ( '*' | id_list ) FROM identifier [ WHERE condition ]

condition  := identifier operator literal
id_list    := identifier ( ',' identifier )*
literal_list := literal ( ',' literal )*
literal    := NUMBER | STRING
operator   := '=' | '!=' | '<' | '<=' | '>' | '>='
```

규칙에서 바로 보이는 제약들이다.

- 세미콜론은 필수다. 마지막 문장도 예외가 아니다.
- `INSERT`의 값은 리터럴(숫자, 문자열)만 가능하다. `VALUES (id + 1)` 같은 식은 없다.
- `WHERE`의 오른쪽도 리터럴만 가능하다. `WHERE id = grade`처럼 컬럼끼리 비교하지 않는다.
- `SELECT *, name`처럼 별표와 컬럼을 섞을 수 없다.

## 3. AST: 파서의 출력

AST(추상 구문 트리)는 "문장의 의미만 남기고 표기는 버린" 구조다. 공백, 세미콜론, 괄호, 쉼표는 사라지고 의미 있는 값만 남는다.

```python
Condition(column="id", op="=", value=1)

Insert(table="students", columns=("name", "grade"), values=("Kim", 3))
Insert(table="students", columns=None, values=("Kim", 3))     # 컬럼 생략

Select(table="students", columns=("name",), where=Condition(...))
Select(table="students", columns=None, where=None)             # SELECT *
```

### 결정: `*`와 컬럼 생략은 `None`으로 둔다

`SELECT *`는 "모든 컬럼"이고, 컬럼을 생략한 INSERT는 "id를 뺀 스키마 순서"다. 둘 다 실제 컬럼 이름으로 바꾸려면 카탈로그가 필요하다. 파서는 카탈로그를 모르므로 "사용자가 지정하지 않았다"는 사실만 `None`으로 전달하고, 해석은 실행기에 맡긴다. 파서가 카탈로그를 보기 시작하면 파서 테스트마다 카탈로그가 필요해지고, 문법 오류와 스키마 오류가 한 곳에서 섞인다.

### 모든 문장은 자기 줄 번호를 안다

`Insert`와 `Select`는 `line` 필드를 가진다. 4단계 실행기가 "없는 테이블"을 발견했을 때, 그 문장이 파일의 몇 번째 줄인지 알려 주기 위해서다. 줄 번호는 문장의 의미가 아니므로 동등 비교에서는 제외한다(`compare=False`). 테스트에서 `Select(...) == Select(...)`를 비교할 때 줄 번호가 끼어들지 않는다.

## 4. 재귀 하강: 문법 규칙 하나가 함수 하나

파서는 2절의 문법 규칙을 거의 그대로 함수로 옮긴 것이다.

| 문법 규칙 | 함수 |
| --- | --- |
| `program` | `_parse_program` |
| `statement` | `_parse_statement` |
| `insert` | `_parse_insert` |
| `select` | `_parse_select` |
| `condition` | `_parse_condition` |
| `id_list` | `_parse_id_list` |
| `literal_list`, `literal` | `_parse_literal_list`, `_parse_literal` |

각 함수는 "지금 토큰부터 내 규칙에 맞는 만큼 소비하고, 결과 객체를 돌려준다"는 약속을 지킨다. 예를 들어 `_parse_select`는 다음과 같다.

```
SELECT 를 기대한다
'*' 가 보이면 소비하고 columns = None, 아니면 _parse_id_list()
FROM 을 기대한다
identifier 를 기대한다 → table
WHERE 가 보이면 소비하고 _parse_condition(), 아니면 where = None
Select(table, columns, where) 를 돌려준다
```

핵심 도구는 두 개다.

- `_peek()`: 현재 토큰을 소비하지 않고 본다. "WHERE가 있는가"처럼 선택 규칙에서 쓴다.
- `_expect(kind, value)`: 현재 토큰이 기대한 것이면 소비하고 돌려주고, 아니면 `ParseError`를 낸다. 오류 메시지에 "무엇을 기대했고 무엇이 왔는가"가 자동으로 들어간다.

이 방식의 장점은 코드와 문법이 1:1이라 **문법을 바꾸면 어느 함수를 고칠지 바로 안다**는 것이다. 단점은 문법이 복잡해지면(연산자 우선순위, 좌재귀) 손으로 짜기 어려워지는데, 이 과제의 문법은 그 수준이 아니다.

## 5. 파서가 검사하는 것과 하지 않는 것

| 검사 | 파서 | 이유 |
| --- | --- | --- |
| 토큰 순서가 문법에 맞는가 | O | 파서의 본업 |
| INSERT 컬럼 수와 값 수가 같은가 | O | 카탈로그 없이 문장만 보고 알 수 있다 |
| INSERT 컬럼 목록에 중복이 있는가 | O | 위와 같다 |
| 테이블이 존재하는가 | X | 카탈로그가 필요하다 → 실행기 |
| 컬럼이 존재하는가, 타입이 맞는가 | X | 카탈로그가 필요하다 → 실행기 |
| 컬럼을 생략한 INSERT의 값 수가 스키마와 맞는가 | X | 카탈로그가 필요하다 → 실행기 |

기준은 하나다. **카탈로그 없이 문장만 보고 알 수 있으면 파서, 아니면 실행기.**

## 6. 결정: 전체를 파싱한 뒤에 실행한다

공개 함수는 `parse(sql) -> list[Statement]` 하나다. 파일 전체를 파싱해 문장 리스트를 만들고, 그중 하나라도 문법이 틀리면 리스트를 돌려주지 않고 `ParseError`를 낸다.

대안은 문장을 하나씩 파싱해 실행하는 것이다. 그러면 세 번째 문장에 오타가 있을 때 앞의 두 INSERT는 이미 파일에 쓰인 뒤다. 사용자는 오타를 고쳐 다시 실행하게 되고, 그러면 앞의 두 행이 중복 저장된다. 전체를 먼저 파싱하면 이 상황이 생기지 않는다.

실행 중 오류(없는 테이블, 타입 불일치)는 파싱으로 미리 잡을 수 없으므로 4단계에서 따로 정한다.

## 7. 오류

모두 `ParseError`이고 문제가 된 토큰의 위치가 붙는다.

| 입력 | 메시지 |
| --- | --- |
| `SELECT name students;` | `1:13: FROM 이 와야 하는데 식별자 'students' 가 왔습니다` |
| `SELECT * FROM t` | `1:16: ';' 이 와야 하는데 입력이 끝났습니다` |
| `DELETE FROM t;` | `1:1: SELECT 또는 INSERT 이 와야 하는데 식별자 'delete' 가 왔습니다` |
| `SELECT *, name FROM t;` | `1:9: FROM 이 와야 하는데 ',' 가 왔습니다` |
| `INSERT INTO t (a, b) VALUES (1);` | `1:1: 컬럼 2개에 값 1개가 왔습니다` |
| `WHERE id = name` (SELECT 안에서) | `1:28: 숫자 또는 문자열 이 와야 하는데 식별자 'name' 가 왔습니다` |

`DELETE`는 키워드 목록에 없으므로 토크나이저가 식별자 `delete`로 넘긴다. 파서 입장에서는 "문장 시작 자리에 식별자가 왔다"다. 메시지가 조금 어색하지만 위치와 원인은 정확하다.

## 산출물

```
minidb/
├── ast.py         # Condition, Insert, Select
└── parser.py      # parse()
tests/
└── test_parser.py
```

## 완료 기준

```sh
pytest tests/test_parser.py
```

- 문법에 맞는 INSERT와 SELECT의 모든 변형(컬럼 지정/생략, `*`, WHERE 유무, 연산자 여섯 개)이 기대한 AST가 된다.
- 여러 문장이 리스트로 나오고, 각 문장의 `line`이 맞다.
- 7절의 오류들이 정확한 위치와 함께 `ParseError`가 된다.
- 두 번째 문장에 오류가 있으면 첫 문장도 돌려주지 않는다.

## 다음 단계

3단계 저장소. 파서와 무관하게, 행을 파일에 쓰고 읽는 층을 만든다. 4단계에서 파서의 출력과 저장소를 실행기가 연결한다.
