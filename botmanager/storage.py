import json
import os
import tempfile
import threading
from pathlib import Path


class JsonStore:
    """Thread-safe read/modify/write with atomic replacement on disk."""

    def __init__(self, path, default=None):
        self.path = Path(path)
        self.default = default if default is not None else {}
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return json.loads(json.dumps(self.default))
            return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, value):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(value, file, indent=2, ensure_ascii=False, allow_nan=False)
                    file.write("\n")
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def update(self, callback):
        with self.lock:
            value = self.read()
            callback(value)
            self.write(value)
            return value
