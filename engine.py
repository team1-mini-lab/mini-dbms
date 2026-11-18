"""엔진: 서버(와 확인 스크립트)가 SQL을 넘기는 단 하나의 입구(execute).

SQL을 읽고 검사하고 실행하고 저장하는 일, B+ 트리로 찾는 일은 Phase 1·2의 minidb가 맡는다
(lexer → parser → catalog → executor(+ bptree) → storage).
엔진이 하는 일은 셋뿐이다.
  - 읽기/쓰기 lock (Phase 3, 16단계): SELECT끼리는 동시에, INSERT는 혼자 실행한다.
      · SELECT만 있는 SQL → 읽기 lock. 여러 스레드가 동시에 들어간다 (SQL 병렬 처리).
        SELECT는 공유 상태를 바꾸지 않는다. B+ 트리는 찾기만 하고, 파일은 pread로 읽는다 (storage.py).
      · INSERT가 하나라도 있는 SQL → 쓰기 lock. 혼자 들어간다.
        INSERT는 다음 id, B+ 트리, 파일 끝을 바꾸므로, 그동안 다른 INSERT도 SELECT도 들어오면 안 된다.
  - Executor 하나를 서버 전체가 같이 쓴다. B+ 트리는 Executor 메모리에만 있어서,
    요청마다 새로 만들면 매번 파일 전체를 다시 읽는다 (100만 건이면 약 1.9초).
  - 결과를 서버가 읽는 dict 모양으로 바꾼다 (접점 1).
켤 때(__init__)는 테이블마다 B+ 트리를 미리 만들어 둔다 (예열). 첫 요청이 쓰기 lock을 오래 잡지 않게.

시연용 (execute(..., with_stats=True), 서버가 씀):
  - use_index=False: id 조건이어도 B+ 트리를 쓰지 않고 전체 스캔 (인덱스 효과 비교)
  - SELECT 결과마다 rows_scanned(읽어서 비교한 행 수), elapsed_ms(실행기 안에서 걸린 시간)
  - 요청마다 lock 종류(read/write)와 lock을 기다린 시간(wait_ms)
  - read_only=True로 켜면 INSERT가 있는 SQL은 아무 문장도 실행하지 않고 거절한다.
    같은 데이터 폴더를 여러 서버 프로세스가 같이 볼 때 쓴다. B+ 트리와 다음 id가 프로세스마다
    따로 메모리에 있어서, 한쪽이 INSERT하면 다른 쪽은 그 행을 모른 채 같은 id를 또 준다.
"""
import contextlib
import threading
import time
from pathlib import Path

from minidb.ast import Select
from minidb.catalog import Catalog
from minidb.errors import MiniDBError, StorageError
from minidb.executor import Executor
from minidb.parser import parse
from minidb.storage import Storage


class ReadWriteLock:
    """읽기는 여럿이 동시에, 쓰기는 혼자만 들어가는 lock. (파이썬 표준 라이브러리에는 없어서 직접 만든다)

        with lock.read():   # 읽기 lock: 쓰는 스레드가 없으면 바로 들어감. 읽는 스레드끼리는 서로 막지 않음
        with lock:          # 쓰기 lock: 읽는 스레드도 쓰는 스레드도 없을 때만 들어감

    쓰기 우선: 쓰기가 기다리는 중이면 새 읽기는 들어가지 않고 기다린다.
    그러지 않으면 SELECT가 끊임없이 들어올 때 INSERT가 영원히 못 들어간다 (굶주림).
    """

    def __init__(self):
        self._cond = threading.Condition()   # 아래 숫자들을 보호하고, 바뀌면 기다리는 스레드를 깨운다
        self._readers = 0                    # 지금 안에 있는 읽기 스레드 수
        self._writer = False                 # 지금 안에 쓰기 스레드가 있는가
        self._writers_waiting = 0            # 들어가려고 기다리는 쓰기 스레드 수

    @contextlib.contextmanager
    def read(self):
        with self._cond:
            while self._writer or self._writers_waiting:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()  # 마지막 읽기가 나감 → 기다리던 쓰기를 깨움

    def __enter__(self):
        with self._cond:
            self._writers_waiting += 1
            try:
                while self._writer or self._readers:
                    self._cond.wait()
            finally:
                self._writers_waiting -= 1
            self._writer = True
        return self

    def __exit__(self, *exc):
        with self._cond:
            self._writer = False
            self._cond.notify_all()          # 기다리던 읽기와 쓰기를 모두 깨움 (쓰기 우선은 read()가 지킴)

    def stats(self):
        """지금 안에 있는 읽기 수, 쓰기 여부, 기다리는 쓰기 수 (확인과 테스트용)."""
        with self._cond:
            return {"readers": self._readers, "writer": self._writer, "writers_waiting": self._writers_waiting}


def _ms(seconds):
    return round(seconds * 1000, 3)


