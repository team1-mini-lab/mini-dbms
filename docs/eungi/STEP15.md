# Phase 3(15단계): Thread Pool

> **한 줄 요약**: 서버가 요청을 하나씩만 처리하던 것을, 미리 만들어 둔 스레드 여러 개가 큐에서 요청을 꺼내 **동시에** 처리하게 바꿨습니다. 큐가 가득 차면 503으로 거절하고, 아무것도 안 보내는 연결은 5초 뒤 끊습니다.

Phase 3는 16단계(lock) → 15단계(Thread Pool) → 17단계(오류 응답) 순서로 합니다. lock은 [STEP16](./STEP16.md)에서 먼저 걸어 두었기 때문에, 스레드를 늘려도 id가 겹치지 않습니다.

## 왜 필요한가

과제 요구사항입니다.
> Thread Pool을 구성합니다. 요청이 들어올 때마다 스레드를 할당하여 SQL 요청을 병렬로 처리해야 합니다.

지도 만들기(3단계)의 서버는 파이썬 기본 `HTTPServer`라서 **요청을 하나씩 차례로** 처리했습니다. 요청 A를 다 처리하고 응답을 보낸 뒤에야 요청 B를 받습니다.

```
지금까지:  A [받기 → 읽기 → 실행 → 응답] → B [받기 → 읽기 → 실행 → 응답] → C ...
```

느린 클라이언트 하나가 요청을 천천히 보내면, 그동안 다른 요청은 전부 기다려야 했습니다.

## Thread Pool이 뭔가요?

**스레드**는 코드 안에서 일을 하는 실행 흐름 하나입니다. 스레드가 여러 개면 여러 일을 동시에 진행할 수 있습니다.

**Thread Pool**은 스레드를 **미리 정해진 수만큼 만들어 두고** 계속 다시 쓰는 방식입니다. 요청이 올 때마다 스레드를 새로 만들지 않습니다.

```
                ┌──────── 큐 (기다리는 요청, 최대 16개) ────────┐
받는 스레드 ──→ │  요청 E   요청 D   요청 C                      │ ──→ worker-1: 요청 A 처리 중
(연결을 받아   └─────────────────────────────────────────────┘ ──→ worker-2: 요청 B 처리 중
 큐에 넣기만 함)                                                   ──→ worker-3: (비어서 큐를 기다림)
                                                                  ──→ worker-4: (비어서 큐를 기다림)
```

| 누가 | 하는 일 |
| --- | --- |
| 받는 스레드 (1개) | 연결을 받아서 큐에 넣기만 하고 바로 다음 연결을 받음. 큐가 꽉 차 있으면 503을 보내고 닫음 |
| 큐 (`queue.Queue`) | 아직 처리하지 못한 요청이 줄을 서는 곳. 최대 칸 수가 정해져 있음 |
| 일하는 스레드 (`worker-1`\~`worker-4`) | 큐에서 요청을 하나 꺼내서 처리(요청 읽기 → `engine.execute` → 응답 쓰기)하고, 다시 큐로 돌아가 다음 요청을 꺼냄 |

## 왜 직접 만들었나요? ([D34](./DECISIONS.md#step15))

| 선택 | 문제 |
| --- | --- |
| 파이썬 `ThreadingHTTPServer` | 요청이 올 때마다 스레드를 **새로** 만듦. 수가 정해져 있지 않아서 Pool이 아님. 요청이 1만 개 몰리면 스레드도 1만 개 |
| 파이썬 `ThreadPoolExecutor` | Pool은 맞지만 안이 안 보여서, 발표에서 "큐와 스레드가 어떻게 동작하나"를 설명하기 어려움 |
| **`queue.Queue` + 스레드 N개 직접 (선택)** | 원리가 코드에 그대로 보임. 큐 크기를 정할 수 있어서 요청이 끝없이 쌓이지 않음 |

## 핵심 코드

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다. 아래 코드는 15단계를 마쳤을 때의 `server.py`입니다.

> 🔄 **17단계에서 바뀐 곳**: ① `__init__`(옵션 검사, 감시 스레드), ④ 503(답을 읽을 수 있게 `linger_close`로 닫기), ⑤ timeout(한 번 받을 때마다 5초 → 받는 시간 전체 5초 + `408 timeout`), ⑥ 서버 끄기(큐가 꽉 찬 채로도 1초 안에 종료). 자세한 내용은 [STEP17](./STEP17.md)에 있습니다.

