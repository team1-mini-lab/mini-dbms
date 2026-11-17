# Phase 3(15단계): Thread Pool

[threadpool_simulator.html](https://github.com/user-attachments/files/34967023/threadpool_simulator.html)

> **한 문장으로**: Thread Pool은 서버를 켤 때 일하는 스레드를 정해진 수만큼 **미리** 만들어 두고, 들어온 요청을 큐에 줄 세워 두면 쉬고 있는 스레드가 하나씩 꺼내 처리하는 방식입니다.
>
> | | |
> | --- | --- |
> | **무엇이 왜 문제였나** | 3단계 서버는 요청을 하나 끝까지 처리해야 다음 연결을 받았습니다. 그래서 한 번에 1개만 처리되고, 한 명이 느리면 뒤에 온 사람은 모두 기다렸습니다. 과제는 "Thread Pool로 병렬 처리"를 요구합니다 |
> | **무엇을 만들었나** | `queue.Queue(16칸)` + 미리 만든 스레드 4개. 받는 스레드는 연결을 큐에 넣기만 하고, 일하는 스레드가 꺼내 처리합니다. 큐까지 꽉 차면 기다리게 하지 않고 바로 503 |
> | **무엇과 비교해 골랐나** | 요청마다 스레드를 새로 만드는 `ThreadingHTTPServer`(Pool이 아님), 파이썬 `ThreadPoolExecutor`(큐에 상한이 없음)와 비교해서 직접 만들기를 골랐습니다 ([아래 비교](#왜-직접-만들었나요-d34)) |

Phase 3는 16단계(lock) → 15단계(Thread Pool) → 17단계(오류 응답) 순서로 합니다. lock은 [STEP16](./STEP16.md)에서 먼저 걸어 두었기 때문에, 스레드를 늘려도 id가 겹치지 않습니다.

## 왜 필요한가

과제 요구사항입니다.
> Thread Pool을 구성합니다. 요청이 들어올 때마다 스레드를 할당하여 SQL 요청을 병렬로 처리해야 합니다.

지도 만들기(3단계)의 서버는 파이썬 기본 `HTTPServer`를 그대로 썼습니다. 3단계의 목표는 "CLI → 엔진 → 파일 → 서버가 처음부터 끝까지 한 번 돌아가게"였고, 동시 처리는 이 15단계의 몫으로 남겨 두었기 때문입니다 ([DESIGN 3절](../DESIGN.md#3-개발-순서)).

`HTTPServer`는 연결을 하나 받을 때마다 아래 함수를 부릅니다. 파이썬 안에 원래 들어 있는 코드입니다 (`socketserver.py`).

```python
def process_request(self, request, client_address):
    self.finish_request(request, client_address)   # 요청을 끝까지 처리 (읽기 → 실행 → 응답)
    self.shutdown_request(request)                 # 연결 닫기
```

이 함수가 끝나야 다음 연결을 받습니다. 그래서 요청이 **하나씩 차례로** 처리됩니다.

```
지금까지:  A [받기 → 읽기 → 실행 → 응답] → B [받기 → 읽기 → 실행 → 응답] → C ...
```

느린 클라이언트 하나가 요청을 천천히 보내면, 그동안 다른 요청은 전부 기다려야 했습니다.

## Thread Pool이 뭔가요?

**스레드**는 프로그램 안에서 일을 하는 실행 흐름 하나입니다. 스레드가 여러 개면 여러 일을 동시에 진행할 수 있습니다.

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
| 받는 스레드 (1개) | `serve_forever`를 돌리는 스레드. 연결을 받아서 큐에 넣기만 하고 바로 다음 연결을 받음. 큐가 꽉 차 있으면 503을 보내고 닫음 |
| 큐 (`queue.Queue`) | 아직 처리하지 못한 요청이 줄을 서는 곳. 최대 칸 수가 정해져 있음 |
| 일하는 스레드 (`worker-1`\~`worker-4`) | 큐에서 요청을 하나 꺼내서 처리(요청 읽기 → `engine.execute` → 응답 쓰기)하고, 다시 큐로 돌아가 다음 요청을 꺼냄 |

`serve_forever`도 우리 코드가 아니라 파이썬 `socketserver.BaseServer`에 있는 함수입니다. 안에서 "새 연결이 오면 받아서 `process_request`를 부른다"를 서버가 꺼질 때까지 반복합니다.

```
socketserver.BaseServer      ← serve_forever (연결을 기다렸다 받는 반복)
  └ socketserver.TCPServer
      └ http.server.HTTPServer
          └ PooledHTTPServer  ← 우리가 만든 것. process_request를 바꿔 끼움
```

## 왜 직접 만들었나요? ([D34](./DECISIONS.md#step15))

세 가지를 비교했습니다. 숫자는 교차 검토에서 같은 서버를 세 가지로 만들어 돌려 본 결과입니다.

| 기준 | 파이썬 `ThreadingHTTPServer` | 파이썬 `ThreadPoolExecutor` | **`queue.Queue` + 스레드 N개 직접 (고름)** |
| --- | --- | --- | --- |
| 스레드 수 | 요청마다 **새로** 만듦. 1만 개가 몰리면 스레드도 1만 개 | 정해진 N개 | 정해진 N개 |
| Pool인가 | 아님 | 맞음 | 맞음 |
| 줄(큐)의 상한 | 줄이 없음 | 안쪽 줄에 **상한이 없음**. 503을 내려면 칸 수를 세는 장치(세마포어)를 따로 붙여야 함 | `Queue(maxsize=16)`. 상한이 곧 503 기준 |
| 손님 1000명이 한꺼번에 오면 | (해 보지 않음) | 요청이 964개까지 쌓이고 386명이 시간 초과로 실패 | 16칸이 차면 바로 503. 쌓이지 않음 |
| 코드 양 (Pool 부분) | 0줄 (상속만) | 약 절반 | 기준 |
| 원리가 코드에 보이나 | 안 보임 | `submit()` 한 줄 뒤에 숨음 | 보임. `_work`의 `while True: self.jobs.get()` 반복이 곧 Pool |

**골랐기 때문에 치르는 대가**: 서버 끄기, 오류 처리, 먼저 끊긴 연결 같은 것을 우리가 직접 다뤄야 합니다. 17단계에서 고친 `server_close`가 그 예입니다.

## 핵심 코드

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다. 아래 코드는 지금 [`server.py`](../../server.py)와 주석까지 똑같습니다. 17단계에서 더한 줄에는 주석에 `Phase 3(17단계)`가 붙어 있습니다.

### ① 서버 만들기: 큐와 스레드 준비 · `PooledHTTPServer.__init__`

```python
class PooledHTTPServer(HTTPServer):
    """Phase 3(15단계): 요청을 큐에 넣고, 미리 만든 스레드 N개가 꺼내서 처리하는 서버.

    받는 스레드(serve_forever를 돌리는 스레드)는 연결을 받아 큐에 넣기만 하고 바로 다음 연결을 받는다.
    실제 처리(요청 읽기 → engine.execute → 응답 쓰기)는 일하는 스레드들이 한다.
    """

    request_queue_size = 128                  # 운영체제가 받아 두는 연결 수 (동시 요청이 많을 때 연결이 거절되지 않게)

    def __init__(self, address, handler, engine, workers=4, queue_size=16, request_timeout=5):
        # Phase 3(17단계): 포트가 이미 쓰이면 super().__init__ 안에서 server_close()가 불린다.
        # 그때 server_close가 쓰는 것(jobs, workers)이 없으면 진짜 이유가 AttributeError에 가려지므로 먼저 만든다
        self.engine = engine                  # 모든 스레드가 같은 엔진 하나를 씀 (lock은 엔진 안에)
        self.request_timeout = request_timeout
        self.jobs = queue.Queue(maxsize=queue_size)
        self.workers = []
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # 한 번 받을 때 기다리는 최대 시간
        super().__init__(address, handler)
        self.workers = [
            threading.Thread(target=self._work, name=f"worker-{n}", daemon=True)
            for n in range(1, workers + 1)
        ]
        for worker in self.workers:
            worker.start()
```

- `class PooledHTTPServer(HTTPServer)`: 파이썬 기본 `HTTPServer`를 **이어받아서** 필요한 부분만 바꿔 끼웁니다. 연결 받기, HTTP 해석 같은 나머지는 `HTTPServer`가 그대로 합니다.
- `queue.Queue(maxsize=16)`: 파이썬에 기본으로 있는 큐입니다. 먼저 넣은 것을 먼저 꺼냅니다. **안에 lock이 들어 있어서** 받는 스레드가 넣고 일하는 스레드 4개가 동시에 꺼내도, 같은 요청을 두 번 꺼내거나 하나를 잃어버리지 않습니다. 그래서 큐에는 lock을 따로 걸지 않습니다.
- `threading.Thread(target=self._work, ...)`: 스레드 하나를 만들고, 그 스레드가 `_work` 함수를 실행하게 합니다. `start()`를 부르는 순간 실행을 시작합니다. 4개를 만들면 `_work`가 4개 동시에 돌아갑니다.
- `name=f"worker-{n}"`: 로그와 응답에 어느 스레드가 처리했는지 보이게 이름을 붙입니다 (⑦).
- `daemon=True`: 서버가 꺼질 때 이 스레드들이 남아서 프로그램이 안 꺼지는 일을 막습니다.
- `self.engine = engine`: 모든 스레드가 이 엔진 **하나**를 같이 씁니다. 엔진 안에 lock이 하나 있으니([STEP16](./STEP16.md)) 동시에 불러도 안전합니다.
- `type(handler.__name__, (handler,), {"timeout": ...})`: `Handler`를 이어받으면서 `timeout` 값만 바꾼 새 클래스를 만듭니다. 서버마다 timeout을 다르게 줄 수 있게 하려고 이렇게 했습니다 (확인 스크립트는 1초로 줄여서 씁니다). 뜻은 ⑤에 있습니다.
- `super().__init__`보다 위에 `self.jobs`, `self.workers = []`를 먼저 만든 이유는 주석 그대로입니다 (17단계에서 고침).

### ② 연결이 오면: 큐에 넣기만 · `process_request`

```python
    def process_request(self, request, client_address):
        """받는 스레드가 연결 하나를 받을 때마다 부름. 큐에 넣기만 한다."""
        try:
            self.jobs.put_nowait((request, client_address))   # 기다리지 않음. 꽉 차 있으면 바로 Full
        except queue.Full:
            self._reject_busy(request)
            self.shutdown_request(request)
```

- 원래 `process_request`는 여기서 요청을 **끝까지 처리**했습니다 ([위 원본 코드](#왜-필요한가)). 이 함수를 바꿔 끼워서, **처리하지 않고 큐에 넣기만** 하게 했습니다. 받는 스레드는 넣자마자 다음 연결을 받으러 갑니다. 이것이 15단계에서 가장 중요한 변화입니다.
- `put_nowait`: 큐가 꽉 차 있으면 기다리지 않고 바로 `queue.Full` 오류를 냅니다. 그냥 `put`을 쓰면 받는 스레드가 빈칸을 기다리며 멈추고, 그동안 아무도 연결을 받지 못합니다. 그러면 원래 `HTTPServer`와 같아집니다.

### ③ 일하는 스레드: 꺼내서 처리하기를 반복 · `_work`

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

- 스레드 4개가 각자 이 `while True` 반복을 돌립니다. **이 반복이 곧 Thread Pool입니다.**
- `self.jobs.get()`: 큐에서 하나 꺼냅니다. 비어 있으면 **들어올 때까지 이 줄에서 잠들어 기다립니다.** 잠든 스레드는 CPU를 쓰지 않고, 누가 `put`하면 큐가 하나를 깨웁니다.
- 어느 스레드가 몇 건을 맡을지는 우리가 정하지 않습니다. 먼저 깨어난(먼저 일이 끝난) 스레드가 가져갑니다. 그래서 결과가 14/12/12/12처럼 대략 고르게 나옵니다.
- `finish_request`: `HTTPServer`가 원래 하던 처리입니다. `Handler`를 만들고, 요청을 읽어 `do_POST`를 실행하고, 응답을 씁니다. 이 안에서 `engine.execute`가 불립니다.
- `try / except / finally`: 요청 하나에서 오류가 나도 스레드가 죽지 않고 다음 요청을 처리하게 합니다. 연결은 어떤 경우에도 닫습니다.

### ④ 큐가 꽉 차면 503 · `_reject_busy`, `linger_close`

```python
BUSY_BODY = json.dumps(
    error_body("busy", "서버가 바쁩니다. 잠시 후 다시 보내 주세요"), ensure_ascii=False
).encode("utf-8")
BUSY_RESPONSE = (                             # 503은 받는 스레드가 Handler 없이 바로 보내므로 미리 만들어 둠
    b"HTTP/1.0 503 Service Unavailable\r\n"
    b"Content-Type: application/json; charset=utf-8\r\n"
    + f"Content-Length: {len(BUSY_BODY)}\r\n".encode()
    + b"Connection: close\r\n\r\n"
    + BUSY_BODY
)
```

```python
    def _reject_busy(self, request):
        """큐가 꽉 찼을 때: 503 JSON을 보내고, 클라이언트가 읽을 수 있게 닫는다."""
        try:
            request.sendall(BUSY_RESPONSE)
        except OSError:
            return
        linger_close(request)
```

- 503은 HTTP 표준의 응답 번호로 "지금은 처리할 수 없음(서버가 바쁨)"이라는 뜻입니다 ([DESIGN 결정 15](../DESIGN.md#4-결정-참고사항)). `"busy"`는 우리가 정한 오류 이름입니다 ([STEP17](./STEP17.md)).
- 이 응답은 **받는 스레드**가 보냅니다. 받는 스레드가 요청을 읽거나 `Handler`를 만들면 그동안 다른 연결을 못 받으니까, 미리 만들어 둔 짧은 응답을 그대로 보냅니다.
- 큐 크기를 정해 두는 이유: 크기가 없으면 요청이 몰릴 때 끝없이 쌓여서 메모리가 늘고, 맨 뒤 요청은 한참 뒤에 처리됩니다. 차라리 빨리 "바쁘다"고 알려 주는 게 낫습니다.

`linger_close`는 17단계 교차 검토에서 더한 함수입니다.

```python
def linger_close(sock, timeout=0.2, idle=0.02):
    """Phase 3(15·17단계): 답을 보낸 뒤 '보내기'만 먼저 닫고, 클라이언트가 보내던 요청을 잠깐 읽어 버린다.

    요청을 읽지 않은 채 바로 닫으면 운영체제가 연결을 강제로 끊어서(RST) 클라이언트가 503을 못 읽을 수 있다.
    최대 timeout초까지 읽되, idle초 동안 아무것도 안 오면 바로 끝낸다 (받는 스레드를 오래 붙잡지 않게).
    """
    try:
        sock.shutdown(socket.SHUT_WR)             # "답은 다 보냈다"고 알림
    except OSError:
        return
    try:
        sock.settimeout(idle)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not sock.recv(65536):              # 클라이언트가 닫으면 끝
                break
    except OSError:                               # idle초 동안 아무것도 안 옴(timeout)도 여기로
        pass
```

- 503을 보낼 때 받는 스레드는 클라이언트의 요청을 **읽지 않았습니다.** 읽지 않은 데이터가 남은 채로 연결을 닫으면, 운영체제는 정상 종료 대신 **강제 종료 신호(RST)** 를 보냅니다. 그러면 클라이언트는 이미 도착한 503도 읽지 못하고 "연결이 끊겼다" 오류를 받습니다. 교차 검토에서 503 확인을 2000번 반복했더니 522번 이랬습니다.
- `shutdown(SHUT_WR)`: 연결의 **보내기 쪽만** 닫습니다. "답은 다 보냈다"는 뜻입니다. 받기 쪽은 열려 있어서, 클라이언트가 보내던 나머지를 읽어 버릴 수 있습니다.
- 최대 0.2초까지 읽어 버리고 닫습니다. 0.02초 동안 아무것도 안 오면(아무것도 안 보내는 연결) 바로 닫습니다. 그래야 받는 스레드가 오래 묶이지 않습니다. 이 0.02초가 없을 때는 아무것도 안 보내는 연결 60개가 있으면 다음 손님이 503을 받기까지 11.4초가 걸렸습니다.

### ⑤ 한 번 받을 때 기다리는 시간: 5초 ([D37](./DECISIONS.md#step15))

```python
        handler = type(handler.__name__, (handler,), {"timeout": request_timeout})   # 한 번 받을 때 기다리는 최대 시간
```

- 스레드가 4개뿐인데, 연결만 해 놓고 아무것도 안 보내는 클라이언트가 4개 있으면 **스레드 4개가 전부 그 연결을 기다리느라** 서버가 멈춥니다.
- `Handler.timeout`을 정해 두면, 파이썬 `http.server`가 **한 번 받을 때** 5초 동안 아무것도 안 오는 연결을 끊고 스레드를 풀어 줍니다.
- **한계**: "한 번 받을 때마다" 5초라서, 4초마다 한 글자씩 계속 보내는 연결은 끊기지 않습니다. 이것까지 막는 "받는 시간 **전체**에 5초"는 엣지 케이스 방어(`server_guard.py`)에 있습니다 ([STEP17](./STEP17.md#엣지-케이스-방어--server_guardpy)). `python3 server.py`로 켜면 그 방어까지 켜집니다.

### ⑥ 서버 끄기 · `server_close`

```python
    def server_close(self):
        super().server_close()
        while True:                               # Phase 3(17단계): 아직 못 꺼낸 연결은 닫고 버려서 "그만" 신호 자리를 만듦
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            if job is not None:
                self.shutdown_request(job[0])
        for _ in self.workers:
            try:
                self.jobs.put_nowait(None)        # 스레드마다 "그만" 신호 하나씩
            except queue.Full:
                break
        for worker in self.workers:
            worker.join(timeout=1)
```

- 스레드 4개는 `self.jobs.get()`에서 기다리고 있습니다. 큐에 `None`을 4개 넣으면 각자 하나씩 꺼내서 반복을 끝냅니다 (③).
- 17단계에서 앞의 `while` 반복을 더했습니다. 전에는 큐가 꽉 찬 채로 `Ctrl + C`를 누르면 `None`을 넣을 빈칸이 없어서, 15초가 지나도 서버가 꺼지지 않았습니다. 이제 아직 못 꺼낸 연결을 먼저 닫고 버려서 자리를 만듭니다.
- `worker.join(timeout=1)`: 그 스레드가 끝날 때까지 최대 1초 기다립니다.

### ⑦ 어느 스레드가 처리했는지 보이기 · `Handler._send`, `Handler.log_message` ([D40](./DECISIONS.md#step15))

```python
        self.send_header("X-Worker", threading.current_thread().name)   # Phase 3(15단계): 어느 스레드가 처리했는지
```

```python
    def log_message(self, format, *args):
        # Phase 3(15단계): 로그 앞에 처리한 스레드 이름을 붙임. 여러 스레드가 나눠 처리하는 것을 눈으로 확인
        print(f"[{threading.current_thread().name}] {self.address_string()} - {format % args}")
```

- `threading.current_thread().name`: 지금 이 코드를 실행하고 있는 스레드의 이름(`worker-2` 등)입니다.
- DESIGN 15단계 완료 기준이 "동시에 보낸 요청이 여러 스레드 이름으로 처리된 로그가 보임"이라서 로그에 남깁니다. 응답 머리(`X-Worker`)에도 남기면 확인 스크립트가 스레드마다 몇 건씩 처리했는지 셀 수 있습니다.

### ⑧ 서버 켜기와 실행 옵션 · `main`, `parse_arguments` ([D35](./DECISIONS.md#step15), [D36](./DECISIONS.md#step15), [D41](./DECISIONS.md#step15))

```python
def main(server_class=PooledHTTPServer, handler_class=Handler):
    args = parse_arguments()
    try:
        engine = Engine("data")
    except OSError as e:                      # Phase 3(17단계): data/ 폴더가 없는 곳에서 켠 경우
        sys.exit(f"데이터 폴더를 열 수 없습니다 (저장소 맨 위 폴더에서 실행하세요): {e}")
    try:
        server = server_class((args.host, args.port), handler_class, engine, args.workers, args.queue)
    except (OSError, OverflowError) as e:     # Phase 3(17단계): 포트가 이미 쓰임, 없는 포트 번호 등
        sys.exit(f"서버를 켤 수 없습니다 (포트 {args.port}): {e}")
```

```python
if __name__ == "__main__":
    import server_guard                      # 기본으로 엣지 케이스 방어(server_guard.py)를 켠 서버를 띄움
    server_guard.main()
```

| 옵션 | 기본값 | 쓰는 곳 |
| --- | --- | --- |
| `--host` | `localhost` | 받을 주소. 내 컴퓨터에서만 받으려면 기본값, Render 같은 곳에 배포할 때는 `0.0.0.0` (바깥에서 오는 요청도 받음) |
| `--port` | 8000 | mini-redis 데모와 같은 컴퓨터에서 띄울 때 포트가 겹치지 않게 ([D36](./DECISIONS.md#step15)). `0`이면 운영체제가 빈 포트를 골라 주고, 켤 때 실제 포트가 찍힘 |
| `--workers` | 4 | 일하는 스레드 수. 1 이상만 ([D35](./DECISIONS.md#step15)) |
| `--queue` | 16 | 큐 칸 수. 1 이상만. 503 시연 때 작게 줄임. `0`은 막음: 파이썬에서 `Queue(0)`은 "크기 제한 없음"이라 503이 사라짐 |

- 지도 만들기(3단계)에서는 `engine = Engine("data")`가 파일 맨 위에 있어서 `server.py`를 `import`만 해도 엔진이 만들어졌습니다. 이제 `main()` 안에서 만들고 서버에 넘깁니다. 그래서 확인 스크립트가 임시 폴더로 서버를 따로 띄울 수 있습니다 ([D41](./DECISIONS.md#step15)).
- `main`이 서버 클래스를 받게 해 둔 이유: `python3 server.py`로 켜면 맨 아래 두 줄이 `server_guard.main()`을 부르고, 그 안에서 `main(GuardedServer, GuardedHandler)`로 **엣지 케이스 방어가 붙은 서버**를 띄웁니다 ([STEP17](./STEP17.md)). 원리는 이 파일에 있고, 방어는 그 파일에 따로 있습니다.

## 요청 하나가 지나가는 길

```
① 받는 스레드: 연결 받음 → process_request → 큐에 넣음 → 바로 다음 연결을 받으러 감
                                    └ 큐가 꽉 참 → 503 busy → linger_close로 닫음
② worker-2:  큐에서 꺼냄 → finish_request
                → Handler.do_POST: 요청 읽기, JSON에서 sql 꺼내기           (여러 스레드가 동시에)
                → self.server.engine.execute(sql)  🔒 한 번에 하나씩        (STEP16의 lock)
                → _send: 응답 쓰기 (X-Worker: worker-2)                    (여러 스레드가 동시에)
             → 연결 닫기 → 다시 큐에서 꺼내러 감
```

엔진 안(`execute`)은 lock 때문에 한 번에 하나씩이지만, 요청을 읽고 응답을 쓰는 부분은 여러 스레드가 동시에 합니다. 한 스레드가 느린 클라이언트의 요청을 기다리는 동안, 다른 스레드는 다른 요청을 처리합니다.

## 확인 스크립트 · [`checks/check_threadpool.py`](../../checks/check_threadpool.py)

서버를 직접 켜지 않아도, 스크립트가 임시 폴더와 빈 포트로 서버를 잠깐 띄웠다가 끕니다. `server.py`의 `PooledHTTPServer`(방어 없는 핵심)만 씁니다.

| 확인 | 방법 |
| --- | --- |
| 여러 스레드가 나눠 처리 | 스레드 4개 서버에 INSERT 50개를 **동시에** 보내고, 응답의 `X-Worker`를 셈 |
| id가 안 겹침 | 50개 응답의 id가 1\~50인지 (STEP16의 lock이 서버에서도 동작하는지) |
| 큐가 차면 503 | 스레드 1개, 큐 1칸으로 줄이고, 아무것도 안 보내는 연결 두 개로 스레드와 큐를 채운 뒤 요청을 보냄 |
| timeout | 2.5초 기다리면 아무것도 안 보내던 연결 둘이 timeout(1초)으로 끊기고, 다음 요청은 200 |
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
스레드별 건수는 실행할 때마다 조금씩 다릅니다.

**서버를 직접 켜서 로그 보기** (터미널 두 개)

터미널 1:
```bash
python3 server.py
```
```
http://localhost:8000 에서 POST /query 를 기다립니다 (스레드 4개, 큐 16칸)
```

터미널 2: 요청 6개를 동시에 보내기. **한 줄로** 붙여 넣으세요. `-d` 뒤의 따옴표 안에서 줄이 바뀌면 JSON 안에 줄바꿈 글자가 들어가서 400이 나옵니다.
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
여러 스레드 이름이 섞여 나오면 Thread Pool이 동작하는 것입니다 (DESIGN 15단계 완료 기준). 같은 이름이 여러 번 나와도 정상입니다. 끌 때는 터미널 1에서 `Ctrl + C`를 누르면 "서버를 끕니다"가 나오고 꺼집니다.

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| `python3 checks/check_threadpool.py` | 6/6 통과 |
| `python3 checks/check_concurrency.py` | lock 켬: 통과 (STEP16 그대로) |
| `python3 checks/check_all.py` | 11/11 그대로 |
| `python3 server.py --help` | `--port`, `--workers`, `--queue` 설명이 나옴 |
| `curl -i -X POST localhost:8000/query -d '{"sql": "SELECT * FROM users;"}'` | 응답 머리에 `X-Worker: worker-n`이 보임 |

## 이 단계에서 정한 것

자세한 이유(무엇이 문제였나 → 무엇을 바꾸나 → 왜 이 방식인가)는 [결정 기록의 Phase 3(15단계) 절](./DECISIONS.md#step15)에 있습니다.

- **D34** `queue.Queue` + 미리 만든 스레드 N개를 직접 만듭니다. 큐가 가득 차면 503입니다.
- **D35** 기본 스레드 4개, 큐 16칸. `--workers`, `--queue`로 바꿀 수 있습니다.
- **D36** `--port`로 포트를 바꿀 수 있습니다. 기본 8000입니다.
- **D37** 한 번 받을 때 5초까지 기다립니다. 받는 시간 전체 5초는 17단계 엣지 케이스 방어에서 합니다.
- **D40** 처리한 스레드 이름을 로그 앞과 응답 머리(`X-Worker`)에 남깁니다.
- **D41** 엔진은 `main()`에서 만들어 서버에 넘기고, `Handler`는 `self.server.engine`으로 씁니다.

## 만든 파일

| 파일 | 내용 |
| --- | --- |
| `server.py` (고침) | `PooledHTTPServer` 추가, `Handler`는 `self.server.engine` 사용, `X-Worker`와 스레드 이름 로그, `main()`과 실행 옵션 |
| `checks/check_threadpool.py` (새로) | 동시 요청, 503, timeout, 끄기 확인 |
| `bench/load_test.py` (17단계에 새로) | D35 숫자 근거를 재는 스크립트 (아래 질문 참고) |

## 다른 담당에게 영향

| 담당 | 영향 |
| --- | --- |
| Phase 1, 2 | 없음. 엔진은 여전히 `engine.execute`로만 불리고, lock이 지켜 줍니다 |
| 서버를 켜는 사람 | 전과 똑같이 `python3 server.py`. 옵션은 선택입니다 |

## 발표 때 나올 질문

**Q. 엔진에 lock이 있어서 한 번에 하나씩만 실행되는데, Thread Pool이 무슨 의미가 있나요?**
요청 하나를 처리하는 시간 중 lock 안에 있는 건 `execute`뿐입니다. 요청을 받고(네트워크), JSON을 풀고, 응답을 보내는 부분은 lock 밖이라 여러 스레드가 동시에 합니다. 특히 한 스레드가 느린 클라이언트의 요청을 기다리는 동안 다른 스레드가 다른 요청을 처리할 수 있습니다. 스레드는 동시성을, lock은 정확성을 맡습니다.

**Q. 왜 기본 스레드가 4개인가요?** ([D35](./DECISIONS.md#step15))
[`bench/load_test.py`](../../bench/load_test.py)로 재 봤습니다. 느린 손님(1초 동안 본문을 안 보냄) K명과 빠른 손님 60명을 섞어 보내고, 빠른 손님의 응답 시간을 봤습니다.

| 느린 손님 | 스레드 | 빠른 손님 응답 (중앙값) |
| --- | --- | --- |
| 3 | 4 | 0.7ms |
| 4 | 4 | 664ms |
| 4 | 8 | 0.5ms |

스레드 수가 동시에 오는 느린 연결 수보다 **많으면** 빠른 손님은 막히지 않고, 같거나 적으면 막힙니다. 기본 4개는 "동시에 느린 연결 3개까지 견딘다"는 뜻입니다. 빠른 손님만 있을 때는 스레드를 늘려도 빨라지지 않았습니다(스레드 1·4·16개 = 44·70·68ms, 이 컴퓨터 기준). 그래서 많이 늘릴 이유도 없습니다. 측정으로 찾은 최적값이 아니라, 이 숫자를 보고 고른 판단입니다.

**Q. 스레드를 요청마다 새로 만들면 안 되나요?**
만드는 비용이 매번 들고, 요청이 몰리면 스레드가 끝없이 늘어 메모리가 바닥납니다. Pool은 수를 정해 두고 다시 쓰며, 넘치는 요청은 큐에서 기다리거나 503으로 거절합니다.

**Q. 실제 서버도 이렇게 하나요?**
구조는 같습니다. 예를 들어 Java의 Tomcat도 스레드 수의 최대값과 기다리는 줄의 길이를 정해 두고, 줄까지 차면 연결을 거절합니다. 실무에서는 이 숫자들을 부하 테스트(요청을 대량으로 보내 응답 시간과 오류를 재는 것)로 정합니다.

**Q. Redis는 스레드 하나로 처리하던데, DB는 왜 여러 개인가요?**

| | Redis | DBMS |
| --- | --- | --- |
| 데이터가 있는 곳 | 메모리 | 파일(디스크) |
| 명령 하나에 걸리는 시간 | 아주 짧음 | 길 수 있음 (처음부터 다 읽는 SELECT 등) |
| 그래서 | 스레드 하나가 연결 여러 개를 번갈아 챙김(이벤트 루프). 하나씩 해도 줄이 길어지지 않음 | 하나가 오래 걸려도 다른 요청이 처리되게 스레드 여러 개 |
| 약점 | 긴 명령 하나가 전체를 멈춤 | 스레드마다 자원을 쓰고, 잠금(lock)이 필요함 |

두 시스템은 맡는 일이 다릅니다. Redis는 자주 빠르게 보는 값(예: 주식 현재가)을, DB는 사라지면 안 되는 값(예: 주문 기록)을 맡습니다. 우리 mini-redis는 실제 Redis와 달리 Flask 멀티스레드 + lock 구조였습니다.

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| `서버를 켤 수 없습니다 (포트 8000): ... Address already in use` | 8000번을 이미 쓰는 중. 이전 서버를 끄거나 `python3 server.py --port 8001` |
| `데이터 폴더를 열 수 없습니다` | 저장소 맨 위 폴더(`data/`가 있는 곳)에서 실행하기 |
| curl이 `exit 7`로 끝남 | 그 포트에 서버가 없음. 서버를 켠 포트와 curl의 포트를 맞추기 |
| curl 응답이 400 `Invalid control character` | `-d` 안에서 줄이 바뀜. 명령을 한 줄로 |
| 로그에 `worker-1`만 나옴 | 요청을 하나씩 보낸 것. 위처럼 `&`로 동시에 보내기 |
| 503이 자주 나옴 | 동시 요청이 큐보다 많음. `--queue`나 `--workers`를 늘리기 |
| 로그에 `"" 408` | 연결만 열고 시간 안에 요청을 다 보내지 않은 연결을 끊은 것. 정상 동작 ([STEP17](./STEP17.md)) |
