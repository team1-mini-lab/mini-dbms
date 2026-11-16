# 지도 만들기(3단계): API 서버

> **한 줄 요약**: 다른 코드가 인터넷 요청(HTTP)으로 SQL을 보내면, 실행해서 결과를 JSON으로 돌려주는 서버를 만들었습니다.

## 왜 필요한가

과제 요구사항에 **"외부 클라이언트가 API로 DBMS를 쓸 수 있어야 한다"**가 있습니다. 지도 만들기(1단계) CLI는 사람이 터미널에서 직접 실행할 때만 쓸 수 있습니다. 다른 코드가 우리 DBMS를 쓰려면, 계속 켜져 있으면서 요청을 받아 주는 서버가 필요합니다.

## CLI와 서버는 뭐가 다른가요?

| | CLI (`cli.py`) | 서버 (`server.py`) |
| --- | --- | --- |
| 누가 쓰나 | 사람이 터미널에서 | 다른 코드가 HTTP 요청으로 (테스트할 때는 `curl` 명령) |
| 언제까지 켜져 있나 | SQL 파일 하나 처리하고 꺼짐 | 켜 두면 끌 때까지 계속 요청을 기다림 |
| 결과 | 화면에 출력 | JSON으로 돌려줌 |

**둘은 같은 엔진 함수를 부릅니다.** 그래서 같은 SQL이면 결과도 같습니다.

```
cli.py ─────┐
            ├──→ engine.execute(sql)
server.py ──┘
```

서버는 엔진 속을 모릅니다. 요청에서 SQL을 꺼내 `engine.execute`에 넘기고, 결과를 감싸서 돌려줄 뿐입니다. 그래서 서버를 붙여도 엔진 코드는 바뀌지 않았습니다.

## 요청과 응답은 어떻게 생겼나요?

**주소는 하나**입니다: `POST /query`

보내는 것:
```json
{"sql": "SELECT * FROM users WHERE id = 2;"}
```

돌려받는 것: CLI 결과와 같은 내용을 `results`로 감쌉니다.
```json
{"results": [{"type": "select", "columns": ["id", "name", "age"], "rows": [[2, "민수", 31]], "used_index": true}]}
```

이 모양이 DESIGN 2절의 **접점 4**입니다.

**왜 주소가 하나뿐인가요?** SQL 안에 "넣기(INSERT)인지 찾기(SELECT)인지"가 이미 들어 있습니다. 그래서 `/insert`, `/select`처럼 주소를 나눌 필요가 없습니다.

## 잘못 보내면 어떻게 되나요?

> 🔄 **수정사항**: 처음 공유했을 때는 틀린 SQL에도 200을 보내고 뒤 문장까지 실행했습니다. 지금은 **첫 오류에서 멈추고 400**을 보냅니다 ([D30](./DECISIONS.md)). CLI는 바뀌지 않았습니다.

응답에는 결과와 함께 **번호**가 붙습니다. 첫 자리가 큰 뜻을 정합니다.

| 번호 | 뜻 | 우리 서버에서 |
| --- | --- | --- |
| 2xx (200) | 성공 | SQL을 모두 실행함 |
| 4xx (400, 404) | 보낸 쪽 잘못 | 요청이 잘못됐거나, SQL 문장이 틀렸거나, 없는 주소 |
| 5xx (501) | 서버 쪽 문제 / 지원 안 함 | POST가 아닌 방식(GET 등)으로 보냄 |

| 보낸 것 | 응답 |
| --- | --- |
| 정상 SQL | 200, `{"results": [...]}` |
| 틀린 SQL이 섞임 | 400, `{"error": {"code": "bad_sql", ...}, "results": [그 전까지의 결과]}` |
| JSON이 아닌 것, `sql`이 빠진 것 | 400, `{"error": {"code": "bad_request", ...}}` |
| 없는 주소 (`/nope`) | 404 |
| POST가 아닌 방식 (`GET /query`) | 501 |

**틀린 SQL이 섞이면 어떻게 되나요?** 한 요청에 SQL 문장이 여러 개 들어올 수 있습니다. 서버는 앞에서부터 하나씩 실행하다가 **처음 틀린 문장에서 멈춥니다.**

```
보냄: {"sql": "INSERT INTO users (name, age) VALUES ('현지', 25); SELEC * FROM users; INSERT INTO users (name, age) VALUES ('민수', 31);"}

1번 INSERT 현지 → 성공. 파일에 저장됨 (id 1)
2번 SELEC       → 오타. 여기서 멈춤
3번 INSERT 민수 → 실행 안 됨
```
```json
400 {"error": {"code": "bad_sql", "message": "2번째 문장: 아직 처리할 수 없는 SQL입니다: SELEC * FROM users"},
     "results": [{"type": "insert", "id": 1}]}
```

