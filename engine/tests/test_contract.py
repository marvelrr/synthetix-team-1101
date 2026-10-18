"""Byte-level freeze of the exact shared v1.0 files supplied by the user."""
import hashlib
from pathlib import Path

import pytest

HASHES = {
    "requirements.txt": "754e48d1b78a5036aaa8d5d37523928d9dfdfab914956e9b6f4094d6531b3753",
    ".env.example": "ceeb2944fa6ce20068f67f654f926b611fda0cad392fdee18d7dc610b3f00808",
    ".gitignore": "e53e7e02374dec9139d0e504bc2b18bc9a6608818f5bf2c5faa0ad00705f829e",
    "contracts/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "contracts/models.py": "e50cfb6dd033a6a0defb060ab89164bc1c8b27c105520a6f889faaec2412a600",
    "contracts/db.py": "f10b52da5c3893621912b10491d5e04f977e21034c545c4ab84d51287cff8842",
    "contracts/llm.py": "21994d0de521b31021dab4c9227a020f399e57948001a729d1c3f0f811c71336",
}


@pytest.mark.parametrize("name", HASHES)
def test_contract_unchanged(name):
    root = Path(__file__).resolve().parents[2]
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == HASHES[name]
