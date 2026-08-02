from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import gettempdir


@dataclass(frozen=True)
class StorageObject:
    uri: str
    mime_type: str | None = None
    file_size: int | None = None
    content_hash: str | None = None


class StorageBackend(ABC):
    @abstractmethod
    def store(self, uri: str, payload: bytes | None = None) -> StorageObject:
        pass


class PassthroughStorageBackend(StorageBackend):
    def store(self, uri: str, payload: bytes | None = None) -> StorageObject:
        # Storage remains abstract: this backend trusts the provided URI.
        return StorageObject(uri=uri, file_size=len(payload) if payload is not None else None)


class LocalFileStorageBackend(StorageBackend):
    def __init__(self, root: str | None = None) -> None:
        base_root = Path(root) if root is not None else Path(gettempdir()) / "atlas-assets"
        base_root.mkdir(parents=True, exist_ok=True)
        self.root = base_root

    def store(self, uri: str, payload: bytes | None = None) -> StorageObject:
        if payload is None:
            return StorageObject(uri=uri)

        source_name = Path(uri).name or "asset.bin"
        object_hash = sha256(payload).hexdigest()
        destination = self.root / f"{object_hash}-{source_name}"
        destination.write_bytes(payload)
        return StorageObject(
            uri=destination.as_uri(),
            file_size=len(payload),
            content_hash=object_hash,
        )