- **400**: 실패했다는 것을 응답 번호만 보고도 알 수 있습니다.
- **`message`의 "2번째 문장"**: 몇 번째 문장이 왜 틀렸는지 알려 줍니다.
- **`results`**: 멈추기 전까지 실행된 문장의 결과입니다. 1번 INSERT는 이미 저장됐다는 것을 알 수 있어서, 보낸 쪽이 전부 다시 보내다가 현지가 두 번 들어가는 일을 막을 수 있습니다.

**CLI는 왜 멈추지 않나요?** CLI는 100만 줄짜리 SQL 파일을 넣을 때도 씁니다(Phase 2(13단계)). 한 줄 때문에 나머지가 전부 안 들어가면 안 돼서, 틀린 문장만 오류로 표시하고 계속 실행합니다 (D9). 같은 엔진 함수를 쓰되, 서버만 `stop_on_error=True`로 부릅니다.

## ⚠️ 서버를 켜 둔 채로 CLI로 INSERT하면 안 됩니다

데이터를 넣는(INSERT) 건 **CLI와 서버 중 하나만** 써야 합니다.

**왜 그런가요?** 서버와 CLI는 따로 실행되고, 각자 "다음 번호"를 기억합니다.

```
1. 서버가 켜짐. 파일에 id 1, 2가 있음 → 서버가 기억: "다음 번호 = 3"
2. 서버가 켜진 채로 CLI로 INSERT 실행
   → CLI가 파일을 읽음 → "다음 번호 = 3" → id 3을 씀
3. 서버로 INSERT 요청
   → 서버는 CLI가 3을 쓴 걸 모름 → 또 id 3을 붙임
4. 파일에 id 3이 두 줄 생김
```

**어떻게 쓰면 되나요?**
- 서버가 켜져 있으면 INSERT는 서버로만 보냅니다.
- CLI로 넣었다면 서버를 껐다 다시 켭니다. 켜질 때 파일을 다시 읽기 때문입니다.
- 찾기(SELECT)만 하는 건 같이 써도 괜찮습니다.

Phase 3(16단계)에서 lock(한 번에 한 요청만 들어오게 하는 장치)을 걸지만, lock은 **서버 안의 요청끼리만** 줄을 세웁니다. 따로 실행되는 CLI까지 막지는 못합니다.

## 지금 서버의 한계

지금 서버는 **요청을 한 번에 하나씩만** 처리합니다. 요청 두 개가 동시에 오면 하나가 끝날 때까지 다른 하나는 기다립니다. 여러 요청을 동시에 처리하는 것은 Phase 3(15\~17단계)에서 만듭니다.

## 핵심 코드

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다.

### ① 엔진을 한 번만 만들기 · [`server.py`](../../server.py) 맨 위

```python
engine = Engine("data")
```

- 서버 파일이 시작될 때 **딱 한 번** 실행됩니다. 이후 모든 요청이 이 `engine` 하나를 같이 씁니다.
- 요청마다 엔진을 새로 만들면, 매번 파일을 처음부터 읽어 인덱스와 다음 번호를 다시 만들어야 해서 느리고, 번호가 어긋날 수 있습니다.

### ② 요청 처리 · [`server.py`](../../server.py)의 `do_POST`

```python
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):                                    # POST 요청이 오면 파이썬이 불러 줌
        if self.path != "/query":                         # 주소가 /query가 아니면
            self.send_error(404)                          #   404 (없는 주소)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))   # ① 본문이 몇 바이트인지
            body = json.loads(self.rfile.read(length))            # ② 그만큼 읽어서 JSON → dict
            sql = body["sql"]                                     # ③ "sql" 칸 꺼내기
            if not isinstance(sql, str):                          # ④ 글자(문자열)인지 확인
                raise ValueError("sql은 문자열이어야 합니다")
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, {"error": {"code": "bad_request", "message": str(e)}})
            return
        results = engine.execute(sql, stop_on_error=True)        # 첫 오류에서 멈춤
        if results and results[-1]["type"] == "error":            # 마지막 결과가 오류면 = 거기서 멈춤
            done = results[:-1]                                    # 실패 전까지 실행된 문장
            message = f"{len(done) + 1}번째 문장: {results[-1]['message']}"
            self._send(400, {"error": {"code": "bad_sql", "message": message}, "results": done})
            return
        self._send(200, {"results": results})                     # 전부 성공하면 200
```

