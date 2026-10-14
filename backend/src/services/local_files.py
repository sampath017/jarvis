"""Private API working files on the local filesystem, with no cloud bucket."""
from pathlib import Path


def source_root():
    from .mobile_scope import mobile_only
    if mobile_only(): raise RuntimeError('File sources belong on Android, not the processing server')
    from .database.connection import get_db_path
    root = get_db_path().parent / 'sources'
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


class LocalBlob:
    def __init__(self, name):
        root = source_root()
        self.path = (root / name).resolve()
        if not self.path.is_relative_to(root):
            raise ValueError('Invalid source path')
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def size(self):
        return self.path.stat().st_size

    def upload_from_string(self, data, **kwargs):
        self.path.write_bytes(data.encode() if isinstance(data, str) else data)

    def delete(self):
        self.path.unlink(missing_ok=True)

    def reload(self):
        self.path.stat()


class LocalSources:
    def blob(self, name):
        return LocalBlob(name)
