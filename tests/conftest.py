from __future__ import annotations

from pathlib import Path

import pytest

from samsarix_workspace.workspace import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "workspace", max_file_bytes=256, max_total_bytes=1_024)