- `Handler`는 요청 하나를 처리하는 클래스입니다. `do_POST`라는 이름은 정해진 규칙이라, POST 요청이 오면 파이썬의 `http.server`가 알아서 이 함수를 부릅니다. `do_GET`은 만들지 않아서 GET 요청에는 파이썬이 501(지원 안 함)로 답합니다.
- **`POST /query`**: `POST`는 "내용을 담아 보내는 방식", `/query`는 주소(`http://localhost:8000/query`의 뒷부분)입니다. 이 조합 하나만 받습니다.
- ①–④는 "SQL을 꺼낼 수 있는 요청인가"를 확인하는 부분입니다. 하나라도 실패하면 SQL을 실행하지도 않고 400을 보냅니다.

| 실패하는 곳 | 보낸 것 예시 | 나는 오류 |
| --- | --- | --- |
| ② JSON으로 못 읽음 | `hello`, 빈 본문 | `ValueError` |
| ③ `"sql"` 칸이 없음 | `{"query": "x"}` | `KeyError` |
| ③ `{...}` 모양이 아님 | `[1]` | `TypeError` |
| ④ sql이 글자가 아님 | `{"sql": 123}` | `ValueError` |

- "글자가 아니다"는 sql 값이 따옴표로 감싼 문자열이 아니라는 뜻입니다. `"SELECT * FROM users WHERE id = 2"`처럼 숫자가 섞여 있어도 따옴표 안이면 문자열이라 괜찮습니다.
- 여기를 통과하면 SQL을 엔진에 넘깁니다. 이때 `stop_on_error=True`를 줘서, 엔진이 첫 오류에서 멈추게 합니다.
- 엔진은 멈췄을 때 결과 목록의 **마지막**에 오류를 담아 돌려줍니다. 그래서 `results[-1]`(마지막 결과)이 오류인지만 보면 됩니다.
  - 오류면: 그 앞까지(`results[:-1]`)가 이미 실행된 문장입니다. 몇 번째 문장인지는 `len(done) + 1`로 셉니다. 400으로 보냅니다.
  - 아니면: 전부 성공이라 `{"results": [...]}`로 감싸서 200으로 보냅니다 (접점 4).

### ③ 응답 보내기 · [`server.py`](../../server.py)의 `_send`

```python
def _send(self, status, obj):
    out = json.dumps(obj, ensure_ascii=False).encode("utf-8")   # 결과 → JSON 글자 → 바이트
    self.send_response(status)                                  # 응답 번호 (200, 400)
    self.send_header("Content-Type", "application/json; charset=utf-8")   # "내용은 JSON"
    self.send_header("Content-Length", str(len(out)))           # "내용 길이는 몇 바이트"
    self.end_headers()
    self.wfile.write(out)                                       # 내용 보내기
```

200이든 400이든 이 함수 하나로 보냅니다. 응답 모양을 한 곳에서 관리하려고 묶었습니다.

### ④ 서버 켜기 · [`server.py`](../../server.py) 맨 아래

```python
if __name__ == "__main__":
    print("http://localhost:8000 에서 POST /query 를 기다립니다")
    HTTPServer(("localhost", 8000), Handler).serve_forever()
```

- `if __name__ == "__main__":`은 **이 파일을 직접 실행했을 때만** 아래를 실행하라는 뜻입니다. `python3 server.py`로 켜면 실행되고, 다른 파일이 `import`할 때는 실행되지 않습니다.
- `HTTPServer(("localhost", 8000), Handler)`: 내 컴퓨터의 8000번에서 요청을 받고, 요청이 오면 `Handler`로 처리합니다.
- `.serve_forever()`: `Ctrl + C`로 끌 때까지 계속 기다립니다.
- 기본 `HTTPServer`는 요청을 **하나씩 차례로** 처리합니다. 여러 요청을 동시에 처리하는 것은 Phase 3(15단계) Thread Pool입니다.

## 이 단계에서 정한 것

자세한 이유는 [DECISIONS](./DECISIONS.md)의 해당 번호에 있습니다.

- **D24** 서버는 파이썬 기본 기능 `http.server`로 만들고, 주소는 `POST /query` 하나입니다.
- **D25** 서버 번호(포트)는 8000입니다.
- **D26** 엔진은 하나만 만들고, 모든 요청이 같이 씁니다.
- **D27** 결과는 `{"results": [...]}`로 감쌉니다 (접점 4).
- **D28** 요청 자체가 잘못되면 400으로 답합니다.
- **D30** 틀린 SQL이 섞이면 첫 오류에서 멈추고 400 + 그때까지의 결과로 답합니다. 🔄 처음 공유한 뒤 바뀐 것
- **D29** 데이터를 쓰는 건 CLI와 서버 중 하나만입니다.

## 만든 파일

