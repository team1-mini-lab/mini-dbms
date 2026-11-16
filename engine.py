import json
import os

from index import DictIndex
from parser import Insert, parse
from storage import Storage

TYPES = {"INT": int, "TEXT": str}


class Engine:
    def __init__(self, data_dir):
        self.storage = Storage(data_dir)
        with open(os.path.join(data_dir, "schema.json"), encoding="utf-8") as f:
            self.schema = json.load(f)
        self.index = {}
        self.next_id = {}
        # CLI는 실행할 때마다 새로 켜지므로, 켤 때 파일을 읽어 목차와 다음 번호를 다시 만든다
        for table in self.schema:
            self.index[table] = DictIndex()
            last = 0
            for offset, row in self.storage.scan(table):
                self.index[table].insert(row[0], offset)
                last = max(last, row[0])
            self.next_id[table] = last + 1

    def execute(self, sql):
        results = []
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:   # 임시: 4단계에서 토큰 뒤에 나눔
            try:
                results.append(self._run(parse(stmt)))
            except Exception as e:
                results.append({"type": "error", "message": str(e)})
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
