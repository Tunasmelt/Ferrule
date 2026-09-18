"""Mutex-guarded, process-local compiler state for milestone 3a."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import RLock
from uuid import uuid4

from .openapi import Operation


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    base_url: str
    auth_kind: str


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    source_id: str
    kind: str
    raw: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class ExtractedSpec:
    id: str
    source_id: str
    source_hash: str
    openapi_version: str
    operations: tuple[Operation, ...]


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    status: str
    result: dict[str, object] | None = None
    options: tuple[Operation, ...] = ()


class Store:
    """A single lock keeps related source/job updates atomic; replace with a DB later."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sources: dict[str, Source] = {}
        self._documents: dict[str, Document] = {}
        self._specs: dict[str, ExtractedSpec] = {}
        self._jobs: dict[str, Job] = {}

    def put_source(self, source: Source) -> None:
        with self._lock:
            self._sources[source.id] = deepcopy(source)

    def get_source(self, source_id: str) -> Source | None:
        with self._lock:
            return deepcopy(self._sources.get(source_id))

    def put_document(self, document: Document) -> None:
        with self._lock:
            self._documents[document.id] = deepcopy(document)

    def documents_for(self, source_id: str) -> list[Document]:
        with self._lock:
            return deepcopy([item for item in self._documents.values() if item.source_id == source_id])

    def put_spec(self, spec: ExtractedSpec) -> None:
        with self._lock:
            self._specs[spec.id] = deepcopy(spec)

    def latest_spec_for(self, source_id: str) -> ExtractedSpec | None:
        with self._lock:
            matches = [item for item in self._specs.values() if item.source_id == source_id]
            return deepcopy(matches[-1]) if matches else None

    def put_job(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = deepcopy(job)

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return deepcopy(self._jobs.get(job_id))