### ① 서버 만들기: 큐와 스레드 준비 · [`server.py`](../../server.py)의 `PooledHTTPServer.__init__`

```python
class PooledHTTPServer(HTTPServer):
    request_queue_size = 128                  # 운영체제가 받아 두는 연결 수 (동시 요청이 많을 때 연결이 거절되지 않게)

    def __init__(self, address, handler, engine, workers=4, queue_size=16, request_timeout=5):
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # 요청 하나당 시간 제한
        super().__init__(address, handler)
        self.engine = engine                  # 모든 스레드가 같은 엔진 하나를 씀 (lock은 엔진 안에)
        self.jobs = queue.Queue(maxsize=queue_size)
        self.workers = [
            threading.Thread(target=self._work, name=f"worker-{n}", daemon=True)
            for n in range(1, workers + 1)
        ]
        for worker in self.workers:
            worker.start()
```

- `class PooledHTTPServer(HTTPServer)`: 파이썬 기본 `HTTPServer`를 **이어받아서** 필요한 부분만 바꿔 끼웁니다. 연결 받기, HTTP 해석 같은 나머지는 `HTTPServer`가 그대로 합니다.
- `queue.Queue(maxsize=16)`: 파이썬에 기본으로 있는 큐입니다. 여러 스레드가 동시에 넣고 꺼내도 안전하게 만들어져 있어서, 큐에는 lock을 따로 걸지 않아도 됩니다.
- `threading.Thread(target=self._work, ...)`: 스레드 하나를 만들고, 그 스레드가 `_work` 함수를 실행하게 합니다. `start()`를 부르는 순간 스레드가 실행을 시작합니다. 4개를 만들면 `_work`가 4개 동시에 돌아갑니다.
- `name=f"worker-{n}"`: 로그와 응답에 어느 스레드가 처리했는지 보이게 이름을 붙입니다.
- `daemon=True`: 서버가 꺼질 때 이 스레드들이 남아서 꺼지지 않는 일을 막습니다.
- `self.engine = engine`: 엔진을 서버 안에 저장해 두고, 모든 스레드가 이 엔진 하나를 같이 씁니다. 엔진 안에 lock이 있으니([STEP16](./STEP16.md)) 동시에 불러도 안전합니다.
- `type(handler.__name__, (handler,), {"timeout": ...})`: `Handler`를 이어받으면서 `timeout` 값만 바꾼 새 클래스를 만듭니다. 서버마다 timeout을 다르게 줄 수 있게 하려고 이렇게 했습니다 (확인 스크립트는 1초로 줄여서 씁니다).

### ② 연결이 오면: 큐에 넣기만 · [`server.py`](../../server.py)의 `process_request`

```python
    def process_request(self, request, client_address):
        """받는 스레드가 연결 하나를 받을 때마다 부름. 큐에 넣기만 한다."""
        try:
            self.jobs.put_nowait((request, client_address))   # 기다리지 않음. 꽉 차 있으면 바로 Full
        except queue.Full:
            self._reject_busy(request)
            self.shutdown_request(request)
```

- `HTTPServer`는 연결을 하나 받을 때마다 `process_request`를 부릅니다. 원래는 여기서 요청을 **바로 처리**했습니다. 그래서 하나씩만 처리됐습니다.
- 이 함수를 바꿔 끼워서, **처리하지 않고 큐에 넣기만** 하게 했습니다. 받는 스레드는 넣자마자 다음 연결을 받으러 갑니다.
- `put_nowait`: 큐가 꽉 차 있으면 기다리지 않고 바로 `queue.Full` 오류를 냅니다. 그러면 503을 보내고 연결을 닫습니다 (④).

### ③ 일하는 스레드: 꺼내서 처리하기를 반복 · [`server.py`](../../server.py)의 `_work`

```python
    def _work(self):
        """일하는 스레드 하나가 하는 일: 큐에서 꺼내 처리하기를 계속 반복한다."""
        while True:
            job = self.jobs.get()                 # 큐가 비어 있으면 일이 들어올 때까지 여기서 기다림
            if job is None:                       # 서버를 끌 때 넣는 "그만" 신호
                return
            request, client_address = job
            try:
                self.finish_request(request, client_address)   # Handler를 만들어 do_POST 등을 실행
            except Exception:
                self.handle_error(request, client_address)
            finally:
                self.shutdown_request(request)    # 연결 닫기
```

