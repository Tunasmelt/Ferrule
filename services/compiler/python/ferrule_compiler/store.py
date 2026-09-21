"""Mutex-guarded, process-local compiler state for milestone 3a."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from threading import RLock
from typing import Literal
from uuid import uuid4

from ferrule_interpreter.coverage import Coverage

from .openapi import Operation


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class JobResumeError(Exception):
    """Raised by Store.resume_needs_input; reason maps 1:1 to an HTTP status in api.py."""

    def __init__(self, reason: Literal["not_found", "not_resumable", "invalid_choice"]) -> None:
        super().__init__(reason)
        self.reason = reason


class NodeVersionUpdateError(Exception):
    """Raised by Store.put_node_version/approve_node_version; reason maps 1:1 to an HTTP status in api.py."""

    def __init__(self, reason: Literal["not_found", "already_approved", "immutable"]) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    name: str
    base_url: str
    auth_kind: Literal["api_key", "bearer"]


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
    document_id: str
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
    # Only set for kind="compile": which source a needs_input job should
    # finish compiling against once resumed. resolve/extract jobs don't
    # need it, since resuming them only ever returns the resolved
    # operation rather than continuing on to compile it.
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class NodeVersion:
    id: str  # node_version_id (e.g. "nv_...")
    node_id: str  # e.g. "nd_...", stable across versions of the same node.
    # No same-node-different-version identity tracking exists yet -- every
    # compile mints a fresh node_id, always at semver "1.0.0". Real
    # versioning (matching an existing node, bumping its semver) is a
    # separate, larger concern deferred past this milestone.
    semver: str
    status: str
    artifact_hash: str
    source_id: str
    source_document_id: str
    operation: Operation
    plan: dict[str, object]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    coverage: Coverage
    limitations: tuple[str, ...]
    # Set only by Store.approve_node_version -- CLAUDE.md invariant 4
    # ("approved artifacts are immutable; there is no update path on an
    # approved node_version row other than status"). These four fields are
    # the one narrow exception, and only ever move from None -> a value
    # exactly once (approve_node_version refuses a version that already
    # has a signature); every other field is copied verbatim via
    # dataclasses.replace(), which is the only place these fields are ever
    # set, so there is no code path that can alter plan/schema/operation
    # data after creation.
    signature: str | None = None
    public_key_pem: str | None = None
    approved_at: str | None = None
    reviewer_note: str | None = None


class Store:
    """A single lock keeps related source/job updates atomic; replace with a DB later."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sources: dict[str, Source] = {}
        self._documents: dict[str, Document] = {}
        self._specs: dict[str, ExtractedSpec] = {}
        self._jobs: dict[str, Job] = {}
        self._node_versions: dict[tuple[str, str], NodeVersion] = {}

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

    def get_document(self, document_id: str) -> Document | None:
        with self._lock:
            return deepcopy(self._documents.get(document_id))

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

    def resume_needs_input(self, job_id: str, choice: str) -> Job:
        """Atomically validate-and-consume a needs_input job in one lock acquisition.

        A separate get-then-put (the original shape) lets two concurrent
        resumes of the same job both pass the status check before either
        writes, so the second silently clobbers the first's result. Holding
        the lock across the whole check-select-write sequence makes a job
        resumable exactly once, the same single-use guarantee the proxy's
        journal gives replay protection.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobResumeError("not_found")
            if job.status != "needs_input":
                raise JobResumeError("not_resumable")
            selected = next((item for item in job.options if item.operation_id == choice), None)
            if selected is None:
                raise JobResumeError("invalid_choice")
            # Preserve the original kind/source_id rather than hardcoding
            # "resolve": a kind="compile" job (POST /nodes/compile's
            # needs_input path) must still be recognizable as one after
            # resuming, so the caller (api.py's resume_job) knows to finish
            # compiling rather than just returning the resolved operation.
            resolved = Job(job.id, job.kind, "succeeded", {"operation": asdict(selected)}, source_id=job.source_id)
            self._jobs[job.id] = deepcopy(resolved)
            return deepcopy(resolved)

    def put_node_version(self, node_version: NodeVersion) -> None:
        """Create a new node version record.

        Refuses to overwrite an existing (node_id, semver) that is already
        approved -- CLAUDE.md invariant 4, enforced at this layer (not just
        the API surface) so no future caller of this method, by mistake or
        by design, can silently replace an approved version's plan/schema
        data with a fresh unapproved one under the same key. Today's only
        caller (_compile_and_store) always mints a fresh node_id per call,
        so this can't happen via the current API either -- this guard is
        defense-in-depth against a future caller, not a fix for an
        observed bug.
        """
        with self._lock:
            key = (node_version.node_id, node_version.semver)
            existing = self._node_versions.get(key)
            if existing is not None and existing.status == "approved":
                raise NodeVersionUpdateError("immutable")
            self._node_versions[key] = deepcopy(node_version)

    def get_node_version(self, node_id: str, semver: str) -> NodeVersion | None:
        with self._lock:
            return deepcopy(self._node_versions.get((node_id, semver)))

    def approve_node_version(
        self, node_id: str, semver: str, signature: str, public_key_pem: str, approved_at: str, reviewer_note: str
    ) -> NodeVersion:
        """Atomically transition a node version to approved, exactly once.

        Uses dataclasses.replace() rather than constructing a new
        NodeVersion by hand: replace() copies every field verbatim except
        the ones explicitly passed, so this is the one place approval
        fields are set, and it is structurally incapable of altering
        plan/input_schema/output_schema/operation/coverage/limitations --
        there is no code path here that could mutate them even by mistake,
        which is the literal invariant-4 test criterion ("no code path
        allows mutating an approved node_version row except its status
        field"), checked at this store layer rather than only the API
        surface.
        """
        with self._lock:
            existing = self._node_versions.get((node_id, semver))
            if existing is None:
                raise NodeVersionUpdateError("not_found")
            if existing.status == "approved":
                raise NodeVersionUpdateError("already_approved")
            approved = replace(
                existing,
                status="approved",
                signature=signature,
                public_key_pem=public_key_pem,
                approved_at=approved_at,
                reviewer_note=reviewer_note,
            )
            self._node_versions[(node_id, semver)] = deepcopy(approved)
            return deepcopy(approved)
