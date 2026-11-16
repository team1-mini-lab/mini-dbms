# 3단계: API 서버

## 목표

다른 코드가 HTTP로 SQL을 보낼 수 있는 서버를 만듭니다. 아직 스레드는 하나입니다. `curl`로 보낸 SQL의 결과가 CLI와 같으면 완료이고, 여기까지가 지도입니다.

## 핵심 문제: 입구만 하나 더

```
cli.py ─────┐
            ├──→ engine.execute(sql)       ← 접점 1, 둘이 같은 함수
server.py ──┘
   ▲  POST /query {"sql": "..."}           ← 접점 4
curl, 다른 코드
```

- 서버는 엔진 속을 모릅니다. 요청에서 SQL을 꺼내 `engine.execute`에 넘기고, 결과를 `{"results": [...]}`로 감싸 돌려줄 뿐입니다.
- 그래서 서버를 붙여도 엔진 코드는 한 줄도 바뀌지 않습니다.

## 질문과 정리

| 질문 | 정리 |
| --- | --- |
| 왜 주소가 `/query` 하나인가 | SQL 안에 동작(INSERT인지 SELECT인지)이 들어 있어 주소를 나눌 필요가 없음 |
| 왜 스레드 하나인가 | 지도 단계라서. 표준 `HTTPServer`는 원래 한 번에 요청 하나를 처리함. 15단계에서 Thread Pool로 바꿈 |
| 엔진은 몇 개 만드나 | 서버가 켜질 때 하나만 만들어 모든 요청이 같이 씀 |

## 이 단계에서 정한 것

| 관련 코드 | 정한 것 | 이유 |
| --- | --- | --- |
| `server.py` | HTTP 서버는 표준 `http.server`. 주소는 `POST /query` 하나 | SQL 자체에 동작이 담겨 있음 (DESIGN.md 제안과 같음) |
| `server.py` 맨 아래 | 서버 포트는 8000 | macOS에서 5000번은 AirPlay와 겹칠 수 있음. mini-redis와 같은 포트 |
| `server.py` `engine = Engine("data")` | 엔진은 서버가 켜질 때 하나만 만듦 | 모든 요청이 같은 다음 ID와 목차를 봐야 함 |
| `server.py` 응답 | `{"results": engine.execute(sql)}`, 한글은 그대로 (`ensure_ascii=False`) | 접점 4. `curl`에서 바로 읽힘 |
| `server.py` `do_POST` | `/query`가 아닌 주소는 일단 `send_error(404)` | JSON 오류 응답은 17단계 |

## 만드는 파일

| 파일 | 내용 |
| --- | --- |
| `server.py` (새로 만듦) | `BaseHTTPRequestHandler`의 `do_POST`에서 본문 JSON의 `sql`을 꺼내 `engine.execute`. `HTTPServer(("localhost", 8000), Handler)` |

## 완료 테스트

서버를 켜는 터미널과 요청을 보내는 터미널을 **따로** 씁니다. 서버는 켜진 채로 요청을 기다리므로, 같은 터미널에서는 다음 명령을 칠 수 없습니다.

**터미널 1**: 서버를 켜 둡니다.

```bash
cd ~/dev/mini-dbms
python3 server.py
```

```
http://localhost:8000 에서 POST /query 를 기다립니다
```

**터미널 2**: 새로 열어서 보냅니다.

```bash
cd ~/dev/mini-dbms
curl -X POST http://localhost:8000/query -d '{"sql": "SELECT * FROM users WHERE id = 2;"}'
```

```
{"results": [{"type": "select", "columns": ["id", "name", "age"], "rows": [[2, "민수", 31]], "used_index": true}]}%
```

맨 끝의 `%`는 오류가 아니라, 응답 끝에 줄바꿈이 없어서 zsh가 붙여 주는 표시입니다.

요청이 올 때마다 **터미널 1**에 기록이 한 줄씩 찍힙니다.

```
127.0.0.1 - - [16/Nov/2026 11:48:32] "POST /query HTTP/1.1" 200 -
```

| 부분 | 뜻 |
| --- | --- |
| `127.0.0.1` | 요청을 보낸 곳 (내 컴퓨터의 curl) |
| `"POST /query HTTP/1.1"` | `/query`로 POST 요청이 옴 |
| `200` | 성공 |

15단계에서는 이 기록에 어느 스레드가 처리했는지를 같이 찍습니다.

| 확인 방법 | 기대 결과 |
| --- | --- |
| 위 `curl` | 2단계 CLI 결과와 같은 내용 |
| `curl -X POST http://localhost:8000/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('하늘', 22);\"}"` 뒤 CLI로 `SELECT *` | 서버로 넣은 줄이 CLI에서도 보임 |
| `curl -X POST http://localhost:8000/nope -d '{}'` | 404 |

세 가지가 맞으면 지도 완성입니다.

## 나중에 바꿔 끼울 곳

| 지금 (임시) | 바뀌는 단계 | 바뀌는 모습 | 안 고쳐도 되는 곳 |
| --- | --- | --- | --- |
| `HTTPServer` (스레드 하나) | 15단계 | 미리 만든 스레드 N개 + 요청 줄(`queue.Queue`). 줄이 가득 차면 503 | 엔진 |
| lock 없음 | 16단계 (15단계보다 먼저 해도 됨) | `engine.execute` 안을 `with self._lock:`으로 감쌈 | 서버. lock은 엔진 안에 둠 |
| 404는 HTML, 잘못된 JSON은 서버 오류 | 17단계 | `{"error": {"code": ..., "message": ...}}` 한 가지 모양 | 엔진 |

## 문제가 생기면

| 증상 | 해결 |
| --- | --- |
| `curl: (7) Failed to connect to localhost port 8000` | 서버가 안 켜져 있음. 터미널 1에서 `python3 server.py`가 켜져 있는지 확인 |
| `curl: (6) Could not resolve host: 터미널` | 명령 뒤의 설명(`# 터미널 2`)까지 같이 붙여 넣음. 명령만 붙여 넣기 |
| `Address already in use` | 8000 포트를 다른 프로그램이 사용 중. `lsof -i :8000`으로 확인하고 끄기 |
| `curl`에서 한글이 `\uXXXX` | `json.dumps(..., ensure_ascii=False)`인지 확인 |
| 서버로 넣은 줄이 CLI에서 안 보임 | 서버와 CLI가 같은 `data/` 폴더를 쓰는지(같은 위치에서 실행했는지) 확인 |

## 코드에서 알아 둘 것

- `do_POST`: POST 요청이 오면 불리는 함수입니다. 본문은 `self.rfile.read(Content-Length만큼)`으로 읽습니다.
- `send_response` → `send_header` → `end_headers` → `wfile.write` 순서로 응답을 씁니다.
- `HTTPServer`는 요청을 하나씩 처리합니다. 15단계에서 이 부분을 Thread Pool로 바꿉니다.
