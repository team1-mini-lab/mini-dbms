# Phase 3(17단계): API 오류 응답 (+ 엣지 케이스 방어)

> **한 문장으로**: 서버가 내는 오류를 모두 `{"error": {"code", "message"}}` 한 모양의 JSON으로 바꿨습니다. 그리고 교차 검토에서 찾은 "서버가 멈추거나 이상하게 답하는 경우"를 따로 막았습니다.
>
> | | |
> | --- | --- |
> | **무엇이 왜 문제였나** | 15단계까지는 오류마다 모양이 달랐습니다. 없는 주소(404)와 `GET`(501)은 HTML로 나가고, 디스크 오류 같은 서버 고장은 400 `bad_sql`로 나가면서 파일 경로까지 보였습니다. 받는 쪽 프로그램(예: 주식 매수 화면)이 오류마다 따로 처리해야 했습니다 |
> | **무엇을 만들었나** | ① `server.py`: 모든 오류를 같은 JSON으로 (404·405·400·413·500·503). 서버 고장은 500, 자세한 내용은 로그에만. ② `server_guard.py`: 느린 연결, 이상한 `Content-Length` 같은 엣지 케이스 방어 (408 등). `python3 server.py`로 켜면 둘 다 켜짐 |
> | **무엇과 비교해 골랐나** | 오류 모양을 주소마다 다르게 두기 / 한 모양으로 통일하기 → 통일 ([D38](./DECISIONS.md#step17)). 엣지 방어를 `server.py`에 섞기 / 따로 두기 → 따로 둬서 `server.py`만 읽어도 원리가 보이게 ([D48](./DECISIONS.md#step17)) |

Phase 3는 16단계(lock) → 15단계(Thread Pool) → 17단계(오류 응답) 순서로 합니다. 이 단계는 [STEP15](./STEP15.md)의 서버 위에서 작업합니다.

> 📖 **처음 읽는다면**: 이 문서에는 **응답 번호(400, 404, 500 …), JSON, HTML, 요청 머리, `Content-Length`, 예외, `ValueError`, 트레이스백, 엣지 케이스**라는 말이 나옵니다. 뜻은 [용어 사전](./GLOSSARY.md)에 있습니다. 특히 [6절 HTTP](./GLOSSARY.md#http), [7절 응답 번호](./GLOSSARY.md#status), [8절 오류와 예외](./GLOSSARY.md#error)를 먼저 보세요.
>
> 한 줄로 바꾸면: **식당이 문제를 알릴 때 어떤 때는 말로, 어떤 때는 손짓으로 하던 것을 "같은 양식의 안내 쪽지 한 장"으로 통일하고(A), 일부러 식당을 멈추게 하는 이상한 손님들을 막는 규칙을 따로 만든 것(C)**이 17단계입니다.

## 이 단계에서 바뀐 것 한눈에

| 묶음 | 파일 | 무엇 | 왜 |
| --- | --- | --- | --- |
| **A. 오류 응답 (17단계 본래 범위)** | `server.py`, `engine.py` | 모든 오류를 같은 JSON으로. 500 | DESIGN 17단계 완료 기준 |
| **B. 15단계 결함 수정** | `server.py` | 503을 클라이언트가 읽게 닫기, 큐가 꽉 차도 꺼지게, `--queue 0` 막기, 켜기 실패 이유 보이기 | 15단계 기능(503, 끄기)이 실제로는 가끔 안 됐음 |
| **C. 엣지 케이스 방어** | `server_guard.py` (새로) | 받는 시간 전체 5초(408), `Content-Length` 깊은 검사, 1MB 제한(413), HTTP/0.9, chunked, 먼저 끊긴 연결 | REQUIREMENTS "엣지 케이스를 최대한 고려합니다" |
| 뺀 것 | | HEAD 처리, 포트 번호 범위 검사, 부하 테스트 그래프 | 요구사항에 없음. 부하 테스트는 D35 숫자 근거로만 남김 |

## 왜 필요한가

DESIGN 17단계 완료 기준입니다.
> 없는 주소, JSON이 아닌 본문 등에 HTML이 아니라 JSON 오류가 옴

15단계까지와 지금을 비교하면 이렇습니다.

| 경우 | 15단계까지 | 지금 |
| --- | --- | --- |
| 없는 주소 (`POST /abc`) | 404, **HTML** | 404 `not_found` JSON |
| `GET /query` | 501 "Unsupported method", **HTML** | 405 `method_not_allowed` JSON |
| 요청 줄이 깨짐 | 400, **HTML** | 400 `bad_request` JSON |
| 디스크 오류 같은 서버 고장 | 400 `bad_sql`, **응답에 파일 경로가 보임** | 500 `internal`, 자세한 내용은 서버 로그에만 |
| 큐가 꽉 찼을 때 큰 본문을 보냄 | 503을 보냈는데 클라이언트가 **못 읽을 때가 있음** | 503을 끝까지 읽음 |
| 연결만 열고 아무것도 안 보냄 / 아주 천천히 보냄 | 4개면 서버 전체가 멈춤 | 5초 뒤 408 `timeout` (엣지 방어) |

15단계에서도 "JSON이 아닌 본문"(400)과 503은 이미 JSON이었습니다. 17단계는 나머지 경로를 모두 같은 모양으로 맞춘 것입니다.

**HTML과 JSON이 왜 다른가요?** HTML은 사람이 브라우저로 보라고 만든 웹 페이지 형식이라, 프로그램이 그 안에서 "무슨 오류인지"를 꺼내기 어렵습니다. JSON은 `{"error": {"code": "not_found"}}`처럼 이름과 값이 딱 정해져 있어서, 프로그램이 `error.code`만 읽으면 됩니다.

**트레이스백**은 파이썬이 오류가 났을 때 "어느 파일 몇째 줄에서 났는지"를 길게 찍어 주는 기록입니다. 개발자에게는 유용하지만 `/Users/.../data/users.tbl` 같은 서버 안의 파일 경로가 들어 있어서, 밖으로 보내면 안 됩니다.

## 오류 목록 ([D38](./DECISIONS.md#step17))

| 응답 번호 | `code` | 언제 | 어디서 |
| --- | --- | --- | --- |
| 400 | `bad_request` | 요청 자체가 잘못됨: JSON이 아님, `sql`이 없음, 요청 줄이 깨짐, `HTTP/2.0` 같은 모르는 버전 | `server.py` |
| 400 | `bad_sql` | SQL이 틀림. 그 전까지 실행된(이미 저장된) 문장 결과를 `results`에 같이 담음 ([D30](./DECISIONS.md#step3)) | `server.py` |
| 404 | `not_found` | `/query`가 아닌 주소 | `server.py` |
| 405 | `method_not_allowed` | `PUT` 등 POST가 아닌 방식, `GET /query` (`GET /`·`/docs`는 브라우저용 시험 화면이라 200) | `server.py` |
| 408 | `timeout` | 요청을 5초 안에 다 받지 못함 | `server_guard.py` |
| 413 | `too_large` | 주소·요청 머리가 너무 김, 본문이 1MB를 넘음 | 둘 다 |
| 500 | `internal` | 서버 고장. 자세한 내용은 로그에만 | `server.py` |
| 503 | `busy` | 일하는 스레드와 큐가 모두 꽉 참 | `server.py` |

응답 번호의 첫 자리는 뜻을 나눕니다. **2로 시작 = 성공, 4로 시작 = 보낸 쪽(클라이언트)이 잘못 보냄, 5로 시작 = 서버 쪽 사정.** 그래서 SQL이 틀리면 4xx(보낸 사람이 고쳐야 함), 디스크가 고장 나면 5xx(서버 관리자가 고쳐야 함)입니다. `code`는 프로그램이 읽는 짧은 이름이고, `message`는 사람이 읽는 설명입니다.

서버가 내는 응답 번호는 이 표에 있는 것뿐입니다. 파이썬 `http.server`가 스스로 내는 다른 번호(414, 431, 501, 505)도 이 표의 번호로 바꿔서 보냅니다 (②).

```json
{"error": {"code": "bad_sql", "message": "2번째 문장: 테이블 'users' 에 컬럼 'email' 이 없습니다"},
 "results": [{"type": "insert", "id": 1}]}
```

문법이 틀린 문장(예: `SELEC 1`)이 하나라도 섞이면 Phase 1 처리기는 **문장 전체를 거절**하고 아무것도 실행하지 않습니다. 그때는 `results`가 비어 있고, 메시지에 틀린 곳의 줄:칸이 붙습니다.

```json
{"error": {"code": "bad_sql", "message": "문법 오류라 아무 문장도 실행하지 않았습니다: 1:50: SELECT 또는 INSERT 이 와야 하는데 식별자 'selec' 가 왔습니다"},
 "results": []}
```

## A. 오류 응답 · [`server.py`](../../server.py), [`engine.py`](../../engine.py)

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다. 아래 코드는 실제 파일과 주석까지 똑같습니다.

### ① 오류는 한 모양으로 · `error_body`, `Handler._error`

```python
def error_body(code, message, **extra):
    """Phase 3(17단계): 모든 오류를 {"error": {"code", "message"}} 한 모양으로 만든다."""
    return {"error": {"code": code, "message": message}, **extra}
```

```python
    def _error(self, status, code, message):
        self._send(status, error_body(code, message))
```

- 오류 응답은 모두 `error_body`로 만듭니다. 모양이 한곳에서 정해지니 경로마다 어긋날 일이 없습니다.
- `error_body`는 파이썬 `dict`(이름 → 값을 모아 둔 것)를 만들고, `_send`가 그것을 JSON 글자로 바꿔 응답으로 보냅니다.
- `**extra`: `bad_sql`처럼 오류 옆에 `results`를 더 붙여야 할 때 씁니다. `**`는 "이름=값으로 받은 것을 몇 개든 모아서" 라는 뜻입니다. `error_body("bad_sql", message, results=done)`이면 `{"error": {...}, "results": done}`이 됩니다.

### ② `http.server`가 스스로 내는 오류도 JSON으로 · `HTTP_ERRORS`, `Handler.send_error`

```python
# Phase 3(17단계): http.server가 스스로 내는 오류를 우리 오류 목록(D38)의 번호와 code로 바꿔 줌
#   501(모르는 방식) → 405, 414·431(주소·머리가 너무 김) → 413, 505와 그 밖 → 400
HTTP_ERRORS = {
    400: (400, "bad_request", "요청 형식이 잘못됐습니다"),
    408: (408, "timeout", "요청을 제한 시간 안에 다 받지 못했습니다"),
    414: (413, "too_large", "주소가 너무 깁니다"),
    431: (413, "too_large", "요청 머리가 너무 큽니다"),
    501: (405, "method_not_allowed", "POST만 받습니다"),
    505: (400, "bad_request", "HTTP/1.0 또는 HTTP/1.1만 받습니다"),
}
```

```python
    def send_error(self, code, message=None, explain=None):
        """Phase 3(17단계): http.server가 스스로 내는 오류도 JSON으로 (원래는 HTML).

        요청 줄이 깨졌거나, 주소·머리가 너무 길거나, do_GET 같은 함수가 없을 때 http.server가 이 함수를 부른다.
        """
        self.close_connection = True
        status, error_code, text = HTTP_ERRORS.get(code, HTTP_ERRORS[400])
        if status == 405:
            text = f"{self.command}는 받지 않습니다. POST /query 를 쓰세요"
        elif message and status == 400:
            text = f"{text} ({message})"           # 파이썬이 준 원래 설명(영어)을 괄호로 붙임
        self._error(status, error_code, text)
```

- `HTTP_ERRORS`는 "파이썬이 내려던 번호 → (우리가 보낼 번호, `code`, 설명)"을 적어 둔 표(`dict`)입니다. `HTTP_ERRORS.get(code, HTTP_ERRORS[400])`은 "표에서 찾고, 없으면 400 줄을 쓴다"는 뜻입니다.
- 요청이 우리 `do_POST`에 오기 **전에** `http.server`가 문제를 발견하면 `send_error`를 부릅니다. 원래 이 함수는 HTML 오류 페이지를 보냅니다.
- 이 함수를 바꿔 끼워서 그런 오류도 같은 JSON이 되게 했습니다. 15단계에서 `process_request`를 바꿔 끼운 것과 같은 방법입니다 (이어받아서 덮어쓰기).
- **`PUT` 같은 방식이 405가 되는 원리**: `http.server`는 `PUT` 요청이 오면 `do_PUT` 함수를 찾습니다. 우리는 그 함수를 만들지 않았으니, `http.server`가 `send_error(501)`(모르는 방식)을 부릅니다. `HTTP_ERRORS`가 501을 405 `method_not_allowed`로 바꿉니다. 405는 "주소는 있는데 그 방식은 안 받음"이라는 뜻이라 우리 상황에 더 맞습니다.
- **`GET`은 조금 다릅니다**: 17단계 뒤에 브라우저로 API를 시험해 보는 화면(`GET /`, `GET /docs`)을 더하면서 `do_GET`이 생겼습니다. 그래서 `GET /`와 `GET /docs`는 HTML 화면(200), `GET /query`는 위와 똑같이 `send_error(501)`을 직접 불러 405, 그 밖의 주소는 404로 답합니다 (`server.py`의 `Handler.do_GET`).
- `self.close_connection = True`: 오류를 보낸 뒤 연결을 닫게 표시합니다.

### ③ 요청 본문 검사 · `Handler.do_POST`, `Handler._parse_sql`

```python
    def do_POST(self):
        if self.path != "/query":
            self._error(404, "not_found", f"없는 주소입니다: {self.path} (POST /query 만 있습니다)")
            return
        raw = self._read_body()
        if raw is None:                           # 이미 오류로 답함
            return
        sql = self._parse_sql(raw)
        if sql is None:                           # 이미 오류로 답함
            return
```

```python
    def _parse_sql(self, raw):
        """본문 JSON에서 sql 문자열을 꺼낸다. 틀리면 400으로 답하고 None."""
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or "sql" not in body:
                raise ValueError('본문은 {"sql": "..."} 모양이어야 합니다')
            if not isinstance(body["sql"], str):
                raise ValueError("sql은 문자열이어야 합니다")
            return body["sql"]
        except (ValueError, RecursionError) as e:   # JSON 오류도 ValueError. RecursionError는 [[[[... 처럼 아주 깊은 JSON
            self._error(400, "bad_request", f"본문을 읽을 수 없습니다: {e}")
            return None
```

- `json.loads(raw)`: JSON 글자를 파이썬 값(`dict` 등)으로 바꿉니다. 이것을 "JSON을 푼다"고 썼습니다.
- `isinstance(body, dict)`: `body`가 `dict` 모양인지 확인합니다. `[1, 2]`처럼 다른 모양이면 틀린 요청입니다.
- `raise ValueError(...)`: 일부러 오류를 만들어 아래 `except`로 보냅니다. 그러면 오류 응답을 만드는 곳이 한 군데로 모입니다.
- 검사 순서: 주소 → 본문 읽기 → JSON 풀기 → `sql`이 문자열인지. 하나라도 틀리면 그 자리에서 오류로 답하고 `None`을 돌려줍니다. `do_POST`는 `None`을 보면 바로 끝냅니다.
- `RecursionError`: `[`를 20만 개 이어 붙인 JSON처럼 아주 깊게 중첩된 본문을 풀면 파이썬이 이 오류를 냅니다. 전에는 이걸 안 잡아서 **대답 없이 연결이 끊겼습니다** (교차 검토에서 찾음).

### ④ 서버 고장은 500 · `engine.execute`, `Handler.do_POST` ([D39](./DECISIONS.md#step17), [D47](./DECISIONS.md#step17))

```python
            except StorageError:        # 손님이 고칠 수 없는 데이터 문제 → 위로 → 500
                raise
            except MiniDBError as e:    # SQL이 틀림 → 결과에 담음 → 서버는 400
                results.append({"type": "error", "message": str(e)})
```

```python
        try:
            results = self.server.engine.execute(sql, stop_on_error=True)   # 첫 오류에서 멈춤 (D30)
        except Exception:
            # Phase 3(17단계, D39): SQL이 틀린 게 아니라 서버가 고장. 자세한 내용은 서버 로그에만
            traceback.print_exc()
            self._error(500, "internal", "서버 내부 오류입니다. 이 요청의 앞쪽 문장은 이미 저장됐을 수 있습니다")
            return
        if results and results[-1]["type"] == "error":
            done = results[:-1]                   # 실패 전까지 실행된(이미 저장된) 문장
            if results[-1].get("stage") == "parse":   # 문법 오류는 문장 전체를 거절 (몇 번째인지는 메시지의 줄:칸에)
                message = results[-1]["message"]
            else:
                message = f"{len(done) + 1}번째 문장: {results[-1]['message']}"
            self._send(400, error_body("bad_sql", message, results=done))
            return
        self._send(200, {"results": results})
```

- **먼저 알아 둘 것**: 파이썬에서 문제가 생기면 **예외**가 납니다. 예외는 종류가 있습니다. `ValueError`는 "값이 잘못됐다", `OSError`는 "파일이나 네트워크에 문제가 있다" 같은 식입니다. `except Exception`은 "종류 상관없이 다 받는다", `except ValueError`는 "`ValueError`만 받고 나머지는 위(나를 부른 쪽)로 넘긴다"는 뜻입니다. minidb는 **"SQL이 틀렸다"를 `MiniDBError`(그 아래 `ParseError`, `SchemaError`, `TypeMismatchError`, `ExecutionError`)로** 알립니다.
- **무엇이 문제였나**: 엔진은 `except Exception`으로 **모든** 오류를 "그 문장이 틀렸다"로 받았습니다. 그래서 디스크가 꽉 찬 것 같은 서버 고장도 400 `bad_sql`로 나갔고, 오류 문장에 들어 있던 **파일 경로**가 응답에 그대로 보였습니다. 서버의 `except Exception → 500`은 실제로는 거의 닿지 않았습니다 (교차 검토에서 찾음).
- **무엇을 바꿨나**: 엔진은 `MiniDBError`만 문장 오류로 담습니다. 단, 그중 `StorageError`(테이블 파일이 깨짐)는 손님이 SQL을 고쳐도 해결되지 않는 서버 쪽 문제라 담지 않고 올려 보냅니다. 그 밖의 예외는 엔진 밖으로 올라가고, 서버가 500 `internal`로 답합니다. 자세한 내용(트레이스백)은 `traceback.print_exc()`로 **서버 터미널에만** 찍습니다.
- lock은 `with`가 풀어 줍니다 ([STEP16](./STEP16.md)). 500 뒤에도 다음 요청은 정상으로 처리됩니다 (확인 스크립트로 확인).
- **CLI는 minidb 것을 씁니다**: `python -m minidb`는 문법 오류면 종료 코드 1, 실행 오류(손상된 행 포함)면 종료 코드 2로 멈춥니다. 서버의 400(SQL 오류)과 500(서버 쪽 문제) 구분과 같은 기준입니다.

## B. 15단계 결함 수정 · [`server.py`](../../server.py)

15단계에서 약속한 기능이 실제로는 가끔 안 되던 것을 고쳤습니다. 코드와 설명은 [STEP15](./STEP15.md)의 해당 절에 있습니다.

| 무엇이 문제였나 | 무엇을 바꿨나 | 코드 |
| --- | --- | --- |
| 503을 보낸 뒤 바로 닫아서, 클라이언트가 503을 못 읽을 때가 있었음 (2000번 중 522번) | 보내기만 먼저 닫고 남은 요청을 잠깐 읽어 버린 뒤 닫음 (`linger_close`) | [STEP15 ④](./STEP15.md#핵심-코드) |
| 그 `linger_close`가 받는 스레드를 붙잡아서, 아무것도 안 보내는 연결 60개면 다음 손님이 503을 받기까지 11.4초 | 0.02초 동안 아무것도 안 오면 바로 닫음 → 30개여도 약 0.6초 | 같은 곳 |
| 큐가 꽉 찬 채로 `Ctrl + C`를 누르면 15초가 지나도 안 꺼짐 | 아직 못 꺼낸 연결을 먼저 닫고 "그만" 신호 자리를 만듦 | [STEP15 ⑥](./STEP15.md#핵심-코드) |
| `--queue 0`이면 `Queue(0)` = 크기 제한 없음이 되어 503이 사라짐. `--workers 0`이면 영원히 대답 안 함 | 1 이상만 받음 (`positive_int`) | [STEP15 ⑧](./STEP15.md#핵심-코드) |
| 포트가 이미 쓰이면 마지막 줄이 `AttributeError`라서 진짜 이유가 가려짐 | 끌 때 쓰는 것을 먼저 만들고, 켜기 실패를 한 줄로 알려 줌 | [STEP15 ①, ⑧](./STEP15.md#핵심-코드) |

## 엣지 케이스 방어 · `server_guard.py`

**엣지 케이스**는 평소에는 잘 안 생기는 끝자락 상황입니다. 정상 사용자는 거의 안 하지만, 실수나 일부러 하면 서버를 멈추게 할 수 있는 요청들입니다. 식당으로 치면 "자리에 앉아서 주문을 영영 안 하는 손님", "주문서에 '음식 -1개'라고 적는 손님" 같은 경우입니다.

[`server_guard.py`](../../server_guard.py)는 `server.py`의 `Handler`와 `PooledHTTPServer`를 **이어받아서** 몇 함수만 덮어씁니다 (이어받기·덮어쓰기는 [STEP15](./STEP15.md#thread-pool이-뭔가요)에서 설명). `server.py`만 읽어도 과제 기능(Thread Pool, JSON 오류)의 원리가 보이게, 방어 코드는 이 파일에 따로 모았습니다 ([D48](./DECISIONS.md#step17)).

| 막는 것 | 막지 않으면 | 답 | 코드 |
| --- | --- | --- | --- |
| 연결만 열고 안 보냄 / 아주 천천히 보냄 | 일하는 스레드가 붙잡혀 서버 전체가 멈춤 | 408 | ⑥ |
| `Content-Length` 없음·음수·숫자 아님·`3_4` | 대답 없이 끊기거나 이상한 길이로 읽음 | 400 | ⑤ |
| `Content-Length`가 1MB 넘음 | 그만큼 메모리를 잡음 | 413 | ⑤ |
| 본문을 나눠 보냄(chunked) | 본문 없이 처리됨 | 400 | ⑤ |
| HTTP/0.9 형식의 한 줄 요청(`GET /`) | 응답에 상태 줄이 없음 | 400 | ⑦ |
| 답을 보내기 전에 클라이언트가 끊음 | 서버 로그에 트레이스백이 쏟아짐 | (조용히) | ⑧ |

### 어떻게 이어 붙이나 · `server.py`의 맨 아래, `server_guard.main`

```python
if __name__ == "__main__":
    import server_guard                      # 기본으로 엣지 케이스 방어(server_guard.py)를 켠 서버를 띄움
    server_guard.main()
```

```python
def main():
    server.main(GuardedServer, GuardedHandler)
```

- `python3 server.py`로 켜면 `server_guard.main()`이 불리고, `server.main`에 **방어가 붙은 클래스**(`GuardedServer`, `GuardedHandler`)를 넘깁니다. 그래서 기본으로 방어가 켜집니다. `python3 server_guard.py`로 켜도 같습니다.
- 확인 스크립트는 둘을 따로 씁니다: `check_errors.py`는 `server.py`의 클래스만, `check_guard.py`는 `server_guard.py`의 클래스를 씁니다.

### ⑤ `Content-Length` 깊은 검사와 1MB 제한 · `GuardedHandler._read_body` ([D42](./DECISIONS.md#step17))

`Content-Length`는 "본문이 몇 바이트인지" 클라이언트가 적어 보내는 값입니다. 서버는 이 숫자만큼 읽습니다. `server.py`의 `_read_body`는 `int()`로 바꾸기만 해서, 이런 값에서 문제가 생겼습니다 (교차 검토에서 실제로 보냄).

| 보낸 값 | 검사가 없으면 | 이유 |
| --- | --- | --- |
| `-1` | 연결이 끝날 때까지 스레드가 붙잡힘 | `read(-1)`은 "끝날 때까지 읽기" |
| `3_4` | 34로 읽힘 | 파이썬 `int()`는 숫자 사이의 밑줄을 허용 |
| `99999999999999999999` | 대답 없이 끊김 | 파이썬이 그만큼 읽을 자리를 못 만듦 |
| 없음 (chunked 전송) | 본문 없이 처리됨 | 나눠 보내는 방식은 `Content-Length` 대신 다른 머리를 씀 |

```python
    def _read_body(self):
        """server.py의 _read_body에 검사를 더한다: Content-Length는 0~9로만 된 숫자, 1MB까지, 받는 시간 마감."""
        if "Transfer-Encoding" in self.headers:
            self._error(400, "bad_request", "본문을 나눠 보내는 방식(Transfer-Encoding)은 받지 않습니다. Content-Length를 보내 주세요")
            return None
        value = self.headers.get("Content-Length")
        if value is None:
            self._error(400, "bad_request", "Content-Length가 필요합니다")
            return None
        if not (value.isascii() and value.isdigit()):   # -1, abc, 1e3, 3_4(파이썬 int()는 밑줄을 허용) 모두 막음
            self._error(400, "bad_request", f"잘못된 Content-Length입니다: {value}")
            return None
        length = int(value)
        if length > MAX_BODY:
            self.close_connection = True
            self._error(413, "too_large", f"요청 본문이 너무 큽니다 (최대 {MAX_BODY // (1024 * 1024)}MB). 대량 넣기는 CLI를 쓰세요")
            self.wfile.flush()
            linger_close(self.connection)         # 읽지 않은 본문이 남아 있으니 413을 읽을 수 있게 닫음
            return None
```

- `self.headers.get("Content-Length")`: 요청 머리에서 `Content-Length` 값을 꺼냅니다. 없으면 `None`입니다.
- `isascii() and isdigit()`: `0`\~`9`로만 된 글자인지 봅니다. `isascii()`는 영어·숫자 같은 기본 글자인지, `isdigit()`는 숫자 글자인지 봅니다. 둘 다 보는 이유는 `²`나 `١`(아랍 숫자) 같은 글자도 `isdigit()`에는 숫자로 통과하기 때문입니다. `-1`은 `-` 때문에, `1e3`은 `e` 때문에, `3_4`는 `_` 때문에 걸립니다.
- `MAX_BODY = 1024 * 1024`(1MB): INSERT 약 1.7만 문장 분량입니다. 100만 건 같은 대량 넣기는 서버가 아니라 CLI로 합니다 (Phase 2 13단계도 CLI 사용).
- `self.wfile.flush()`: `wfile`은 클라이언트에게 쓰는 통로입니다. `flush()`는 "모아 둔 것을 지금 바로 보내라"는 뜻입니다. 연결을 닫기 전에 413이 확실히 나가게 합니다.
- 413일 때는 본문을 읽지 않고 답하므로, 503과 같은 이유로 `linger_close`로 닫습니다 ([STEP15 ④](./STEP15.md#핵심-코드)).

### ⑥ 요청을 받는 시간 전체에 5초 · `GuardedHandler.handle_one_request`, 감시 스레드 ([D37](./DECISIONS.md#step15))

**무엇이 문제였나**: 15단계의 timeout은 "**한 번 받을 때마다** 5초"입니다([STEP15 ⑤](./STEP15.md#핵심-코드)). 한 글자라도 오면 5초가 다시 시작돼서, 이런 일이 생깁니다.

```
3초마다 한 글자씩 보내는 연결 4개 → 일하는 스레드 4개가 전부 붙잡힘 → 정상 요청은 끝없이 기다림
```

시험으로 치면, 15단계는 "문제 하나를 5초 안에 못 풀면 끝" 규칙입니다. 문제마다 5초가 다시 시작되니, 4초마다 한 문제씩 풀면 시험이 영원히 안 끝납니다. 17단계는 "시험 **전체**가 5초"로 바꾼 것입니다.

**무엇을 바꿨나**: "연결을 꺼낸 순간부터 본문을 다 받을 때까지" **전체**에 5초를 겁니다. 이 시간을 재는 **감시 스레드**를 서버를 켤 때 하나 만듭니다. 시험 감독관 한 명이 교실 전체의 시계를 보다가, 시간이 다 된 학생의 시험지를 거두는 것과 같습니다.

| 순서 | 누가 | 하는 일 |
| --- | --- | --- |
| 1 | 일하는 스레드 | 연결을 꺼내자마자 `_watch`로 "이 연결은 지금 + 5초가 마감"이라고 적음 |
| 2 | 감시 스레드 | 0.05초마다 적힌 목록을 보고, 마감이 지난 연결의 **받기 쪽만** 닫음 (`shutdown(SHUT_RD)`) |
| 3 | 일하는 스레드 | 받기에서 막혀 있던 읽기가 바로 끝남. 보내기 쪽은 열려 있으니 408 JSON을 보낼 수 있음 |
| 4 | 일하는 스레드 | 본문을 다 받으면 `_unwatch`로 목록에서 지움. 그 뒤 lock을 기다리는 시간과 SQL 실행 시간은 세지 않음 |

```python
    def _watch(self, sock, event):
        with self._watch_lock:
            self._next_token += 1
            if self._stop_watch.is_set():          # 끄는 중에 큐에서 꺼낸 연결은 바로 깨움
                event.set()
                try:
                    sock.shutdown(socket.SHUT_RD)
                except OSError:
                    pass
            else:
                self._watching[self._next_token] = (time.monotonic() + self.request_timeout, sock, event)
            return self._next_token

    def _unwatch(self, token):
        with self._watch_lock:
            self._watching.pop(token, None)

    def _watch_loop(self):
        """감시 스레드: 0.05초마다 마감이 지난 연결을 찾아 받기 쪽을 닫는다."""
        while not self._stop_watch.is_set():
            now = time.monotonic()
            with self._watch_lock:
                expired = [t for t, (deadline, _, _) in self._watching.items() if now >= deadline]
                expired = [self._watching.pop(t) for t in expired]
            for _, sock, event in expired:
                event.set()
                try:
                    sock.shutdown(socket.SHUT_RD)  # 받기만 닫음. 막혀 있던 읽기가 바로 끝나고, 보내기는 열려 있어 408을 보낼 수 있음
                except OSError:
                    pass
            self._stop_watch.wait(0.05)
```

- 코드를 줄여서 읽으면: `_watch`는 감시 목록에 "번호표 → (마감 시각, 연결, 깃발)"을 적고 번호표를 돌려줍니다. `_unwatch`는 그 번호표를 목록에서 지웁니다. `_watch_loop`는 0.05초마다 목록을 훑어 마감이 지난 것을 꺼내서 깃발을 올리고 받기 쪽을 닫습니다. `_stop_watch`는 "서버를 끄는 중"이라는 깃발입니다.
- `_watching`: 번호 → (마감 시각, 연결, "마감됐다"는 표시). 일하는 스레드 4개와 감시 스레드가 함께 고치는 dict라서 `_watch_lock`으로 잠그고 씁니다. 엔진 lock과는 **다른** lock이고, dict를 고치는 아주 짧은 순간만 잡습니다.
- `event`(`threading.Event`): "이 연결은 마감됐다"는 표시입니다. 일하는 스레드는 읽기가 끝난 뒤 이 표시를 보고, 덜 받은 이유가 마감 때문인지(408) 클라이언트가 덜 보낸 것인지(400) 구별합니다.
- **왜 요청마다 타이머 스레드를 만들지 않았나**: 요청마다 스레드를 새로 만들면 "스레드 수를 정해 둔다"는 Thread Pool의 뜻과 어긋납니다. 감시 스레드는 서버 전체에 딱 하나입니다.

감시를 등록하고 408을 보낼 자리를 만들려고, `http.server`의 `handle_one_request`도 덮어씁니다.

```python
    def handle_one_request(self):
        """요청 줄·머리·본문을 받는 시간 '전체'에 마감(request_timeout초)을 건다. 넘으면 408 JSON.

        http.server의 원래 handle_one_request는 시간이 넘으면 응답 없이 끊기만 해서, 408을 보낼 자리를 만들려고
        같은 순서(요청 줄 읽기 → parse_request → do_POST 등)를 여기서 직접 한다.
        """
        self.requestline = self.request_version = self.command = ""
        self._timed_out = threading.Event()
        self._token = self.server._watch(self.connection, self._timed_out)   # 감시 스레드에 "마감 = 지금 + 5초" 등록
        try:
            try:
                self.raw_requestline = self.rfile.readline(65537)
            except TimeoutError:
                self._timed_out.set()
                self.raw_requestline = b""
            if self._timed_out.is_set():          # 요청 줄을 다 받기 전에 마감
                self._timeout_error()
                return
            if len(self.raw_requestline) > 65536:
                self.close_connection = True
                self._error(413, "too_large", "요청 줄이 너무 깁니다")
                return
            if not self.raw_requestline:          # 아무것도 안 보내고 닫음
                self.close_connection = True
                return
            if not self.parse_request():          # 요청 줄·머리 읽기. 틀리면 send_error로 이미 답함
                return
            if self._timed_out.is_set():          # 머리를 다 받기 전에 마감
                self._timeout_error()
                return
            method = getattr(self, "do_" + self.command, None)
            if method is None:
                self.send_error(501)              # → 405 JSON (server.py의 send_error)
                return
            method()
            self.wfile.flush()
        except TimeoutError:                      # 감시 스레드보다 소켓 timeout이 먼저 온 경우
            self._timeout_error()
        finally:
            self.server._unwatch(self._token)     # 여러 번 불러도 됨
```

- `self.rfile.readline(65537)`: `rfile`은 클라이언트가 보낸 것을 읽는 통로입니다. 한 줄(요청 줄)을 최대 65537바이트까지 읽습니다. 65536보다 하나 더 읽어 보는 이유는 "65536을 넘었는지" 알기 위해서입니다.
- `getattr(self, "do_" + self.command, None)`: 방식이 `POST`면 `do_POST`라는 함수를 찾습니다. 없으면 `None`입니다.
- `http.server`는 연결 하나에서 요청을 처리할 때 이 함수를 부릅니다. 원래 함수는 시간이 넘으면 로그만 찍고 응답 없이 끊기 때문에, 408을 보낼 자리가 없었습니다. 그래서 원래와 같은 순서를 여기서 직접 하면서, 중간중간 "마감됐나"를 확인합니다.
- 본문을 읽는 부분은 ⑤ `_read_body`의 뒷부분입니다. 덜 받은 채 끝나면 마감 때문인지 보고 408 또는 400으로 답합니다.

```python
        try:
            raw = self.rfile.read(length)         # 감시 스레드가 받기를 닫으면 덜 받은 채로 끝남
        except TimeoutError:
            self._timed_out.set()
            raw = b""
        timed_out = self._timed_out.is_set()
        self.server._unwatch(self._token)         # 다 받았으면 마감 끝. 그 뒤 lock 기다림·실행 시간은 안 셈
        if timed_out:
            self._timeout_error()
            return None
        if len(raw) < length:                     # 클라이언트가 덜 보내고 닫음
            self.close_connection = True
            self._error(400, "bad_request", "본문이 Content-Length보다 짧습니다")
            return None
        return raw
```

- `GuardedServer.__init__`의 `self.RequestHandlerClass.timeout = request_timeout + 0.5`: 15단계의 "한 번 받을 때 5초"는 예비로 남겨 두되 0.5초 늦게 해서, 감시 스레드가 먼저 깨우게 합니다. 예비가 먼저 걸려도(`TimeoutError`) 같은 408로 답합니다.

### ⑦ HTTP/0.9 형식 막기 · `GuardedHandler.parse_request`

```python
    def parse_request(self):
        """HTTP/0.9 형식(`GET /`처럼 버전이 없는 한 줄)은 받지 않는다. 받으면 응답에 상태 줄이 빠진다."""
        if not super().parse_request():
            return False
        if self.request_version == "HTTP/0.9":
            self.request_version = "HTTP/1.0"     # 이렇게 바꿔야 상태 줄과 머리가 붙은 응답이 나감
            self.close_connection = True
            self._error(400, "bad_request", "HTTP/1.0 또는 HTTP/1.1 형식으로 보내 주세요")
            return False
        return True
```

- `GET /`처럼 버전 없이 두 단어만 보내면 `http.server`는 아주 옛날 형식(HTTP/0.9)으로 보고, 응답에 상태 줄(`HTTP/1.0 400 ...`)과 머리를 붙이지 않습니다. 받는 쪽은 응답 번호를 알 수 없습니다. 그래서 이 형식은 400으로 거절합니다.

### ⑧ 먼저 끊긴 연결은 조용히, 끌 때 깨우기 · `GuardedServer.handle_error`, `GuardedServer.server_close`

```python
    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return                                 # 답을 보내기 전에 클라이언트가 먼저 끊음. 서버 잘못이 아니라 조용히
        super().handle_error(request, client_address)
```

```python
    def server_close(self):
        with self._watch_lock:                     # 끄기 표시와 깨우기를 한 번에 (그 사이에 새로 등록되는 연결이 없게)
            self._stop_watch.set()
            watched = list(self._watching.values())
            self._watching.clear()
        for _, sock, event in watched:             # 받기에서 막혀 있는 일하는 스레드를 깨워야 "그만" 신호를 받음
            event.set()
            try:
                sock.shutdown(socket.SHUT_RD)
            except OSError:
                pass
        super().server_close()
        if self._watcher.is_alive():
            self._watcher.join(timeout=1)
```

- `sys.exc_info()[1]`: 지금 처리 중인 예외(오류)를 꺼냅니다. `isinstance(..., (A, B))`는 "그 오류가 A나 B 종류인지" 봅니다.
- 408을 보내려는데 클라이언트가 이미 닫았으면 `BrokenPipeError`(보내는 길이 끊김)가 납니다. `ConnectionResetError`는 상대가 연결을 강제로 끊었다는 뜻입니다. 서버 잘못이 아니라서 트레이스백을 찍지 않습니다.
- 끌 때 감시 중인 연결을 모두 깨웁니다. 받기에서 막혀 있던 일하는 스레드가 풀려나야 "그만" 신호(`None`)를 받고 끝납니다. 끄기 표시와 깨우기를 같은 lock 안에서 하는 이유: 그 사이에 큐에서 새로 꺼낸 연결이 등록되면 아무도 깨워 주지 않아서, 확인 스크립트를 동시에 여러 개 돌릴 때 가끔 5초 동안 안 꺼졌습니다 (교차 검토에서 찾음). `_watch`도 끄는 중이면 바로 깨웁니다 (⑥).

## 용어 풀이

이 문서에서 특히 많이 쓴 말만 모았습니다. 나머지는 [용어 사전](./GLOSSARY.md)에 있습니다.

| 용어 | 뜻 |
| --- | --- |
| `shutdown(SHUT_WR)` | 연결의 **보내기 쪽만** 닫음. "답은 다 보냈다"는 뜻. 받기는 계속 할 수 있음 |
| `shutdown(SHUT_RD)` | 연결의 **받기 쪽만** 닫음. 받기에서 막혀 있던 스레드가 바로 깨어남. 보내기는 계속 할 수 있음 |
| RST | 운영체제가 연결을 **강제로** 끊는 신호. 읽지 않은 데이터가 남은 채 닫으면 이 신호가 가서, 상대가 이미 도착한 응답도 못 읽을 수 있음 |
| `Content-Length` | 본문이 몇 바이트인지 클라이언트가 적어 보내는 요청 머리 |
| chunked | 본문을 조각으로 나눠 보내는 방식. `Content-Length` 대신 `Transfer-Encoding: chunked` 머리를 씀 |
| HTTP/0.9 | 아주 옛날 HTTP 형식. 요청에 버전이 없고 응답에 상태 줄이 없음 |
| `threading.Event` | 한 스레드가 `set()`으로 표시하면 다른 스레드가 `is_set()`으로 확인할 수 있는 깃발 |

## 요청 하나가 지나가는 길 (어디서 어떤 오류가 나나)

```
받는 스레드: 연결 받음 → 큐에 넣기
                └ 큐가 꽉 참 ─────────────────────────────────→ 503 busy (linger_close로 닫음)
worker:      꺼냄 → _watch: 5초 마감 등록 (엣지)
             → 요청 줄·머리 읽기
                ├ 5초 넘음 ──────────────────────────────────→ 408 timeout (엣지)
                ├ 줄이 깨짐 / 모르는 버전 / 주소·머리가 너무 김 ──→ 400 / 400 / 413 (②)
                └ HTTP/0.9 형식 ─────────────────────────────→ 400 (엣지 ⑦)
             → do_GET 등 함수가 없음 ─────────────────────────→ 405 (②)
             → do_POST
                ├ 주소가 /query가 아님 ────────────────────────→ 404 not_found
                ├ Content-Length 검사, chunked ────────────────→ 400 / 413 (엣지 ⑤)
                ├ 본문 읽기 (5초 넘으면 끊김) ──────────────────→ 408 timeout (엣지 ⑥)
                ├ _unwatch: 마감 끝 (여기부터는 시간을 안 셈)
                ├ JSON 풀기, sql 꺼내기 ───────────────────────→ 400 bad_request (③)
                ├ engine.execute 🔒
                │   ├ SQL이 틀림 (MiniDBError) ────────────────→ 400 bad_sql + results
                │   └ 파일 손상(StorageError)·그 밖의 예외 ─────→ 500 internal (④)
                └ 성공 ─────────────────────────────────────────→ 200 results
```

## 막지 못하는 것 (한계)

| 경우 | 왜 못 막나 |
| --- | --- |
| 연결 20개(스레드 4 + 큐 16칸)를 5초마다 계속 새로 여는 손님 | 연결 하나는 5초 안에 끊기지만, 계속 새로 열면 그동안 정상 손님은 503을 받습니다. 스레드 하나가 연결 하나를 맡는 구조 자체의 한계입니다 |
| 서버가 켜져 있을 때 CLI로 같은 `data/`에 INSERT | 두 프로그램은 lock을 따로 가져서 id가 겹칠 수 있습니다. 코드로 막지 않고 규칙으로 둡니다 ([D29](./DECISIONS.md#step3)) |
| 데이터 파일의 줄이 깨짐 | 400 `bad_sql`로 나갑니다 (④ 한계). Phase 1(8단계) |

## 확인 스크립트

서버를 직접 켜지 않아도, 스크립트가 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다. `data/users.tbl`은 건드리지 않습니다.

| 스크립트 | 무엇을 확인 |
| --- | --- |
| [`checks/check_errors.py`](../../checks/check_errors.py) | `server.py`만: 오류 모양(404·405·400·413), 깊은 JSON, 500(진짜 엔진 안의 디스크 오류 포함), 503을 끝까지 읽음, 큐가 꽉 찬 채로 끄기, 실행 옵션, 켜기 실패 메시지 |
| [`checks/check_guard.py`](../../checks/check_guard.py) | `server_guard.py`: `Content-Length` 깊은 검사, 1MB, chunked, HTTP/0.9, 408(아무것도 안 보냄·본문을 덜 보냄·머리를 덜 보냄), 천천히 보내는 연결이 스레드를 다 잡아도 정상 요청 처리, 받는 스레드가 안 묶임, 끄기 |

```bash
python3 checks/check_errors.py
python3 checks/check_guard.py
```
```
1. 오류 모양과 404 / 405 / 400 확인
통과  없는 주소 → 404 not_found
통과  GET /query → 405 method_not_allowed
통과  JSON 아님 → 400 bad_request
...
통과  아주 깊게 중첩된 JSON → 400 bad_request (끊기지 않음)

2. 예상 못 한 오류 → 500 internal
통과  엔진 예외 → 500 internal (내부 경로 노출 안 함)
통과  엔진 안의 디스크 오류 → 500 internal, 응답에 파일 경로 없음
통과  그 뒤 정상 INSERT → 200 (lock이 풀려 있음)
...
23/23 통과
```
```
1. Content-Length와 요청 형식 검사
통과  1MB 초과 요청 → 413 too_large
통과  Content-Length -1 → 400
...
2. 느린 요청 → 408 timeout (이 서버는 1초)
통과  아무것도 안 보낸 연결 → 408 timeout (1.0초)
통과  본문을 덜 보낸 연결 → 408 timeout (1.4초)
통과  헤더를 덜 보낸 연결 → 408 timeout (1.0초)
통과  천천히 보내는 연결 2개가 스레드 2개를 다 잡아도 정상 요청은 200 (0.6초)
...
17/17 통과
```
초 숫자는 컴퓨터마다 조금씩 다릅니다.

## 직접 확인해 보기

터미널 1:
```bash
python3 server.py
```

터미널 2 (한 줄씩):
```bash
curl -s -X GET  localhost:8000/query
curl -s -X POST localhost:8000/abc -d '{"sql": "SELECT * FROM users;"}'
curl -s -X POST localhost:8000/query -d 'not json'
curl -s -X POST localhost:8000/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('현지', 25); SELECT * FROM users WHERE email = 'x';\"}"
```
```
{"error": {"code": "method_not_allowed", "message": "GET는 받지 않습니다. POST /query 를 쓰세요"}}
{"error": {"code": "not_found", "message": "없는 주소입니다: /abc (POST /query 만 있습니다)"}}
{"error": {"code": "bad_request", "message": "본문을 읽을 수 없습니다: Expecting value: line 1 column 1 (char 0)"}}
{"error": {"code": "bad_sql", "message": "2번째 문장: 테이블 'users' 에 컬럼 'email' 이 없습니다"}, "results": [{"type": "insert", "id": 1}]}
```

터미널 1의 로그:
```
[worker-1] 127.0.0.1 - "GET /query HTTP/1.1" 405 -
[worker-2] 127.0.0.1 - "POST /abc HTTP/1.1" 404 -
[worker-3] 127.0.0.1 - "POST /query HTTP/1.1" 400 -
[worker-4] 127.0.0.1 - "POST /query HTTP/1.1" 400 -
```

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| `python3 checks/check_errors.py` | 23/23 통과 |
| `python3 checks/check_guard.py` | 17/17 통과 |
| `python3 checks/check_threadpool.py` | 6/6 그대로 |
| `python3 checks/check_concurrency.py` | lock 켬: 통과 그대로 |
| `python3 checks/check_all.py` | 11/11 그대로 |
| `python3 server.py --queue 0` | `1 이상이어야 합니다: 0`이 나오고 켜지지 않음 |

## 이 단계에서 정한 것

자세한 이유(무엇이 문제였나 → 무엇을 바꾸나 → 왜 이 방식인가)는 [결정 기록의 Phase 3(17단계) 절](./DECISIONS.md#step17)에 있습니다.

- **D38** 모든 오류를 `{"error": {"code", "message"}}` 한 모양으로. 서버가 내는 번호는 오류 목록의 것뿐입니다.
- **D39** 500일 때 자세한 내용은 서버 로그에만 남깁니다.
- **D42** 본문은 최대 1MB. `Content-Length`가 틀리면 400, 넘으면 413 (엣지 방어).
- **D43** 본문을 다 읽지 않고 답할 때(503, 413)는 보내기만 먼저 닫고, 남은 것을 잠깐 읽어 버린 뒤 닫습니다.
- **D44** 큐가 꽉 찬 채로 꺼도 1초 안에 꺼집니다.
- **D45** `--workers`, `--queue`는 1 이상만. 켜기에 실패하면 진짜 이유를 한 줄로 보여 줍니다.
- **D46** 답을 보내기 전에 클라이언트가 먼저 끊으면 조용히 넘어갑니다 (엣지 방어).
- **D47** 엔진은 `MiniDBError`(SQL 오류)만 문장 오류로 담고, `StorageError`와 나머지 예외는 위로 올립니다.
- **D48** 엣지 케이스 방어는 `server_guard.py`에 따로 두고, `python3 server.py`로 켜면 기본으로 켜집니다.
- **D37 (17단계에서 더함)** 받는 시간 전체 5초는 엣지 방어의 감시 스레드가 합니다.

## 만든 파일

| 파일 | 내용 |
| --- | --- |
| `server.py` (고침) | 오류 JSON 통일(`error_body`, `HTTP_ERRORS`, `send_error`), 깊은 JSON, 500, `linger_close`, 끄기·옵션·켜기 실패 수정. 맨 아래에서 `server_guard`를 켬 |
| `server_guard.py` (새로) | 엣지 케이스 방어 (`GuardedHandler`, `GuardedServer`, 감시 스레드) |
| `engine.py` | `execute`가 `MiniDBError`만 결과에 담고, `StorageError`와 그 밖의 예외는 올려 보냄 |
| `checks/check_errors.py` (새로) | `server.py`의 오류 응답 확인 25개 |
| `checks/check_guard.py` (새로) | `server_guard.py`의 엣지 방어 확인 17개 |
| `bench/load_test.py` (새로) | D35 숫자 근거 측정 ([STEP15 질문](./STEP15.md#발표-때-나올-질문)) |

## 다른 담당에게 영향

| 담당 | 영향 |
| --- | --- |
| Phase 1 | 없음. minidb의 `MiniDBError` 계층을 그대로 씁니다. 새 오류 종류를 만들 때 `MiniDBError` 아래에 두면 400, 그 밖이면 500으로 나갑니다 |
| Phase 2 | 없음 |
| 서버를 부르는 쪽 (주식 화면 등) | 응답 번호가 200이 아니면 `error.code`만 보면 됩니다. `busy`는 잠시 뒤 다시 보내기, `bad_sql`은 `results`에 이미 저장된 문장이 있음, `internal`은 관리자에게 알리기 |

## 발표 때 나올 질문

**Q. 오류를 왜 JSON 한 모양으로 맞추나요?**
받는 쪽 프로그램이 오류마다 HTML을 읽거나 따로 처리하지 않고, `error.code` 하나만 보고 "다시 보낼지(`busy`), 사용자에게 보여 줄지(`bad_sql`), 관리자에게 알릴지(`internal`)"를 정할 수 있게 하려는 것입니다.

**Q. 500일 때 왜 자세한 내용을 안 보내나요?**
오류 내용에는 파일 경로 같은 서버 내부 정보가 들어 있습니다. 밖에서 볼 필요가 없고, 보이면 공격에 쓰일 수 있습니다. 자세한 내용은 서버 터미널에 남아서 관리자는 볼 수 있습니다.

**Q. Thread Pool인데 감시 스레드를 또 만들면 안 되는 것 아닌가요?**
Pool이 막으려는 것은 "요청 수만큼 스레드가 늘어나는 것"입니다. 감시 스레드는 요청 수와 상관없이 서버 전체에 하나뿐이라, 스레드 수는 여전히 정해져 있습니다 (일하는 스레드 N개 + 감시 1개 + 받는 1개).

**Q. 엣지 방어를 왜 따로 파일로 뒀나요?**
`server.py`만 읽어도 과제의 핵심(Thread Pool, JSON 오류)이 보이게 하려는 것입니다. 방어 코드는 원리를 이해한 뒤에 따로 읽으면 됩니다. 실행은 `python3 server.py` 하나로 같고, 방어는 기본으로 켜집니다.

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `서버를 켤 수 없습니다 (포트 8000): ... Address already in use` | 8000번을 이미 쓰는 중. 이전 서버를 끄거나 `--port 8001` |
| `데이터 폴더를 열 수 없습니다` | 저장소 맨 위 폴더(`data/`가 있는 곳)에서 실행하기 |
| `413 too_large` | 본문이 1MB를 넘음. 대량 넣기는 CLI로 (`python -m minidb 파일.sql`, 서버는 끈 상태로) |
| `408 timeout` | 5초 안에 요청을 다 보내지 못함. 네트워크가 아주 느리거나 클라이언트가 멈춤 |
| `500 internal` | 서버 터미널에 트레이스백이 있음 |
| `400` + `Invalid control character` | curl의 `-d` 안에서 줄이 바뀜. 명령을 한 줄로 |
| 처음 보는 오류 `code` | 위 오류 목록에 없으면 버그입니다. 알려 주세요 |
