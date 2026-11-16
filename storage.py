import json
import os


class Storage:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def _path(self, table):
        return os.path.join(self.data_dir, f"{table}.tbl")

    def append(self, table, row):
        """파일 끝에 한 줄 쓰고, 그 줄이 시작하는 바이트 위치(offset)를 돌려준다."""
        with open(self._path(table), "ab") as f:
            offset = f.tell()
            f.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        return offset

    def read_at(self, table, offset):
        """offset 위치의 한 줄만 읽는다."""
        with open(self._path(table), "rb") as f:
            f.seek(offset)
            return json.loads(f.readline())

    def scan(self, table):
        """첫 줄부터 끝까지 (offset, row)를 하나씩 돌려준다."""
        if not os.path.exists(self._path(table)):
            return
        with open(self._path(table), "rb") as f:
            while True:
                offset = f.tell()
                line = f.readline()
                if not line:
                    break
                yield offset, json.loads(line)
