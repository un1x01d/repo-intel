from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from uuid import UUID


class RepoWorkspace:
    """Temporary checkout workspace for a single scan."""

    def __init__(self, scan_id: UUID, root: Path | None = None) -> None:
        self.scan_id = scan_id
        self.root = root
        self.path: Path | None = None

    def __enter__(self) -> RepoWorkspace:
        if self.root is None:
            self.path = Path(tempfile.mkdtemp(prefix=f"repo-intel-{self.scan_id}-"))
        else:
            self.root.mkdir(parents=True, exist_ok=True)
            self.path = self.root / str(self.scan_id)
            if self.path.exists():
                shutil.rmtree(self.path)
            self.path.mkdir(parents=True)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.path is not None and self.path.exists():
            shutil.rmtree(self.path)
