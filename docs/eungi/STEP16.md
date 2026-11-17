# Phase 3(16단계): lock

> **한 줄 요약**: 여러 스레드가 동시에 `INSERT`해도 같은 id가 두 번 붙지 않도록, 엔진의 `execute`를 한 번에 하나씩만 실행하게 만들었습니다.

Phase 3는 16단계(lock) → 15단계(Thread Pool) → 17단계(오류 응답) 순서로 합니다. 스레드를 늘리기 **전에** 잠금부터 걸어 두면, Thread Pool을 붙이는 순간부터 안전하기 때문입니다 ([DESIGN 3절](../DESIGN.md#3-개발-순서)).

## 왜 필요한가

Phase 3(15단계)에서 서버는 스레드 여러 개로 요청을 동시에 처리합니다. 그러면 `INSERT` 두 개가 거의 같은 순간에 엔진에 들어올 수 있습니다.

`INSERT` 하나는 엔진 안에서 세 걸음입니다 ([STEP1 핵심 코드 ④](./STEP1.md#핵심-코드)).

```
① 다음 번호(next_id)를 읽음
② 그 번호로 파일에 씀
③ 다음 번호를 하나 올림
```

lock이 없으면, 스레드 A가 ①과 ③ 사이에 있을 때 스레드 B가 끼어들 수 있습니다.

| 순서 | 스레드 A | 스레드 B | next_id |
| --- | --- | --- | --- |
| 1 | ① 읽음 → 4 | | 4 |
| 2 | | ① 읽음 → **4** (A가 아직 ③ 전) | 4 |
| 3 | ② id 4로 씀 | | 4 |
| 4 | | ② **id 4로 씀** | 4 |
| 5 | ③ 5로 올림 | ③ 5로 올림 | 5 |

결과: 파일에 id 4가 두 줄 생기고, 인덱스에는 "4 → 위치"를 하나만 적을 수 있어서 한 줄은 id로 찾을 수 없게 됩니다.

## 무엇을 했나

엔진에 lock을 하나 두고, `execute` 전체를 그 lock 안에서 실행하게 했습니다. 스레드 A가 `execute`에 들어가 있는 동안 스레드 B는 입구에서 기다리고, A가 ①②③을 다 끝내고 나가야 B가 들어갑니다.

```
스레드 A ──[lock 얻음]── execute (①②③) ──[lock 풂]
스레드 B ────── 기다림 ─────────────────────────[lock 얻음]── execute (①②③) ──[lock 풂]
```

## 핵심 코드

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다.

### ① lock 만들기 · [`engine.py`](../../engine.py)의 `__init__`

```python
def __init__(self, data_dir):
    self._lock = threading.Lock()          # 엔진 하나에 lock 하나
    self.storage = Storage(data_dir)
    ...
```

- `threading.Lock()`은 파이썬에 기본으로 있는 잠금입니다. 한 번에 한 스레드만 가질 수 있습니다.
- 서버는 엔진을 하나만 만들어 모든 요청이 같이 쓰므로([D26](./DECISIONS.md#step3)), lock도 하나입니다.

### ② `execute`를 lock 안에서 실행하기 · [`engine.py`](../../engine.py)의 `locked`

```python
def locked(method):
    """감싼 함수를 엔진의 lock 안에서 실행한다. 한 번에 한 스레드만 들어간다."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:                   # 여기서 lock을 얻을 때까지 기다림
            return method(self, *args, **kwargs)   # 원래 execute를 실행. 끝나면 with를 나가며 lock을 풂
    return wrapper


class Engine:
    @locked                                # ← 이 한 줄로 execute 전체가 lock 안에서 실행됨
    def execute(self, sql, stop_on_error=False):
        ...                                # 안은 그대로
```

- `@locked`처럼 함수 위에 붙이는 것을 **데코레이터**라고 합니다. `execute`를 부르면 실제로는 `wrapper`가 먼저 실행되고, `wrapper`가 lock을 얻은 뒤 원래 `execute`를 부릅니다.
- `with self._lock:`은 들어갈 때 lock을 얻고, 나갈 때 **오류가 나도** 풀어 줍니다. 그래서 SQL 하나가 틀려도 lock이 잠긴 채로 남지 않습니다.
- `functools.wraps`는 `wrapper`가 원래 `execute`의 이름과 설명을 그대로 갖게 해 줍니다.

**왜 `execute` 안을 `with`로 감싸지 않았나** ([D32](./DECISIONS.md#step16)): 그렇게 해도 동작은 같습니다. 하지만 `execute` 안쪽 코드 전체가 한 칸 들여쓰기돼서, 같은 곳(`sql.split(";")` 줄)을 고치는 Phase 1(4\~5단계)과 합칠 때 충돌이 납니다. 데코레이터는 함수 위에 한 줄만 더하므로 안쪽은 그대로입니다.

### lock 범위: 왜 `execute` 전체인가 ([D31](./DECISIONS.md#step16))

| 선택 | 문제 |
| --- | --- |
| 문장 하나마다 잠금 | `INSERT ...; SELECT *`를 보냈는데 두 문장 사이에 다른 요청이 끼어들어, SELECT에 남의 INSERT가 섞여 나올 수 있음 |
| INSERT만 잠금 | INSERT가 파일에 반쯤 쓴 줄을 SELECT가 읽거나, B+ 트리가 노드를 나누는 도중에 SELECT가 찾다가 틀린 결과가 나올 수 있음 |
| **`execute` 전체 (선택)** | 엔진 안에서는 동시 실행이 없음. 대신 Phase 2의 B+ 트리는 **동시성을 신경 쓰지 않아도 됨** |

**lock이 막지 못하는 것**: CLI와 서버는 따로 실행되어서 lock도 각자 하나씩 가집니다. 그래서 서버가 켜져 있을 때 CLI로 `INSERT`하는 경우는 lock으로 막을 수 없습니다. 이 경우는 지금처럼 "쓰는 건 둘 중 하나만"이라는 규칙([D29](./DECISIONS.md#step3))으로 둡니다.

## 확인 스크립트 · [`checks/check_concurrency.py`](../../checks/check_concurrency.py)

스레드 100개가 **동시에** `INSERT`를 한 번씩 보내고, 파일에 저장된 id를 셉니다. lock을 끈 경우와 켠 경우를 둘 다 돌려서 비교합니다.

```python
start_together = threading.Barrier(THREADS)    # 100개가 다 준비되면 동시에 출발

def worker(n):
    start_together.wait()
    engine.execute(f"INSERT INTO users (name, age) VALUES ('u{n}', {n});")
```

- `threading.Barrier(100)`은 스레드 100개가 모두 `wait()`에 도착할 때까지 기다렸다가 한꺼번에 출발시킵니다. 최대한 동시에 들어가게 하려고 씁니다.
- **lock 끔**: `engine._lock`을 아무것도 안 하는 것(`contextlib.nullcontext()`)으로 바꿔 끼웁니다.
- **끼어들 틈 넓히기** ([D33](./DECISIONS.md#step16)): INSERT는 매우 빨라서, lock이 없어도 우연히 안 겹칠 때가 많습니다. 그래서 이 스크립트 안에서만 "파일에 쓰기"(②) 직전에 0.001초 쉬게 합니다. 실제 코드에는 쉬는 부분이 없습니다.

```python
def slow_append(table, row):           # ①과 ③ 사이(②)를 일부러 길게
    time.sleep(SLOW_WRITE_SECONDS)
    return original_append(table, row)

engine.storage.append = slow_append    # 이 스크립트의 엔진에만 바꿔 끼움
```

## 직접 확인해 보기

```bash
python3 checks/check_concurrency.py
```

```
[lock 끔] 스레드 100개가 동시에 INSERT
  파일에 저장된 줄: 100줄
  서로 다른 id: 16개
  겹친 id: 7개 (예: id 1 × 54번, id 2 × 14번, id 3 × 6번, id 4 × 6번, id 5 × 6번)
  빠진 id: 84개 (예: [6, 7, 9, 12, 13])
  → 실패: id가 겹치거나 빠짐

[lock 켬] 스레드 100개가 동시에 INSERT
  파일에 저장된 줄: 100줄
  서로 다른 id: 100개
  → 통과: id 1~100이 빠짐없이, 겹치지 않음
```

- **lock 끔**: 100줄이 저장됐는데 서로 다른 id는 16개뿐입니다. id 1이 54번이나 붙었습니다. 숫자는 실행할 때마다 조금씩 다릅니다.
- **lock 켬**: id 1\~100이 빠짐없이 한 번씩 붙었습니다. [DESIGN 3절](../DESIGN.md#3-개발-순서)의 16단계 완료 기준("동시에 `INSERT`를 100번 보내도 ID가 1\~100으로 빠짐없이, 겹치지 않음")과 같습니다.

| 확인 | 이렇게 나오면 됨 |
| --- | --- |
| `python3 checks/check_concurrency.py` | lock 켬: 통과 |
| `python3 checks/check_concurrency.py 500` | 스레드 500개로도 lock 켬: 통과 |
| `python3 checks/check_all.py` | "지금 통과해야 하는 것: 11/11" 그대로 (lock을 걸어도 기존 동작은 같음) |

## 이 단계에서 정한 것

자세한 이유는 [결정 기록의 Phase 3(16단계) 절](./DECISIONS.md#step16)에 있습니다.

- **D31** lock은 엔진 안에 하나, `execute` 전체를 감쌉니다. SELECT도 잠급니다.
- **D32** `@locked` 데코레이터 한 줄로 겁니다. `execute` 안은 들여쓰지 않습니다.
- **D33** lock이 없을 때 겹치는 시연은 확인 스크립트 안에서만 끼어들 틈을 넓혀서 보여 줍니다.

## 만든 파일

| 파일 | 내용 |
| --- | --- |
| `engine.py` (고침) | `locked` 데코레이터 추가, `__init__`에 `self._lock` 한 줄, `execute` 위에 `@locked` 한 줄. `execute` 안은 그대로 |
| `checks/check_concurrency.py` (새로) | 스레드 N개 동시 INSERT. lock 끔 / 켬 비교 |

## 다른 담당에게 영향

| 담당 | 영향 |
| --- | --- |
| Phase 1 | `execute` 안을 고쳐도 됩니다. lock은 함수 위 한 줄이라 충돌하지 않습니다 |
| Phase 2 | B+ 트리는 동시성을 신경 쓰지 않아도 됩니다. 엔진이 한 번에 하나씩만 `insert`/`search`를 부릅니다 |

## 발표 때 나올 질문

**Q. 엔진을 lock으로 한 번에 하나씩만 실행하면, Thread Pool로 병렬 처리하는 의미가 있나요?**

요청 하나는 이렇게 흘러갑니다.

```
① 연결 받기 → ② 요청 읽기(HTTP, JSON) → ③ engine.execute (lock) → ④ 응답 쓰기
                여러 스레드가 동시에             한 번에 하나          여러 스레드가 동시에
```

②와 ④(네트워크로 주고받기, JSON 바꾸기)는 여러 스레드가 동시에 하고, 줄을 서는 건 ③뿐입니다. 느린 클라이언트 하나가 다른 요청을 막지도 않습니다. ③의 SELECT끼리도 동시에 하게 만드는 것은 차별화(21단계) 읽기/쓰기 lock입니다.

## 막히면

| 이런 일이 생기면 | 이렇게 |
| --- | --- |
| 서버가 멈춰서 응답이 안 옴 | `execute` 안에서 다시 `execute`를 부르면 같은 스레드가 lock을 두 번 얻으려다 멈춥니다. `execute` 안에서는 `_run`처럼 lock이 없는 함수를 부르기 |
| lock 끔에서 겹침이 안 생김 | 컴퓨터가 빨라서 우연히 안 겹친 것. 스레드 수를 늘리기 (`python3 checks/check_concurrency.py 300`) |
| 서버가 켜져 있는데 CLI로 넣었더니 id가 겹침 | lock으로는 못 막는 경우. [STEP3 ⚠️](./STEP3.md) 참고 |
