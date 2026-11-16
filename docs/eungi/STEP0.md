# 0단계: 준비

## 이 단계에서 한 일

코드를 쓰기 전에 **테이블 모양을 적은 파일**과 **연습용 SQL 파일**을 준비했습니다.

- 우리 과제는 `CREATE TABLE`을 만들지 않습니다. 그래서 "users 테이블에는 id, name, age 열이 있다"는 정보를 `data/schema.json`에 미리 적어 둡니다.
- 단계마다 같은 명령으로 확인할 수 있게 `examples/` 폴더에 SQL 파일을 둡니다.

## 만든 파일

```
mini-dbms/
├── .gitignore          실행할 때 생기는 data/*.tbl, __pycache__ 는 올리지 않음
├── data/
│   └── schema.json     테이블마다 어떤 열이 있고, 각 열이 숫자인지 글자인지
└── examples/
    ├── step1.sql       1단계 확인용 (INSERT 두 번 + 전체 조회)
    └── step2.sql       2단계 확인용 (id로 찾기)
```

`data/schema.json`
```json
{"users": [["id", "INT"], ["name", "TEXT"], ["age", "INT"]]}
```
- `INT` = 숫자, `TEXT` = 글자. 타입은 이 두 가지뿐입니다.
- 첫 열은 항상 `id`입니다. id는 사람이 넣지 않고 엔진이 1, 2, 3… 순서로 붙입니다.

`examples/step1.sql`
```sql
INSERT INTO users (name, age) VALUES ('현지', 25);
INSERT INTO users (name, age) VALUES ('민수', 31);
SELECT * FROM users;
```

`examples/step2.sql`
```sql
SELECT * FROM users WHERE id = 2;
```

## 이 단계에서 정한 것

| 정한 것 | 왜 | 출처 |
| --- | --- | --- |
| 파이썬 표준 라이브러리만 씀. 설치할 것 없음 | 누구나 받자마자 실행할 수 있음. 파서·인덱스·서버를 직접 만들어 설명할 수 있어야 함 | DESIGN.md 제안과 같음 |
| 테이블 모양은 `data/schema.json`에 적어 둠. 타입은 `INT`, `TEXT` | `CREATE TABLE`이 없어서, 열 이름과 타입을 알 곳이 따로 필요함 | DESIGN.md 제안과 같음 |
| 모든 테이블의 첫 열은 `id INT` | 자동 번호와 인덱스(목차)의 기준이 됨 | DESIGN.md 제안과 같음 |
| `schema.json`과 데이터 파일(`users.tbl`)은 `data/` 폴더 하나에 | 엔진은 폴더 이름 하나만 받으면 됨: `Engine("data")` | 새로 정함 |
| 단계마다 확인용 SQL을 `examples/`에 | 완료 확인을 매번 같은 명령으로 반복할 수 있음 | 새로 정함 |

**출처** 칸: "DESIGN.md 제안과 같음" = 팀 설계 문서 [DESIGN.md](../DESIGN.md) 4절에 제안으로 적힌 것을 그대로 따름. "새로 정함" = DESIGN에 없어서 만들면서 정함. "교차 검토로 정함" = 두 검토자가 코드를 돌려 보고 문제를 찾아 고치면서 정함.

## 완료 확인

저장소 맨 위 폴더(`mini-dbms`)에서 실행합니다.

| 명령 | 이렇게 나오면 완료 |
| --- | --- |
| `python3 --version` | 3.8 이상 |
| `python3 -c "import json; print(json.load(open('data/schema.json')))"` | `{'users': [['id', 'INT'], ['name', 'TEXT'], ['age', 'INT']]}` |
| `ls examples` | `step1.sql  step2.sql` |

## 나중에 바꿀 곳

| 지금 | 언제 | 어떻게 |
| --- | --- | --- |
| 테이블은 `users` 하나 | 필요할 때 | `schema.json`에 한 줄 추가하면 끝. 코드는 안 고쳐도 됨 |

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `can't open file '/Users/.../Desktop/...'` | 다른 폴더에서 실행한 것. 저장소는 `~/dev/mini-dbms` 같은 곳에 두기. Desktop 폴더는 iCloud 동기화 때문에 git이 `unable to map index file` 오류를 낼 수 있음 (여기서 index는 git 내부 파일 이야기로, 우리 프로젝트의 인덱스와는 상관없음) |
| `JSONDecodeError` | `schema.json`의 따옴표가 큰따옴표(`"`)인지, 마지막에 쉼표가 남지 않았는지 확인 |