| 파일 | 하는 일 |
| --- | --- |
| `server.py` (새로 만듦) | 요청에서 `sql`을 꺼내 `engine.execute`에 넘기고, 결과를 JSON으로 돌려줌 |

## 직접 확인해 보기

터미널을 **두 개** 씁니다. 서버는 켜진 채로 계속 기다리기 때문에, 서버를 켠 터미널에서는 다른 명령을 칠 수 없습니다.

**터미널 1**: 서버 켜기
```bash
cd ~/dev/mini-dbms
python3 server.py
```
```
http://localhost:8000 에서 POST /query 를 기다립니다
```

**터미널 2**: 새로 열어서 요청 보내기
```bash
cd ~/dev/mini-dbms
curl -X POST http://localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id = 2;"}'
```
```
{"results": [{"type": "select", "columns": ["id", "name", "age"], "rows": [[2, "민수", 31]], "used_index": true}]}%
```
맨 끝 `%`는 오류가 아닙니다. 응답 끝에 줄바꿈이 없어서 터미널이 붙여 주는 표시입니다.

요청을 보낼 때마다 **터미널 1**에 기록이 한 줄씩 찍힙니다.
```
127.0.0.1 - - [16/Nov/2026 11:48:32] "POST /query HTTP/1.1" 200 -
```
`127.0.0.1`은 내 컴퓨터에서 보냈다는 뜻, `200`은 성공이라는 뜻입니다.

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| 위 `curl` | 지도 만들기(2단계) CLI 결과와 같은 내용 |
| 서버로 INSERT: `curl -X POST http://localhost:8000/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('하늘', 22);\"}"` | `{"results": [{"type": "insert", "id": 3}]}` (앞에 두 명이 있을 때) |
| `curl -X POST http://localhost:8000/query -d 'not json'` | 400, `{"error": {"code": "bad_request", ...}}` |
| `curl -X POST http://localhost:8000/query -d '{"sql": "SELEC * FROM users;"}'` | 400, `{"error": {"code": "bad_sql", "message": "1번째 문장: ..."}, "results": []}` |

다 확인했으면 터미널 1에서 `Ctrl + C`로 서버를 끕니다.

## 아직 엉성한 곳 (Phase 3에서 바뀜)

| 단계 | 바꿀 것 |
| --- | --- |
| 16 (먼저) | 엔진에 lock을 걸어서, 한 번에 한 요청만 엔진에 들어가게 함 |
| 15 | 미리 만들어 둔 스레드(일을 처리하는 흐름) 여러 개가 요청을 나눠 처리하게 함 |
| 17 | 404 같은 오류도 JSON으로 답함 |

**아직 없는 응답 번호** (지금은 문서로만 적어 두고, Phase 3에서 만듭니다)

| 번호 | 뜻 | 지금 서버 | 언제 |
| --- | --- | --- | --- |
| 405 | 주소는 맞는데 방식이 틀림 (예: `GET /query`) | 안 나옴. 파이썬 `http.server`는 `do_GET`이 없으면 **501**(지원 안 함)로 답함 | Phase 3(17단계)에서 405 + JSON으로 바꿀지 정함 |
| 500 | 서버 안에서 예상 못 한 오류 | 안 나옴. SQL 오류는 엔진이 잡아 400으로, 요청 오류도 400으로 보냄. 그 밖의 예상 못 한 오류가 나면 지금은 응답 없이 **연결이 끊김** | Phase 3(17단계)에서 500 + JSON으로 답하게 함 |
| 503 | 서버가 바쁨 | 안 나옴. 아직 요청을 하나씩만 받음 | Phase 3(15단계) Thread Pool에서 대기 줄이 가득 차면 503 (DESIGN 결정 15) |

16을 15보다 먼저 하는 이유: 동시에 처리하게 바꾸는 순간, 두 요청이 같은 "다음 번호"를 동시에 읽어서 같은 id를 붙일 수 있습니다. 그래서 lock을 먼저 겁니다.

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `Failed to connect to localhost port 8000` | 서버가 안 켜져 있음. 터미널 1에서 `python3 server.py`가 실행 중인지 확인 |
| `Could not resolve host: 터미널` | 명령 옆의 설명 글까지 같이 붙여 넣은 것. 명령만 붙여 넣기 |
| `Address already in use` | 8000번을 이미 다른 것이 쓰고 있음. 이전에 켠 서버를 `Ctrl + C`로 끄거나, `lsof -i :8000`으로 찾아서 끄기 |
| 같은 id가 두 줄 생김 | 서버가 켜진 채로 CLI로 INSERT한 것. 위 ⚠️ 참고. `data/users.tbl`을 지우고 다시 시작 |
