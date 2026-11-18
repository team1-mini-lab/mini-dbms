"""엔진: CLI와 서버가 SQL을 넘기는 단 하나의 입구(execute).

SQL을 읽고 검사하고 실행하고 저장하는 일은 Phase 1의 minidb(lexer → parser → catalog → executor → storage)가 맡는다.
엔진이 하는 일은 셋뿐이다.
  - lock (Phase 3, 16단계): execute 전체를 한 번에 한 스레드만 지나가게 한다.
  - B+ 트리 인덱스 (Phase 2): INSERT가 쓴 파일 위치를 적어 두고, WHERE id = ? 는 그 한 줄만 읽는다.
  - 결과를 서버·CLI가 읽는 dict 모양으로 바꾼다 (접점 1).
"""
import functools
import threading
from pathlib import Path

from index import BPlusTree
from minidb.ast import Select
from minidb.catalog import Catalog
from minidb.errors import StorageError
from minidb.executor import Executor
from minidb.parser import parse
from minidb.storage import Storage as TableFiles


def locked(method):
    """Phase 3(16단계): 함수를 lock 안에서 실행한다.

    함수 위에 @locked를 붙이면, 그 아랫줄 함수가 method로 들어온다 (지금은 execute).
    """
    @functools.wraps(method)                        # wrapper에 원래 함수 이름(execute)을 붙여 줌
    def wrapper(self, *args, **kwargs):             # 받은 값은 그대로 method에 넘김
        with self._lock:                            # 잠금 (이미 잠겨 있으면 풀릴 때까지 기다림)
            return method(self, *args, **kwargs)    # 우리가 쓴 execute를 실행. 끝나면 자동으로 풂
    return wrapper


class _Files:
    """minidb 저장소를 '테이블 이름 + 행' 모양으로 감싼다. 확인 스크립트가 append를 바꿔 끼우는 자리."""

    def __init__(self, files):
        self._files = files

    def append(self, table, row):
        return self._files.table(table).append(row)

    def scan(self, table):
        return self._files.table(table).scan()

    def read_at(self, table, offset):
        return self._files.table(table).read_at(offset)

    def close(self):
        self._files.close()


class _TableForExecutor:
    """minidb 실행기가 부르는 storage.table(name)의 자리. 쓸 때마다 위치를 B+ 트리에 적는다."""

    def __init__(self, engine, name):
        self._engine = engine
        self._name = name

    def append(self, row):
        offset = self._engine.storage.append(self._name, row)   # 엔진을 거쳐 부름 (확인 스크립트가 바꿔 끼울 수 있게)
        self._engine.index[self._name].insert(row[0], offset)   # Phase 2: "id → 파일 위치"를 목차에
        return offset

    def scan(self):
        return self._engine.storage.scan(self._name)

    def read_at(self, offset):
        return self._engine.storage.read_at(self._name, offset)


class _StorageForExecutor:
    def __init__(self, engine):
        self._engine = engine

    def table(self, name):
        return _TableForExecutor(self._engine, name)


class Engine:
    def __init__(self, data_dir):
        self._lock = threading.Lock()   # Phase 3(16단계): lock을 만든다. execute를 부를 때마다 이 lock을 잠근다
        schema_path = Path(data_dir) / "schema.json"
        if not schema_path.exists():    # 서버·CLI가 "데이터 폴더를 열 수 없습니다"로 알려 주게 OSError로
            raise FileNotFoundError(f"스키마 파일이 없습니다: {schema_path}")
        self.catalog = Catalog.load(schema_path)
        self.schema = {                 # 서버의 테스트 페이지가 보여 주는 테이블 모양
            name: [[c.name, c.type] for c in self.catalog.table(name).columns]
            for name in self.catalog.table_names
        }
        self.storage = _Files(TableFiles(data_dir, self.catalog))
        # 목차는 메모리에만 있어서 끄면 사라진다. 엔진을 만들 때마다 파일을 처음부터 읽어 다시 만든다
        self.index = {}
        for name in self.catalog.table_names:
            self.index[name] = BPlusTree()
            for offset, row in self.storage.scan(name):
                self.index[name].insert(row[0], offset)
        self.executor = Executor(self.catalog, _StorageForExecutor(self))

    @locked
    def execute(self, sql, stop_on_error=False):
        """CLI는 기본값(틀린 문장이 있어도 계속), 서버는 stop_on_error=True(첫 오류에서 멈춤)로 부른다."""
        try:
            statements = parse(sql)
        except ValueError as e:         # 문법 오류: minidb는 문장 전체를 거절한다 (하나도 실행하지 않음)
            return [{"type": "error", "stage": "parse",
                     "message": f"문법 오류라 아무 문장도 실행하지 않았습니다: {e}"}]
        results = []
        for stmt in statements:
            try:
                results.append(self._run(stmt))
            except StorageError:        # 파일이 깨짐: 손님이 고칠 수 없는 데이터 문제 → 위로 올림 → 서버는 500
                raise
            except ValueError as e:     # SQL이 틀린 것만 결과에 담음 (minidb 오류는 모두 ValueError 하위). 그 밖은 위로 → 서버는 500
                results.append({"type": "error", "message": str(e)})
                if stop_on_error:
                    break
        return results

    def _run(self, stmt):
        if isinstance(stmt, Select) and self._is_id_lookup(stmt):
            return self._select_by_id(stmt)
        result = self.executor.execute(stmt)
        if isinstance(stmt, Select):
            return {"type": "select", "columns": list(result.columns),
                    "rows": [list(row) for row in result.rows], "used_index": False}
        return {"type": "insert", "id": result.rows[0][0]}

    @staticmethod
    def _is_id_lookup(stmt):
        where = stmt.where
        return where is not None and where.column == "id" and where.op == "=" and type(where.value) is int

    def _select_by_id(self, stmt):
        """WHERE id = 숫자: B+ 트리로 위치를 찾아 그 한 줄만 읽는다."""
        table = self.catalog.table(stmt.table)                         # 없는 테이블이면 TableNotFoundError
        names = table.column_names if stmt.columns is None else stmt.columns
        picks = [table.column_index(name) for name in names]           # 없는 열이면 ColumnNotFoundError
        offset = self.index[stmt.table].search(stmt.where.value)
        rows = [] if offset is None else [self.storage.read_at(stmt.table, offset)]
        return {"type": "select", "columns": list(names),
                "rows": [[row[i] for i in picks] for row in rows], "used_index": True}

    def close(self):
        self.storage.close()