- 스레드 4개가 각자 이 `while True` 반복을 돌립니다.
- `self.jobs.get()`: 큐에서 하나 꺼냅니다. 비어 있으면 **들어올 때까지 이 줄에서 기다립니다.** 그래서 일이 없을 때 스레드가 헛돌지 않습니다.
- `finish_request`: `HTTPServer`가 원래 하던 처리입니다. `Handler`를 만들고, 요청을 읽어 `do_POST`를 실행하고, 응답을 씁니다. 이 안에서 `engine.execute`가 불립니다.
- `try / except / finally`: 요청 하나에서 오류가 나도 스레드가 죽지 않고 다음 요청을 처리하게 합니다. 연결은 어떤 경우에도 닫습니다.
- `None`을 꺼내면 반복을 끝냅니다. 서버를 끌 때 쓰는 신호입니다 (⑥).

### ④ 큐가 꽉 차면 503 · [`server.py`](../../server.py)의 `_reject_busy`

```python
BUSY_BODY = json.dumps(
    {"error": {"code": "busy", "message": "서버가 바쁩니다. 잠시 후 다시 보내 주세요"}}, ensure_ascii=False
).encode("utf-8")
BUSY_RESPONSE = (
    b"HTTP/1.1 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    + f"Content-Length: {len(BUSY_BODY)}\r\n".encode()
    + b"Connection: close\r\n\r\n"
    + BUSY_BODY
)

    def _reject_busy(self, request):
        try:
            request.sendall(BUSY_RESPONSE)
        except OSError:
            pass
```

