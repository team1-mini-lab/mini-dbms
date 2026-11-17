import functools
import json
import os
import threading

from index import DictIndex
from parser import Insert, parse
from storage import Storage

TYPES = {"INT": int, "TEXT": str}


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
    def __init__(self, data_dir):
        self._lock = threading.Lock()   # Phase 3(16단계): lock을 만든다. execute를 부를 때마다 이 lock을 잠근다
        self.storage = Storage(data_dir)
        with open(os.path.join(data_dir, "schema.json"), encoding="utf-8") as f:
            self.schema = json.load(f)
        self.index = {}
        self.next_id = {}
        # 목차와 다음 번호는 메모리에만 있어서 끄면 사라진다. 그래서 엔진을 만들 때마다(CLI는 실행할 때마다,
        # 서버는 켤 때 한 번) 파일을 처음부터 읽어 다시 만든다
        for table in self.schema:
            self.index[table] = DictIndex()
            last = 0
            for offset, row in self.storage.scan(table):
                self.index[table].insert(row[0], offset)
                last = max(last, row[0])
            self.next_id[table] = last + 1

    @locked
    def execute(self, sql, stop_on_error=False):
        """CLI는 기본값(틀린 문장이 있어도 계속), 서버는 stop_on_error=True(첫 오류에서 멈춤)로 부른다."""
        results = []
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:   # 임시: Phase 1(4단계)에서 토큰 뒤에 나눔
            try:
                results.append(self._run(parse(stmt)))
            except ValueError as e:                       # Phase 3(17단계): SQL이 틀린 것만 결과에 담음. 그 밖(디스크 오류 등)은 위로 → 서버는 500
                results.append({"type": "error", "message": str(e)})
                if stop_on_error:
                    break                                 # 뒤 문장은 실행하지 않음
        return results

    def _run(self, cmd):
        if cmd.table not in self.schema:
            raise ValueError(f"{cmd.table} 테이블이 없습니다")
        columns = [name for name, _ in self.schema[cmd.table]]

        if isinstance(cmd, Insert):
            values = self._arrange(columns, cmd)          # 검사 먼저. 실패하면 번호는 그대로
            new_id = self.next_id[cmd.table]
            offset = self.storage.append(cmd.table, [new_id] + values)
            self.next_id[cmd.table] += 1                  # 파일에 쓴 뒤에 올림
            self.index[cmd.table].insert(new_id, offset)
            return {"type": "insert", "id": new_id}

        # 아직 못 하는 것은 조용히 넘기지 않고 오류로 막음 (5단계 파서가 들어와도 틀린 결과가 안 나오게)
        if cmd.columns != ["*"]:
            raise ValueError("아직 SELECT * 만 처리합니다")
        where = cmd.where
        if where:
            if where.op != "=":
                raise ValueError("아직 = 조건만 처리합니다")
            if where.column not in columns:
                raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {where.column}")
            i = columns.index(where.column)
            expected = TYPES[self.schema[cmd.table][i][1]]
            if not isinstance(where.value, expected):
                raise ValueError(f"{where.column} 열은 {self.schema[cmd.table][i][1]} 값과 비교해야 합니다")

        if where and where.column == "id":
            offset = self.index[cmd.table].search(where.value)
            rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]
            return {"type": "select", "columns": columns, "rows": rows, "used_index": True}

        rows = [row for _, row in self.storage.scan(cmd.table) if not where or row[i] == where.value]
        return {"type": "select", "columns": columns, "rows": rows, "used_index": False}

    def _arrange(self, columns, cmd):
        """값을 schema.json의 열 순서(id 제외)에 맞춰 배치한다."""
        names = columns[1:]                       # id는 엔진이 붙이므로 뺌
        given = cmd.columns or names              # 열 이름을 생략하면 schema 순서 그대로
        if len(given) != len(cmd.values):
            raise ValueError("열 수와 값 수가 다릅니다")
        if columns[0] in given:
            raise ValueError(f"{columns[0]}는 자동으로 붙으므로 직접 넣을 수 없습니다")
        if len(set(given)) != len(given):
            raise ValueError("같은 열이 두 번 있습니다")
        unknown = set(given) - set(names)
        if unknown:
            raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {', '.join(sorted(unknown))}")
        missing = set(names) - set(given)
        if missing:
            raise ValueError(f"빠진 열이 있습니다: {', '.join(sorted(missing))}")
        by_name = dict(zip(given, cmd.values))
        return [by_name[name] for name in names]

    def close(self):
        pass
