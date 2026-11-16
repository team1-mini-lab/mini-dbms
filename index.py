class DictIndex:
    """2단계 임시 인덱스. 12단계에서 같은 두 함수를 가진 B+ 트리로 바꾼다."""

    def __init__(self):
        self._d = {}

    def insert(self, key, value):
        self._d[key] = value

    def search(self, key):
        return self._d.get(key)