- 503은 "서버가 바쁘다"는 응답 번호입니다 ([DESIGN 결정 15](../DESIGN.md#4-결정-참고사항)).
- 이 응답은 **받는 스레드**가 보냅니다. 받는 스레드가 요청을 읽거나 `Handler`를 만들면 그동안 다른 연결을 못 받으니까, 미리 만들어 둔 짧은 응답을 그대로 보내고 바로 닫습니다.
- 큐 크기를 정해 두는 이유: 크기가 없으면 요청이 몰릴 때 끝없이 쌓여서 메모리가 늘고, 맨 뒤 요청은 한참 뒤에 처리됩니다. 차라리 빨리 "바쁘다"고 알려 주는 게 낫습니다.

### ⑤ 느린 클라이언트 막기: 5초 timeout ([D37](./DECISIONS.md#step15))

```python
handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # ①에서 본 줄. 기본 5초
```

- 스레드가 4개뿐인데, 연결만 해 놓고 아무것도 안 보내는 클라이언트가 4개 있으면 **스레드 4개가 전부 그 연결을 기다리느라** 서버가 멈춥니다.
- `Handler.timeout`을 정해 두면, 파이썬 `http.server`가 그 시간 동안 아무것도 안 오는 연결을 끊고 스레드를 풀어 줍니다.

### ⑥ 서버 끄기 · [`server.py`](../../server.py)의 `server_close`

```python
    def server_close(self):
        super().server_close()
        for _ in self.workers:
            self.jobs.put(None)                   # 스레드마다 "그만" 신호 하나씩
        for worker in self.workers:
            worker.join(timeout=1)
```

- 스레드 4개는 `self.jobs.get()`에서 기다리고 있습니다. 큐에 `None`을 4개 넣으면 각자 하나씩 꺼내서 반복을 끝냅니다.
- `worker.join()`: 그 스레드가 끝날 때까지 기다립니다.

### ⑦ 어느 스레드가 처리했는지 보이기 · [`server.py`](../../server.py)의 `Handler`

```python
    def _send(self, status, obj):
        ...
        self.send_header("X-Worker", threading.current_thread().name)   # Phase 3(15단계): 어느 스레드가 처리했는지
        ...

    def log_message(self, format, *args):
        # Phase 3(15단계): 로그 앞에 처리한 스레드 이름을 붙임. 여러 스레드가 나눠 처리하는 것을 눈으로 확인
        print(f"[{threading.current_thread().name}] {self.address_string()} - {format % args}")
```

- `threading.current_thread().name`: 지금 이 코드를 실행하고 있는 스레드의 이름(`worker-2` 등)입니다.
- DESIGN 15단계 완료 기준이 "동시에 보낸 요청이 여러 스레드 이름으로 처리된 로그가 보임"이라서, 로그와 응답 헤더 두 곳에 남깁니다.

### ⑧ 실행 옵션 · [`server.py`](../../server.py)의 `main`

```python
def main():
    args = parse_arguments()
    engine = Engine("data")
    server = PooledHTTPServer(("localhost", args.port), Handler, engine, args.workers, args.queue)
    ...
```

| 옵션 | 기본값 | 쓰는 곳 |
| --- | --- | --- |
| `--port` | 8000 | mini-redis와 같은 곳에서 띄울 때 충돌을 피함 ([D36](./DECISIONS.md#step15)) |
| `--workers` | 4 | 스레드 수를 바꿔 가며 비교할 때 ([D35](./DECISIONS.md#step15)) |
| `--queue` | 16 | 503 시연 때 작게 줄임 |

지도 만들기(3단계)에서는 `engine = Engine("data")`가 파일 맨 위에 있어서 `server.py`를 `import`만 해도 엔진이 만들어졌습니다. 이제 `main()` 안에서 만들고 서버에 넘깁니다. 그래서 확인 스크립트가 임시 폴더로 서버를 따로 띄울 수 있습니다 ([D41](./DECISIONS.md#step15)).

## 요청 하나가 지나가는 길

```
① 받는 스레드: 연결 받음 → process_request → 큐에 넣음 → 바로 다음 연결을 받으러 감
② worker-2:  큐에서 꺼냄 → finish_request
                → Handler.do_POST: 요청 읽기, JSON에서 sql 꺼내기           (여러 스레드가 동시에)
                → self.server.engine.execute(sql)  🔒 한 번에 하나씩        (STEP16의 lock)
                → _send: 응답 쓰기 (X-Worker: worker-2)                    (여러 스레드가 동시에)
             → 연결 닫기 → 다시 큐에서 꺼내러 감
```

엔진 안(`execute`)은 lock 때문에 한 번에 하나씩이지만, 요청을 읽고 응답을 쓰는 부분은 여러 스레드가 동시에 합니다. 느린 클라이언트 하나가 다른 요청을 막지도 않습니다.

## 확인 스크립트 · [`checks/check_threadpool.py`](../../checks/check_threadpool.py)

서버를 직접 켜지 않아도, 스크립트가 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다.

| 확인 | 방법 |
| --- | --- |
| 여러 스레드가 나눠 처리 | 스레드 4개 서버에 INSERT 50개를 **동시에** 보내고, 응답의 `X-Worker`를 셈 |
| id가 안 겹침 | 50개 응답의 id가 1\~50인지 (STEP16의 lock이 서버에서도 동작하는지) |
| 큐가 차면 503 | 스레드 1개, 큐 1칸으로 줄이고, 아무것도 안 보내는 연결 두 개로 스레드와 큐를 채운 뒤 요청을 보냄 |
| timeout | 2.5초 기다리면 느린 연결 둘이 timeout(1초)으로 끊기고, 다음 요청은 200 |
| 끄기 | 서버를 끄면 일하는 스레드가 모두 멈춤 |

## 직접 확인해 보기

```bash
python3 checks/check_threadpool.py
```
```
1. 요청 50개를 동시에 보냄 (스레드 4개, 큐 64칸)
통과  50개 모두 200  ({200: 50})
통과  id 1~50이 빠짐없이, 겹치지 않음 (lock 덕분)
통과  여러 스레드가 나눠 처리함  (worker-1 14건, worker-2 12건, worker-3 12건, worker-4 12건)

2. 스레드 1개, 큐 1칸, timeout 1초로 줄여서 꽉 채움
통과  스레드와 큐가 꽉 차면 503  (503 busy)
통과  느린 연결이 timeout으로 끊긴 뒤 다시 처리됨  (200)
통과  서버를 끄면 일하는 스레드가 모두 멈춤

6/6 통과
```

**서버를 직접 켜서 로그 보기** (터미널 두 개)

터미널 1:
```bash
python3 server.py
```
```
http://localhost:8000 에서 POST /query 를 기다립니다 (스레드 4개, 큐 16칸)
```

터미널 2: 요청 6개를 동시에 보내기
```bash
for i in 1 2 3 4 5 6; do curl -s -X POST localhost:8000/query -d "{\"sql\": \"INSERT INTO users (name, age) VALUES ('u$i', $i);\"}" & done; wait
```

터미널 1에 찍히는 로그:
```
[worker-2] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
[worker-3] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
[worker-1] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
[worker-1] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
[worker-4] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
[worker-2] 127.0.0.1 - "POST /query HTTP/1.1" 200 -
```
여러 스레드 이름이 섞여 나오면 Thread Pool이 동작하는 것입니다 (DESIGN 15단계 완료 기준). 끌 때는 터미널 1에서 `Ctrl + C`를 누르면 "서버를 끕니다"가 나오고 꺼집니다.

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| `python3 checks/check_threadpool.py` | 6/6 통과 |
| `python3 checks/check_concurrency.py` | lock 켬: 통과 (STEP16 그대로) |
| `python3 checks/check_all.py` | 11/11 그대로 |
| `python3 server.py --help` | `--port`, `--workers`, `--queue` 설명이 나옴 |
| `curl -i -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users;"}'` | 응답 머리에 `X-Worker: worker-n`이 보임 |

## 이 단계에서 정한 것

자세한 이유는 [결정 기록의 Phase 3(15단계) 절](./DECISIONS.md#step15)에 있습니다.

- **D34** `queue.Queue` + 미리 만든 스레드 N개를 직접 만듭니다. 큐가 가득 차면 503입니다.
- **D35** 기본 스레드 4개, 큐 16칸. `--workers`, `--queue`로 바꿀 수 있습니다.
- **D36** `--port`로 포트를 바꿀 수 있습니다. 기본 8000입니다.
- **D37** 요청 하나당 5초 timeout입니다.
- **D40** 처리한 스레드 이름을 로그 앞과 응답 머리(`X-Worker`)에 남깁니다.
- **D41** 엔진은 `main()`에서 만들어 서버에 넘기고, `Handler`는 `self.server.engine`으로 씁니다.

## 만든 파일

| 파일 | 내용 |
| --- | --- |
| `server.py` (고침) | `PooledHTTPServer` 추가, `Handler`는 `self.server.engine` 사용, `X-Worker`와 스레드 이름 로그, `main()`과 실행 옵션. `do_POST`의 요청 처리 내용은 그대로 |
| `checks/check_threadpool.py` (새로) | 동시 요청, 503, timeout, 끄기 확인 |

## 다른 담당에게 영향

| 담당 | 영향 |
| --- | --- |
| Phase 1, 2 | 없음. 엔진은 여전히 `engine.execute`로만 불리고, lock이 지켜 줍니다 |
| 서버를 켜는 사람 | 전과 똑같이 `python3 server.py`. 옵션은 선택입니다 |

## 발표 때 나올 질문

**Q. 엔진에 lock이 있어서 한 번에 하나씩만 실행되는데, Thread Pool이 무슨 의미가 있나요?**
요청을 읽고(HTTP, JSON) 응답을 쓰는 부분은 여러 스레드가 동시에 합니다. 줄을 서는 건 `execute` 안뿐입니다. 느린 클라이언트 하나가 다른 요청을 막지도 않습니다 (위 확인 2번). SELECT끼리도 동시에 하게 만드는 것은 차별화(21단계) 읽기/쓰기 lock입니다.

**Q. 스레드를 요청마다 새로 만들면 안 되나요?**
만드는 비용이 매번 들고, 요청이 몰리면 스레드가 끝없이 늘어 메모리가 바닥납니다. Pool은 수를 정해 두고 다시 쓰며, 넘치는 요청은 큐에서 기다리거나 503으로 거절합니다.

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `Address already in use` | 8000번을 이미 쓰는 중. 이전 서버를 끄거나 `python3 server.py --port 8001` |
| 로그에 `worker-1`만 나옴 | 요청을 하나씩 보낸 것. 위처럼 `&`로 동시에 보내기 |
| 503이 자주 나옴 | 동시 요청이 큐보다 많음. `--queue`나 `--workers`를 늘리기 |
| `Request timed out` 로그 | 5초 동안 아무것도 안 보낸 연결을 끊은 것. 정상 동작 |
