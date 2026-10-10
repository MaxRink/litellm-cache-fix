"""Fail-closed provenance check used by the diagnostic overlay image build."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

EXPECTED_BASE_SHA256 = "1227bd9292d28462e9db12946238dcc2f5caf20cd40ba9ebd504d27fa25c96e0"


def verify(path: Path, expected: str = EXPECTED_BASE_SHA256) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f"unexpected base source hash: {actual}")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
