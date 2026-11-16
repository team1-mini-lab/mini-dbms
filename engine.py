import json
import os

from index import DictIndex
from parser import Insert, parse
from storage import Storage


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
            values = self._arrange(columns, cmd)          # 검사 먼저. 실패하면 번호를 쓰지 않음
            new_id = self.next_id[cmd.table]
            offset = self.storage.append(cmd.table, [new_id] + values)
            self.next_id[cmd.table] += 1                  # 파일에 쓴 뒤에 번호를 올림
            self.index[cmd.table].insert(new_id, offset)
            return {"type": "insert", "id": new_id}

        if cmd.where and cmd.where.column == "id":
            offset = self.index[cmd.table].search(cmd.where.value)
            rows = [] if offset is None else [self.storage.read_at(cmd.table, offset)]
            return {"type": "select", "columns": columns, "rows": rows, "used_index": True}

        if cmd.where:                                     # id가 아닌 열: 처음부터 읽으며 조건에 맞는 줄만
            if cmd.where.column not in columns:
                raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {cmd.where.column}")
            i = columns.index(cmd.where.column)
            rows = [row for _, row in self.storage.scan(cmd.table) if row[i] == cmd.where.value]
        else:
            rows = [row for _, row in self.storage.scan(cmd.table)]
        return {"type": "select", "columns": columns, "rows": rows, "used_index": False}

    def _arrange(self, columns, cmd):
        """값을 schema.json의 열 순서(id 제외)에 맞춰 배치한다."""
        names = columns[1:]                       # id는 엔진이 붙이므로 뺌
        given = cmd.columns or names              # 열 이름을 생략하면 schema 순서 그대로
        if len(given) != len(cmd.values):
            raise ValueError("열 수와 값 수가 다릅니다")
        by_name = dict(zip(given, cmd.values))
        unknown = set(by_name) - set(names)
        if unknown:
            raise ValueError(f"{cmd.table} 테이블에 없는 열입니다: {', '.join(sorted(unknown))}")
        return [by_name.get(name) for name in names]

    def close(self):
        pass
