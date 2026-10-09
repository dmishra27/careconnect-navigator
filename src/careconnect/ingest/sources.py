"""List and read source files from a local folder or a Unity Catalog Volume.

The same code works on a laptop and in a Databricks job:
- a local folder (e.g. data/raw) is read with plain file I/O
- /Volumes/... is read directly when mounted (inside Databricks), otherwise
  through the Databricks Files API (laptop, via your CLI profile)
"""

import csv
import io
from dataclasses import dataclass
from pathlib import Path

SUBFOLDERS = {"leaflets": ".md", "policies": ".pdf"}


@dataclass
class SourceFile:
    path: str
    kind: str  # "leaflets" or "policies"
    data: bytes


class SourceReader:
    def __init__(self, root: str):
        self.root = root.rstrip("/")
        self._local = Path(self.root).exists()
        self._ws = None
        if not self._local:
            from databricks.sdk import WorkspaceClient

            self._ws = WorkspaceClient()

    def _list(self, folder: str) -> list[str]:
        path = f"{self.root}/{folder}"
        if self._local:
            p = Path(path)
            return (
                sorted(str(f).replace("\\", "/") for f in p.iterdir() if f.is_file())
                if p.exists()
                else []
            )
        try:
            entries = self._ws.files.list_directory_contents(path)
            return sorted(e.path for e in entries if not e.is_directory)
        except Exception:  # folder missing in the Volume
            return []

    def read(self, path: str) -> bytes:
        if self._local:
            return Path(path).read_bytes()
        return self._ws.files.download(path).contents.read()

    def files(self) -> list[SourceFile]:
        out = []
        for folder, ext in SUBFOLDERS.items():
            for path in self._list(folder):
                if path.lower().endswith(ext):
                    out.append(SourceFile(path=path, kind=folder, data=self.read(path)))
        return out

    def policy_manifest(self) -> dict[str, dict]:
        path = f"{self.root}/policies/sources.csv"
        try:
            text = self.read(path).decode("utf-8-sig")
        except Exception:
            return {}
        return {row["file_name"]: row for row in csv.DictReader(io.StringIO(text))}
