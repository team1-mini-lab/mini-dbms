"""모든 단계의 테스트가 공유하는 픽스처."""

import pytest

from minidb.catalog import Catalog

# docs/DESIGN.md 의 샘플 테이블. data/schema.json 과 같은 내용이다.
STUDENTS_SCHEMA = {
    "students": {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "name", "type": "TEXT"},
            {"name": "grade", "type": "INT"},
        ]
    }
}


@pytest.fixture
def catalog() -> Catalog:
    return Catalog.from_dict(STUDENTS_SCHEMA)
