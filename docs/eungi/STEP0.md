# 지도 만들기(0단계): 준비

> **한 줄 요약**: 코드를 쓰기 전에, "users 테이블에는 어떤 열이 있는지" 적은 파일과 연습용 SQL 파일을 만들었습니다.

## 왜 필요한가

진짜 데이터베이스는 이런 SQL로 테이블을 먼저 만듭니다.

```sql
CREATE TABLE users (id INT, name TEXT, age INT);
```

그런데 **우리 과제는 `CREATE TABLE`을 지원하지 않습니다.** 과제 요구사항이 INSERT와 SELECT뿐이기 때문입니다. 그러면 엔진은 "users 테이블에 name 열이 있나? age는 숫자인가?"를 알 방법이 없습니다.

그래서 이 정보를 **우리가 직접 파일에 적어 두기로** 했습니다. 그 파일이 `data/schema.json`입니다.

## 만든 파일

```
mini-dbms/
├── data/
│   └── schema.json     ← 우리가 직접 만든 파일. 테이블과 열 정보
├── examples/
│   ├── step1.sql       ← 지도 만들기(1단계) 확인용
│   ├── step1_error.sql ← 지도 만들기(1단계) 확인용 (틀린 문장이 섞인 것)
│   └── step2.sql       ← 지도 만들기(2단계) 확인용
└── .gitignore          ← 실행하다 생기는 파일은 GitHub에 안 올리게
```

### `data/schema.json`

이 파일은 어디서 받아 온 것이 아니라 **우리가 직접 손으로 쓴 파일**입니다. 내용은 한 줄입니다.

```json
{"users": [["id", "INT"], ["name", "TEXT"], ["age", "INT"]]}
```

읽는 법:

| 부분 | 뜻 |
| --- | --- |
| `"users"` | 테이블 이름 |
| `["id", "INT"]` | 첫 번째 열 이름은 `id`, 숫자 |
| `["name", "TEXT"]` | 두 번째 열 이름은 `name`, 글자 |
| `["age", "INT"]` | 세 번째 열 이름은 `age`, 숫자 |

- 타입은 `INT`(숫자)와 `TEXT`(글자) 두 가지만 씁니다.
- **첫 열은 항상 `id`**입니다. id는 사람이 넣지 않고, 엔진이 1, 2, 3… 순서로 자동으로 붙입니다.
- 이 순서가 그대로 저장 순서가 됩니다. 나중에 파일에는 `[1, "현지", 25]`처럼 id, name, age 순서로 저장됩니다.
- 테이블을 하나 더 만들고 싶으면, 이 파일에 한 줄만 더 적으면 됩니다. 코드는 안 고쳐도 됩니다.

### `examples/` 폴더의 SQL 파일

단계가 끝날 때마다 "제대로 되나?"를 같은 명령으로 확인하려고 만든 파일입니다.

`examples/step1.sql`: 두 사람을 넣고 전체를 조회합니다.
```sql
INSERT INTO users (name, age) VALUES ('현지', 25);
INSERT INTO users (name, age) VALUES ('민수', 31);
SELECT * FROM users;
```

`examples/step1_error.sql`: 가운데 문장이 일부러 틀렸습니다. `email`이라는 열은 없기 때문입니다.
```sql
INSERT INTO users (name, age) VALUES ('a', 1);
INSERT INTO users (email) VALUES ('x');
INSERT INTO users (name, age) VALUES ('b', 2);
```

`examples/step2.sql`: id가 2인 사람을 찾습니다.
```sql
SELECT * FROM users WHERE id = 2;
```

INSERT에 id가 없는 것을 눈여겨보세요. id는 엔진이 붙여 줍니다.

### `.gitignore`

코드를 실행하면 `data/users.tbl`(실제 데이터가 저장되는 파일)이 생깁니다. 사람마다 내용이 다르니 GitHub에는 올리지 않도록 적어 둔 파일입니다.

## 이 단계에서 정한 것

자세한 이유는 [DECISIONS](./DECISIONS.md)의 해당 번호에 있습니다.

- **D1** 파이썬에 기본으로 들어 있는 기능만 씁니다. 따로 설치할 것이 없습니다.
- **D2** 테이블 정보는 `data/schema.json`에 직접 적습니다.
- **D3** 모든 테이블의 첫 열은 `id`입니다.
- **D4** `schema.json`과 데이터 파일은 `data/` 폴더 하나에 둡니다.
- **D5** 단계마다 확인용 SQL을 `examples/`에 둡니다.

## 직접 확인해 보기

저장소 맨 위 폴더(`mini-dbms`)에서 실행합니다.

| 명령 | 이렇게 나오면 됨 |
| --- | --- |
| `python3 --version` | `Python 3.8` 이상 |
| `cat data/schema.json` | 위의 한 줄이 그대로 보임 |
| `ls examples` | `step1.sql  step1_error.sql  step2.sql` |

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `No such file or directory` | 저장소 맨 위 폴더(`mini-dbms`)에서 실행했는지 확인 |
| git이 `unable to map index file` 오류를 냄 | 저장소를 Desktop(바탕화면) 폴더에 두면 iCloud 동기화와 부딪힐 수 있음. `~/dev/mini-dbms`처럼 다른 곳에 두기 |
| `schema.json`을 고쳤더니 `JSONDecodeError` | 따옴표는 큰따옴표(`"`)만 쓰고, 마지막 항목 뒤에 쉼표를 남기지 않기 |
