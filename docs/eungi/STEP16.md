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

위치는 줄 번호 대신 **파일과 함수 이름**으로 적었습니다. 아래 코드는 실제 `engine.py`와 주석까지 똑같습니다.

### ① lock 만들기 · [`engine.py`](../../engine.py)의 `__init__`

```python
class Engine:
    def __init__(self, data_dir):
        self._lock = threading.Lock()   # Phase 3(16단계): lock을 만든다. execute를 부를 때마다 이 lock을 잠근다
        self.storage = Storage(data_dir)
        ...
```

- `threading.Lock()`은 파이썬에 기본으로 있는 잠금 장치입니다. 상태는 **열림**과 **잠김** 두 가지뿐입니다.
- 이 줄에서는 lock을 **만들기만** 합니다. 아직 잠그지 않습니다. 실제로 잠그는 건 `execute`를 부를 때입니다 (②).
- 서버는 엔진을 하나만 만들어 모든 요청이 같이 씁니다([D26](./DECISIONS.md#step3)). 그래서 엔진 안에 lock을 하나 두면 **모든 스레드가 같은 lock 하나**를 씁니다. 스레드마다 자기 lock을 가지면 아무도 서로를 기다리지 않습니다.

### ② `execute`를 lock 안에서 실행하기 · [`engine.py`](../../engine.py)의 `locked`

```python
def locked(method):
    """Phase 3(16단계): 함수를 lock 안에서 실행한다.

    함수 위에 @locked를 붙이면, 그 아랫줄 함수가 method로 들어온다 (지금은 execute).
    """
    @functools.wraps(method)                        # wrapper에 원래 함수 이름(execute)을 붙여 줌
    def wrapper(self, *args, **kwargs):             # 받은 값은 그대로 method에 넘김
        with self._lock:                            # 잠금 (이미 잠겨 있으면 풀릴 때까지 기다림)
            return method(self, *args, **kwargs)    # 우리가 쓴 execute를 실행. 끝나면 자동으로 풂
    return wrapper


class Engine:
    @locked                                         # ← 이 한 줄로 execute 전체가 lock 안에서 실행됨
    def execute(self, sql, stop_on_error=False):
        ...                                         # 안은 그대로
```

#### `@locked`는 어떻게 동작하나

`@locked`처럼 함수 위에 붙이는 것을 **데코레이터**라고 합니다. **바로 아랫줄의 함수가 `locked`의 인자(`method`)로 들어갑니다.** 파이썬은 위 코드를 이렇게 바꿔서 실행합니다.

```python
def execute(self, sql, stop_on_error=False):   # ① 우리가 쓴 execute를 만들고
    ...
execute = locked(execute)                       # ② locked에 넘겨서 돌려받은 wrapper로 바꿔 끼움
```

| 이름 | 무엇 |
|---|---|
| `method` | 우리가 쓴 `execute` 코드. `@locked`를 `execute` 위에 붙였기 때문에 `execute`가 들어옴. 다른 함수 위에 붙이면 그 함수가 들어옴 |
| `wrapper` | 잠그고 → `method`를 실행하고 → 푸는 함수. 이게 새 `execute` 자리에 들어감 |
| `*args, **kwargs` | 받은 값을 **그대로 넘겨주라**는 뜻. `wrapper`는 `execute`가 무슨 값을 받는지 몰라도 됨 |
| `@functools.wraps(method)` | `wrapper`에 원래 함수의 이름(`execute`)을 붙여 줌. 오류가 나면 `execute`에서 났다고 보여서 찾기 쉬움 |

이 바꿔 끼우기는 `engine.py`를 처음 불러올 때 **한 번** 일어납니다. 그 뒤로 `engine.execute(...)`를 부르면 이 순서로 실행됩니다.

```
engine.execute("INSERT ...; SELECT ...")
  → wrapper 실행
      → with self._lock: 잠금 🔒 (다른 스레드가 잡고 있으면 여기서 기다림)
          → method = 우리가 쓴 execute 실행: 문장 나누기 → parse → _run → storage / index
      → with를 나감: 풂 🔓 (오류가 나도 풂)
  → 결과를 돌려줌
```

`execute` 자리에 정말 `wrapper`가 들어 있는지 직접 확인할 수 있습니다.

```bash
python3 -c "
from engine import Engine
print(Engine.execute)              # wrapper (이름은 wraps 덕분에 execute로 보임)
print(Engine.execute.__wrapped__)  # 우리가 쓴 execute
"
```
```
<function Engine.execute at 0x104f3bba0>
<function Engine.execute at 0x104f3bb00>
```
이름은 둘 다 `Engine.execute`지만 끝의 주소가 다릅니다. **서로 다른 함수**라는 뜻입니다.

#### `with self._lock:`은 무엇을 하나

`with`는 "들어갈 때 준비하고, 나갈 때 정리한다"는 문법입니다. lock에서는 아래와 같습니다.

```python
with self._lock:
    일을 함

# 위와 똑같은 코드
self._lock.acquire()      # 잠금. 이미 잠겨 있으면 풀릴 때까지 이 줄에서 멈춰서 기다림
try:
    일을 함
finally:
    self._lock.release()  # 풂. 오류가 나도 반드시 풂
```

`acquire()`가 핵심입니다. **잠겨 있으면 그 줄을 넘어가지 못하고 기다립니다.** 두 스레드가 정확히 같은 순간에 `acquire()`를 불러도 잠금을 얻는 건 하나뿐이라고 파이썬이 보장합니다. 그래서 `execute` 안에는 언제나 한 스레드만 있습니다.

```
A: acquire() → 열려 있음 → 잠그고 통과 → execute 실행 중...
B: acquire() → 잠겨 있음 → 이 줄에서 기다림
A: ...execute 끝 → release() → 열림
B: (깨어남) → 잠그고 통과 → execute 실행 → release()
```

#### `with`와 `@locked`의 차이 ([D32](./DECISIONS.md#step16))

`@locked`도 안에서는 `with self._lock:`을 씁니다. **`with`를 함수 바깥(데코레이터)으로 옮겨 놓은 것**이라 실행 결과는 똑같습니다. 다른 건 코드가 어떻게 바뀌느냐입니다.

```python
# 방법 A: with로 안을 감싸기
def execute(self, sql):
    with self._lock:
        ...원래 코드 전부 한 칸 들여쓰기...

# 방법 B: @locked (선택)
@locked
def execute(self, sql):
    ...원래 코드 그대로...
```

| | `with self._lock:` | `@locked` |
|---|---|---|
| 실행 결과 | 같음 | 같음 |
| 바뀌는 줄 | 함수 안 **전체**가 들여쓰기로 바뀜 | 함수 위 **한 줄** 추가 |
| Phase 1과 합칠 때 | Phase 1(4\~5단계)도 같은 `execute` 안을 고쳐서 **충돌** | 서로 다른 줄이라 자동으로 합쳐짐 |
| 잠그는 범위 | 함수 일부만 잠글 수도 있음 | 함수 **전체**만 |

함수 **전체**를 잠글 때는 `@locked`, 함수 **일부만** 잠가야 할 때는 `with`를 씁니다.

### lock 범위: 왜 `execute` 전체인가 ([D31](./DECISIONS.md#step16))

`execute`는 CLI와 서버가 SQL을 넘길 때 부르는 **유일한 입구**입니다. 엔진의 다른 함수는 전부 `execute` 안에서만 불립니다.

```
cli.py ─────┐
server.py ──┴──→ execute 🔒 ──→ _run ──→ _arrange
                                      └→ storage.append / scan / read_at
                                      └→ index.insert / search
                                 (전부 잠긴 상태에서 실행)
```

| 함수 | lock | 이유 |
|---|---|---|
| `__init__` | 안 걸음 | 서버가 요청을 받기 **전에** 한 번만 실행됨. 그때는 스레드가 하나뿐 |
| `execute` | **걸었음** | CLI와 서버가 부르는 유일한 입구 |
| `_run`, `_arrange` | 따로 안 걸어도 됨 | `execute` 안에서만 불려서 이미 잠긴 상태 |
| `storage`, `index` | 따로 안 걸어도 됨 | 마찬가지로 `execute` 안에서만 쓰임 |

**SELECT도 잠깁니다.** SELECT만 따로 잠그는 코드는 없지만, SELECT도 `execute` → `_run`의 SELECT 부분으로 가기 때문에 같이 잠깁니다. 다른 스레드가 lock을 1초 동안 잡고 있는 사이에 SELECT를 보내 보면, SELECT가 **1.00초를 기다렸다가** 실행됩니다.

**함수마다 따로 lock을 걸면 안 되나요?**
1. 함수와 함수 사이에 틈이 생깁니다. "번호 읽기 → 쓰기 → 번호 올리기"가 한 번에 이어져야 하는데, 함수마다 풀었다 잠그면 그 사이에 다른 스레드가 끼어듭니다.
2. 서버가 멈출 수 있습니다. `execute`가 잠근 상태로 `_run`을 부르는데 `_run`도 같은 lock을 걸려고 하면, 자기가 잡고 있는 lock이 풀리기를 자기가 기다리게 됩니다.

**왜 storage에 lock을 걸지 않았나요?** INSERT 한 번은 네 곳에 걸쳐 있습니다.

```
① 다음 번호 읽기      ← engine (self.next_id)
② 파일에 쓰기         ← storage
③ 다음 번호 올리기    ← engine (self.next_id)
④ 인덱스에 적기       ← index
```

storage에 lock을 걸면 ②만 보호되고 ①③④는 보호되지 않습니다. 실제로 엔진 lock은 끄고 storage에만 lock을 건 채 스레드 100개로 돌려 보면 **100줄 전부 id 1**이 됩니다. storage lock은 파일에 두 줄이 섞여 써지는 것만 막을 뿐, 같은 번호를 읽는 것은 못 막습니다.

| lock 위치 | 보호되는 것 | 결과 (스레드 100개) |
|---|---|---|
| storage | ② 파일 쓰기만 | 100줄 전부 id 1 ❌ |
| **engine `execute`** | **①\~④ 전부** | id 1\~100 정확 ✅ |

lock은 **같이 바뀌어야 하는 것들을 모두 감싸는 가장 바깥**에 걸어야 합니다. 그 자리가 `execute`입니다.

| 다른 선택 | 문제 |
| --- | --- |
| 문장 하나마다 잠금 | `INSERT ...; SELECT *` 사이에 다른 요청이 끼어들어 SELECT에 남의 INSERT가 섞여 나올 수 있음 |
| INSERT만 잠금 | INSERT가 반쯤 쓴 줄을 SELECT가 읽거나, B+ 트리가 노드를 나누는 도중에 SELECT가 찾다가 틀린 결과가 나올 수 있음 |

`execute` 전체를 잠그면 엔진 안에서는 동시 실행이 없습니다. 그래서 Phase 2의 B+ 트리는 **동시성을 신경 쓰지 않아도 됩니다.**

**⚠️ 지켜야 할 규칙**: 엔진은 항상 `engine.execute`로만 부릅니다. 엔진 밖에서 `engine._run(...)`이나 `engine.storage.append(...)`를 직접 부르면 lock을 건너뛰게 됩니다.

| 누가 | 조심할 상황 |
| --- | --- |
| Phase 1 | Phase 1(6단계)에서 실행기를 `executor.py`로 떼어 내도, 입구는 `engine.execute` 하나로 남기고 `@locked`도 그대로 둠 |
| Phase 2 | Phase 2(14단계) 성능 비교에서 `engine.index.search(...)`를 직접 부르지 말고 `engine.execute("SELECT ...")`로 잼 |

**lock이 막지 못하는 것**: CLI와 서버는 따로 실행되어서 lock도 각자 하나씩 가집니다. 서버가 켜져 있을 때 CLI로 `INSERT`하는 경우는 lock으로 막을 수 없어서, "쓰는 건 둘 중 하나만" 규칙([D29](./DECISIONS.md#step3))으로 둡니다.

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
- **끼어들 틈 넓히기** ([D33](./DECISIONS.md#step16)): lock이 없어도 우연히 안 겹칠 때가 많아서, 이 스크립트 안에서만 "파일에 쓰기"(②) 직전에 0.001초 쉬게 합니다. 실제 코드에는 쉬는 부분이 없습니다.

**왜 우연히 안 겹치나요?** 직접 재 보면 이렇습니다.

| | 시간 |
| --- | --- |
| INSERT 하나가 끝나는 데 걸리는 시간 | 약 0.011ms |
| 파이썬이 스레드를 바꿔 주는 간격 (`sys.getswitchinterval()`) | 약 5ms |

파이썬은 스레드 여러 개를 진짜로 동시에 돌리지 않고, 약 5ms마다 번갈아 가며 조금씩 실행합니다. INSERT는 0.011ms면 끝나서, **스레드가 바뀌기 전에 이미 다 끝나 버리는** 경우가 대부분입니다. 아주 가끔 ①과 ③ 사이에서 스레드가 바뀔 때만 겹칩니다. 평소에는 안 보이다가 사용자가 많을 때 가끔 터지는 문제라 더 위험합니다.

`time.sleep()`을 부르면 파이썬은 그 즉시 다른 스레드로 바꿉니다. 그래서 쉬게 하면 모든 스레드가 ① 번호 읽기까지 마친 뒤 ②로 가게 되고, 같은 번호를 읽게 됩니다.

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

- **lock 끔**: 100줄이 저장됐는데 서로 다른 id는 16개뿐입니다. id 1이 54번이나 붙었습니다. 숫자는 실행할 때마다 다르고, 100줄 전부 id 1이 나올 때도 있습니다. 스레드들이 번호를 올리기 **전에** 같은 번호를 읽어 버렸기 때문입니다. 중요한 건 **매번 겹친다**는 것입니다.
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
