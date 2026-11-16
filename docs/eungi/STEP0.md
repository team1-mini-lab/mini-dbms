# 0단계: 준비

## 목표

코드를 쓰기 전에 폴더, 테이블의 열 구성(`schema.json`), 연습용 SQL 파일을 준비합니다. 아래 구조가 있으면 완료입니다.

## 이 단계에서 정한 것

| 관련 코드 | 정한 것 | 이유 |
| --- | --- | --- |
| 프로젝트 전체 | 파이썬 표준 라이브러리만 사용. 가상환경과 `requirements.txt`는 두지 않음 | 설치 없이 바로 실행됨. 파서, 인덱스, 서버를 직접 만들어 설명할 수 있음 (DESIGN.md 제안과 같음) |
| `data/schema.json` | 테이블의 열 구성은 `schema.json`에 미리 적어 둠. 타입은 `INT`, `TEXT` 두 가지 | `CREATE TABLE`이 없으므로 열과 타입을 알 곳이 필요 (DESIGN.md 제안과 같음) |
| `data/schema.json` | 모든 테이블의 첫 열은 `id INT` | 자동 ID와 인덱스의 기준 (DESIGN.md 제안과 같음) |
| `data/` | `schema.json`과 테이블 파일(`users.tbl`)을 `data/` 폴더 하나에 둠 | 엔진은 폴더 하나만 받으면 됨 (`Engine("data")`, 접점 1) |
| `examples/` | 단계마다 확인용 SQL 파일을 하나씩 둠 (`step1.sql`, `step2.sql`) | 완료 테스트를 같은 명령으로 반복할 수 있음 |

[DECISIONS.md](./DECISIONS.md)에도 같은 내용이 모여 있습니다.

## 만드는 파일

```
mini-dbms/
├── .gitignore          data/*.tbl, __pycache__, .DS_Store 제외
├── data/
│   └── schema.json     테이블의 열 구성
└── examples/
    ├── step1.sql       1단계 확인용
    └── step2.sql       2단계 확인용
```

`data/schema.json`
```json
{"users": [["id", "INT"], ["name", "TEXT"], ["age", "INT"]]}
```

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

## 완료 테스트

| 확인 방법 | 기대 결과 |
| --- | --- |
| `python3 --version` | 3.8 이상 |
| `python3 -c "import json; print(json.load(open('data/schema.json')))"` | `{'users': [['id', 'INT'], ['name', 'TEXT'], ['age', 'INT']]}` |
| `ls examples` | `step1.sql  step2.sql` |

## 나중에 바꿔 끼울 곳

| 지금 | 바뀌는 단계 | 바뀌는 모습 |
| --- | --- | --- |
| 테이블은 `users` 하나 | 13단계 | 100만 건 SQL을 만들 때 필요하면 테이블을 더함. `schema.json`에 한 줄 추가하면 됨 |

## 문제가 생기면

| 증상 | 해결 |
| --- | --- |
| `can't open file '/Users/.../Desktop/...'` | 다른 폴더에서 실행함. 저장소는 `~/dev/mini-dbms`에 둠. Desktop 폴더는 iCloud 동기화 때문에 git이 `unable to map index file` 오류를 낼 수 있음 |
| `json.decoder.JSONDecodeError` | `schema.json`의 따옴표가 큰따옴표(`"`)인지, 마지막에 쉼표가 남지 않았는지 확인 |