class Engine:
    def __init__(self, data_dir, read_only=False):
        self._lock = ReadWriteLock()    # Phase 3(16단계): SELECT는 self._lock.read(), INSERT는 with self._lock
        self.read_only = read_only
        schema_path = Path(data_dir) / "schema.json"
        if not schema_path.exists():    # 서버가 "데이터 폴더를 열 수 없습니다"로 알려 주게 OSError로
            raise FileNotFoundError(f"스키마 파일이 없습니다: {schema_path}")
        self.catalog = Catalog.load(schema_path)
        self.schema = {                 # 서버의 테스트 페이지가 보여 주는 테이블 모양
            name: [[c.name, c.type] for c in self.catalog.table(name).columns]
            for name in self.catalog.table_names
        }
        self.storage = Storage(data_dir, self.catalog)
        self.executor = Executor(self.catalog, self.storage)   # 서버 전체가 이것 하나를 같이 씀
        # 예열: 실행기는 테이블을 처음 쓸 때 파일을 읽어 B+ 트리를 만든다 (100만 건이면 약 1.9초).
        # 첫 요청이 그 일을 하면 그동안 다른 요청이 기다리므로, 요청을 받기 전에 미리 만든다
        for name in self.catalog.table_names:
            self.executor.execute(parse(f"SELECT id FROM {name} WHERE id = 0;")[0])

    def execute(self, sql, stop_on_error=True, use_index=True, with_stats=False):
        """SQL 전체를 해석하고, 문장마다 실행해 결과 dict 목록을 돌려준다.

        - 문법 오류: 아무 문장도 실행하지 않는다 (minidb 설계, step02).
        - 실행 오류(없는 열 등): 결과에 담고, 기본은 그 문장에서 멈춘다 (step04 결정 2). 앞 문장은 되돌리지 않음.
        - 파일 손상(StorageError)과 그 밖의 예외: 잡지 않고 위로 올린다 → 서버는 500.

        해석(parse)은 공유 상태를 건드리지 않으므로 lock 밖에서 한다.
        해석한 문장이 전부 SELECT면 읽기 lock, 하나라도 INSERT가 있으면 쓰기 lock 안에서 실행한다.

        with_stats=True (서버가 씀): SELECT 결과에 rows_scanned·elapsed_ms를 붙이고,
        (결과 목록, {"mode": "read" | "write", "wait_ms": lock을 기다린 시간}) 둘을 돌려준다.
        SQL이 하나도 실행되지 않은 경우(문법 오류, 읽기 전용 거절)는 lock 정보가 None.
        """
        results, lock_info = self._execute(sql, stop_on_error, use_index, with_stats)
        return (results, lock_info) if with_stats else results

    def _execute(self, sql, stop_on_error, use_index, with_stats):
        try:
            statements = parse(sql)
        except MiniDBError as e:
            return [{"type": "error", "stage": "parse",
                     "message": f"문법 오류라 아무 문장도 실행하지 않았습니다: {e}"}], None
        select_only = all(isinstance(stmt, Select) for stmt in statements)
        if self.read_only and not select_only:
            return [{"type": "error", "stage": "read_only",
                     "message": "읽기 전용 서버라 INSERT가 있는 요청은 아무 문장도 실행하지 않았습니다"}], None
        lock = self._lock.read() if select_only else self._lock
        asked = time.perf_counter()
        with lock:
            lock_info = {"mode": "read" if select_only else "write", "wait_ms": _ms(time.perf_counter() - asked)}
            return self._run_all(statements, stop_on_error, use_index, with_stats), lock_info

    def _run_all(self, statements, stop_on_error, use_index, with_stats):
        results = []
        for stmt in statements:
            try:
                results.append(self._run(stmt, use_index, with_stats))
            except StorageError:        # 손님이 고칠 수 없는 데이터 문제 → 위로 → 500
                raise
            except MiniDBError as e:    # SQL이 틀림 → 결과에 담음 → 서버는 400
                results.append({"type": "error", "message": str(e)})
                if stop_on_error:
                    break
        return results

    def _run(self, stmt, use_index=True, with_stats=False):
        started = time.perf_counter()
        result = self.executor.execute(stmt, use_index=use_index)
        elapsed = time.perf_counter() - started   # 실행기 안에서 걸린 시간만 (lock 대기·해석·HTTP 제외)
        if isinstance(stmt, Select):
            out = {"type": "select", "columns": list(result.columns),
                   "rows": [list(row) for row in result.rows], "used_index": result.used_index}
            if with_stats:
                out["rows_scanned"] = result.rows_scanned
                out["elapsed_ms"] = _ms(elapsed)
            return out
        return {"type": "insert", "id": result.rows[0][0]}

    def lock_stats(self):
        """GET /stats용: 지금 SQL을 실행 중인 읽기 수, 쓰기 여부, 기다리는 쓰기 수."""
        return self._lock.stats()

    def close(self):
        self.storage.close()
