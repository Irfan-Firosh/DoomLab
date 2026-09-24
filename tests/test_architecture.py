"""Guards on ownership boundaries that must hold as the code grows."""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "src" / "doomlab"
SOURCES = {p.relative_to(PKG).as_posix(): p.read_text() for p in PKG.rglob("*.py")}


def test_package_has_sources():
    assert "cli.py" in SOURCES


def test_only_executor_touches_the_game():
    callers = {name for name, src in SOURCES.items() if re.search(r"\.make_action\(", src)}
    assert callers <= {"tools/executor.py"}


def test_only_llm_client_talks_http():
    importers = {name for name, src in SOURCES.items() if re.search(r"^\s*(import|from) httpx", src, re.M)}
    assert importers <= {"llm/client.py"}


def test_no_eval_or_exec():
    assert not [name for name, src in SOURCES.items() if re.search(r"(?<![\w.])(eval|exec)\(", src)]
