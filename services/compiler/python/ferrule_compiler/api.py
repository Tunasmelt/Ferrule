"""FastAPI surface for compiler ingest and deterministic operation resolution."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal, Mapping, cast
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from ferrule_artifact import artifact_hash as compute_artifact_hash
from ferrule_artifact import build as build_artifact
from ferrule_artifact import encode_signature, generate_dev_keypair, sign

from .claims import extract_claims
from .evidence import assemble_evidence
from .generate import CompileResult, compile_operation
from .mocktest import golden_case, run_mock_case
from .models import (
    ApprovalResponse,
    ApproveRequest,
    DocumentResponse,
    EvidenceResponse,
    ExtractJobResponse,
    ExtractResult,
    NeedsInputResponse,
    NodeCompileFailure,
    NodeCompileRequest,
    NodeCompileSuccess,
    NodeVersionDetail,
    OperationResponse,
    OperationsResponse,
    ResolutionOption,
    ResolveRequest,
    ResolvedResponse,
    ResumeRequest,
    SourceCreate,
    SourceResponse,
)
from .openapi import OpenAPIIngestError, Operation, ingest, operation_from_mapping
from .resolve import ResolutionStatus, resolve_operation
from .store import (
    Document,
    ExtractedSpec,
    Job,
    JobResumeError,
    NodeVersion,
    NodeVersionUpdateError,
    Source,
    Store,
    new_id,
)

# Generous for hand-written OpenAPI docs, but bounds ingest cost against a
# hostile upload (unbounded read + yaml.safe_load are otherwise a resource-
# exhaustion vector: safe_load blocks code execution, not memory/CPU blowup
# from adversarial anchor/alias expansion).
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


def _operation_model(operation: Operation) -> OperationResponse:
    return OperationResponse(**asdict(operation))


def _source_model(source: Source) -> SourceResponse:
    return SourceResponse(id=source.id, name=source.name, base_url=source.base_url, auth_kind=source.auth_kind)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code,
        "message": message,
        "request_id": f"req_{uuid4().hex}",
    }})


def create_app() -> FastAPI:
    app = FastAPI(title="Ferrule compiler", version="4c")
    store = Store()
    # A fresh dev keypair per process, matching every other piece of state
    # in this service (CredentialStore, ArtifactCache, ...): deliberately
    # in-memory and ephemeral until real signing-key custody exists. Real
    # production custody (HSM-backed, rotated, audited) is a separate,
    # much larger concern than this milestone's scope -- reusing phase-0's
    # generate_dev_keypair()/sign() means the actual cryptography is the
    # same code path production would use, only the key's storage differs.
    signing_private_key, signing_public_key = generate_dev_keypair()

    # Milestone 3a is deliberately process-local and unscoped. Workspace API-key
    # authentication belongs with the later multi-tenant workspace model.
    @app.exception_handler(APIError)
    async def api_error_handler(_request: Request, error: APIError) -> JSONResponse:
        return _error(error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, error: RequestValidationError) -> JSONResponse:
        return _error(400, "malformed_request", str(error))

    def require_source(source_id: str) -> Source:
        source = store.get_source(source_id)
        if source is None:
            raise APIError(404, "source_not_found", f"source {source_id} was not found")
        return source

    def require_spec(source_id: str) -> ExtractedSpec:
        require_source(source_id)
        spec = store.latest_spec_for(source_id)
        if spec is None:
            raise APIError(409, "source_not_extracted", "source has no extracted OpenAPI document")
        return spec

    def _compile_and_store(
        source: Source, spec: ExtractedSpec, operation: Operation
    ) -> NodeCompileSuccess | NodeCompileFailure:
        # Shared by POST /nodes/compile's direct-resolve path and
        # resume_job's kind="compile" path, so the two can never diverge
        # in how a resolved operation actually gets compiled and recorded.
        result: CompileResult = compile_operation(source.base_url, operation)
        # CLAUDE.md invariant 9: plan_coverage is recorded on every compile
        # attempt, including failures -- returned directly here, not
        # folded into a generic error message, so it stays visible.
        if result.plan is None or result.input_schema is None or result.output_schema is None:
            return NodeCompileFailure(plan_coverage="not_representable", reasons=list(result.reasons))
        artifact_hash = compute_artifact_hash(build_artifact(result.plan))
        node_version = NodeVersion(
            id=new_id("nv"),
            node_id=new_id("nd"),
            semver="1.0.0",
            status="proposed",
            artifact_hash=artifact_hash,
            source_id=source.id,
            source_document_id=spec.document_id,
            operation=operation,
            plan=result.plan,
            input_schema=result.input_schema,
            output_schema=result.output_schema,
            coverage=result.coverage,
            limitations=result.limitations,
        )
        store.put_node_version(node_version)
        assert result.coverage != "not_representable"  # guaranteed above by the result.plan is None check
        return NodeCompileSuccess(
            node_version_id=node_version.id,
            status="proposed",
            artifact_hash=artifact_hash,
            plan_coverage=result.coverage,
            evidence_url=f"/nodes/{node_version.node_id}/versions/{node_version.semver}/evidence",
        )

    @app.post("/sources", status_code=201, response_model=SourceResponse)
    def create_source(body: SourceCreate) -> SourceResponse:
        source = Source(new_id("src"), body.name, body.base_url, body.auth_kind)
        store.put_source(source)
        return _source_model(source)

    @app.get("/sources/{source_id}", response_model=SourceResponse)
    def get_source(source_id: str) -> SourceResponse:
        return _source_model(require_source(source_id))

    @app.post("/sources/{source_id}/documents", status_code=201, response_model=DocumentResponse)
    async def upload_document(
        source_id: str,
        kind: Literal["openapi", "prose_doc", "example_payload"] = Form(...),
        file: UploadFile = File(...),
    ) -> DocumentResponse:
        require_source(source_id)
        raw = await file.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise APIError(413, "document_too_large", f"document exceeds the {MAX_DOCUMENT_BYTES}-byte limit")
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        document = Document(new_id("doc"), source_id, kind, raw, digest)
        store.put_document(document)
        return DocumentResponse(id=document.id, sha256=digest, kind=kind)

    @app.get("/sources/{source_id}/documents/{document_id}")
    def get_document_bytes(source_id: str, document_id: str) -> Response:
        # Raw bytes, not a JSON envelope: this is the same content originally
        # uploaded, needed by callers (e.g. claims.extract_claims) that must
        # resolve a source span back into the raw document -- otherwise the
        # only artifact of an upload a caller can ever get back is its digest.
        require_source(source_id)
        document = store.get_document(document_id)
        if document is None or document.source_id != source_id:
            raise APIError(404, "document_not_found", f"document {document_id} was not found")
        return Response(content=document.raw, media_type="application/octet-stream")

    @app.post("/sources/{source_id}/extract", status_code=202, response_model=ExtractJobResponse)
    def extract_source(source_id: str) -> ExtractJobResponse:
        require_source(source_id)
        documents = [item for item in store.documents_for(source_id) if item.kind == "openapi"]
        if not documents:
            raise APIError(409, "openapi_document_missing", "source has no OpenAPI document")
        used_document = documents[-1]
        try:
            parsed = ingest(used_document.raw)
        except OpenAPIIngestError as error:
            raise APIError(422, "openapi_invalid", str(error)) from error
        spec = ExtractedSpec(
            new_id("spec"), source_id, used_document.id, parsed.source_hash, parsed.openapi_version, parsed.operations
        )
        store.put_spec(spec)
        result = ExtractResult(
            extracted_spec_id=spec.id,
            confidence=1.0,  # Deterministic parse; probabilistic claim confidence starts in 3c.
            operations_found=len(spec.operations),
            claims=0,  # Source-linked claim extraction is milestone 3c.
        )
        job = Job(new_id("job"), "extract", "succeeded", result.model_dump())
        store.put_job(job)
        return ExtractJobResponse(job_id=job.id, status="succeeded", poll_url=f"/jobs/{job.id}", result=result)

    @app.get("/sources/{source_id}/operations", response_model=OperationsResponse)
    def list_operations(source_id: str) -> OperationsResponse:
        # Deliberate API.md extension: milestone 3a requires extracted operations to be queryable.
        spec = require_spec(source_id)
        return OperationsResponse(data=[_operation_model(item) for item in spec.operations])

    @app.post("/sources/{source_id}/resolve", status_code=202)
    def resolve(source_id: str, body: ResolveRequest) -> ResolvedResponse | NeedsInputResponse:
        spec = require_spec(source_id)
        resolution = resolve_operation(body.task, spec.operations)
        if resolution.status is ResolutionStatus.NO_MATCH:
            raise APIError(422, "operation_not_found", "no operation plausibly matches the task")
        if resolution.status is ResolutionStatus.RESOLVED:
            assert resolution.operation is not None
            job = Job(
                new_id("job"),
                "resolve",
                "succeeded",
                {"operation": asdict(resolution.operation)},
            )
            store.put_job(job)
            return ResolvedResponse(
                job_id=job.id,
                status="succeeded",
                poll_url=f"/jobs/{job.id}",
                operation=_operation_model(resolution.operation),
            )
        job = Job(new_id("job"), "resolve", "needs_input", options=resolution.candidates)
        store.put_job(job)
        return NeedsInputResponse(
            status="needs_input",
            question=f"Multiple operations match '{body.task}'.",
            options=[ResolutionOption(operation_id=item.operation_id, path=item.path) for item in resolution.candidates],
            resume_url=f"/jobs/{job.id}/resume",
        )

    @app.post("/nodes/compile", status_code=202)
    def compile_node(body: NodeCompileRequest) -> NodeCompileSuccess | NodeCompileFailure | NeedsInputResponse:
        source = require_source(body.source_id)
        spec = require_spec(body.source_id)
        resolution = resolve_operation(body.task, spec.operations)
        if resolution.status is ResolutionStatus.NO_MATCH:
            raise APIError(422, "operation_not_found", "no operation plausibly matches the task")
        if resolution.status is ResolutionStatus.RESOLVED:
            assert resolution.operation is not None
            return _compile_and_store(source, spec, resolution.operation)
        job = Job(new_id("job"), "compile", "needs_input", options=resolution.candidates, source_id=body.source_id)
        store.put_job(job)
        return NeedsInputResponse(
            status="needs_input",
            question=f"Multiple operations match '{body.task}'.",
            options=[ResolutionOption(operation_id=item.operation_id, path=item.path) for item in resolution.candidates],
            resume_url=f"/jobs/{job.id}/resume",
        )

    @app.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
    ) -> ExtractJobResponse | ResolvedResponse | NodeCompileSuccess | NodeCompileFailure | NeedsInputResponse:
        job = store.get_job(job_id)
        if job is None:
            raise APIError(404, "job_not_found", f"job {job_id} was not found")
        if job.kind == "extract" and job.status == "succeeded" and job.result is not None:
            return ExtractJobResponse(
                job_id=job.id,
                status="succeeded",
                poll_url=f"/jobs/{job.id}",
                result=ExtractResult.model_validate(job.result),
            )
        if job.kind == "resolve" and job.status == "succeeded" and job.result is not None:
            operation_data = job.result.get("operation")
            return ResolvedResponse(
                job_id=job.id,
                status="succeeded",
                poll_url=f"/jobs/{job.id}",
                operation=OperationResponse.model_validate(operation_data),
            )
        if job.kind == "compile" and job.status == "succeeded" and job.result is not None:
            outcome = cast(Mapping[str, object], job.result["compile_outcome"])
            if "node_version_id" in outcome:
                return NodeCompileSuccess.model_validate(outcome)
            return NodeCompileFailure.model_validate(outcome)
        if job.kind == "compile" and job.status == "failed":
            # Terminal, not resumable -- resume_job's except-Exception
            # branch above already put it here after finishing the
            # ambiguity resolution but failing to complete the compile.
            raise APIError(500, "compile_failed", "this node failed to compile; retry via POST /nodes/compile")
        return NeedsInputResponse(
            status="needs_input",
            question="Choose one matching operation.",
            options=[ResolutionOption(operation_id=item.operation_id, path=item.path) for item in job.options],
            resume_url=f"/jobs/{job.id}/resume",
        )

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str, body: ResumeRequest) -> ResolvedResponse | NodeCompileSuccess | NodeCompileFailure:
        try:
            job = store.resume_needs_input(job_id, body.choice)
        except JobResumeError as error:
            if error.reason == "not_found":
                raise APIError(404, "job_not_found", f"job {job_id} was not found") from error
            if error.reason == "not_resumable":
                raise APIError(409, "job_not_resumable", "job does not need input") from error
            raise APIError(422, "invalid_operation_choice", "choice is not one of the job options") from error
        assert job.result is not None
        if job.kind == "compile":
            assert job.source_id is not None
            # resume_needs_input above already committed this job as
            # "succeeded" (atomically, single-use) once the ambiguity was
            # resolved -- but resolving the choice and finishing the
            # compile are two different things, and everything from here
            # down can still fail. Without this try/except, any exception
            # here (confirmed by reproduction: even require_source/
            # require_spec or an unexpected compile_operation failure)
            # left the job permanently stuck -- already consumed so it
            # can never be resumed again, and unpollable, since get_job's
            # kind="compile" branch indexes job.result["compile_outcome"],
            # which only this block ever writes. The immediate caller also
            # got a raw, unhandled 500 instead of a clean error envelope.
            try:
                source = require_source(job.source_id)
                spec = require_spec(job.source_id)
                operation = operation_from_mapping(cast(Mapping[str, object], job.result["operation"]))
                outcome = _compile_and_store(source, spec, operation)
            except APIError:
                store.put_job(Job(job.id, "compile", "failed", {"error": "compile could not be completed"}))
                raise
            except Exception as error:
                store.put_job(Job(job.id, "compile", "failed", {"error": str(error)}))
                raise APIError(
                    500, "compile_failed", "an unexpected error occurred while compiling this node"
                ) from error
            store.put_job(Job(job.id, "compile", "succeeded", {"compile_outcome": outcome.model_dump()}))
            return outcome
        return ResolvedResponse(
            job_id=job.id,
            status="succeeded",
            poll_url=f"/jobs/{job.id}",
            operation=OperationResponse.model_validate(job.result["operation"]),
        )

    @app.get("/nodes/{node_id}/versions/{semver}/evidence", response_model=EvidenceResponse)
    def get_evidence(node_id: str, semver: str) -> EvidenceResponse:
        node_version = store.get_node_version(node_id, semver)
        if node_version is None:
            raise APIError(404, "node_version_not_found", f"node {node_id} version {semver} was not found")
        document = store.get_document(node_version.source_document_id)
        if document is None:
            raise APIError(404, "document_not_found", "node version's source document no longer exists")
        result = CompileResult(
            coverage=node_version.coverage,
            plan=node_version.plan,
            input_schema=node_version.input_schema,
            output_schema=node_version.output_schema,
            limitations=node_version.limitations,
        )
        claims = extract_claims(document.raw, node_version.operation, result)
        sample_input = golden_case(node_version.input_schema).input
        mock_result = run_mock_case(node_version.plan, golden_case(node_version.input_schema))
        evidence = assemble_evidence(
            node_id=node_version.node_id,
            semver=node_version.semver,
            status=node_version.status,
            artifact_hash=node_version.artifact_hash,
            operation=node_version.operation,
            result=result,
            sample_input=sample_input,
            claims=claims,
            source_document_id=document.id,
            source_hash=document.sha256,
            mock_result=mock_result,
        )
        return EvidenceResponse.model_validate(evidence)

    def _node_version_model(node_version: NodeVersion) -> NodeVersionDetail:
        return NodeVersionDetail(
            node_version_id=node_version.id,
            node_id=node_version.node_id,
            semver=node_version.semver,
            status=node_version.status,
            artifact_hash=node_version.artifact_hash,
            plan=node_version.plan,
            signature=node_version.signature,
            public_key_pem=node_version.public_key_pem,
            approved_at=node_version.approved_at,
            reviewer_note=node_version.reviewer_note,
        )

    @app.get("/nodes/{node_id}/versions/{semver}", response_model=NodeVersionDetail)
    def get_node_version_detail(node_id: str, semver: str) -> NodeVersionDetail:
        # Deliberate API.md extension, same rationale as 3a's
        # GET /sources/{id}/operations: the evidence bundle deliberately
        # doesn't expose the raw plan (only derived schemas and a rendered
        # preview), so `ferrule node verify` needs a separate place to
        # fetch the exact bytes a signature was computed over.
        node_version = store.get_node_version(node_id, semver)
        if node_version is None:
            raise APIError(404, "node_version_not_found", f"node {node_id} version {semver} was not found")
        return _node_version_model(node_version)

    @app.post("/nodes/{node_id}/versions/{semver}/approve", response_model=ApprovalResponse)
    def approve_node_version(node_id: str, semver: str, body: ApproveRequest) -> ApprovalResponse:
        node_version = store.get_node_version(node_id, semver)
        if node_version is None:
            raise APIError(404, "node_version_not_found", f"node {node_id} version {semver} was not found")
        artifact_bytes = build_artifact(node_version.plan)
        signature = encode_signature(sign(artifact_bytes, signing_private_key))
        public_key_pem = signing_public_key.decode("ascii")
        approved_at = datetime.now(timezone.utc).isoformat()
        try:
            approved = store.approve_node_version(
                node_id, semver, signature, public_key_pem, approved_at, body.reviewer_note
            )
        except NodeVersionUpdateError as error:
            if error.reason == "not_found":
                raise APIError(404, "node_version_not_found", f"node {node_id} version {semver} was not found") from error
            # "already_approved" is the only other reason approve_node_version
            # raises; API.md: "409 if already approved" -- approval is a
            # one-time transition, never a silent re-sign of the same version.
            raise APIError(409, "already_approved", "this node version has already been approved") from error
        assert approved.signature is not None and approved.public_key_pem is not None
        assert approved.approved_at is not None and approved.reviewer_note is not None
        return ApprovalResponse(
            node_version_id=approved.id,
            node_id=approved.node_id,
            semver=approved.semver,
            status="approved",
            artifact_hash=approved.artifact_hash,
            plan=approved.plan,
            signature=approved.signature,
            public_key_pem=approved.public_key_pem,
            approved_at=approved.approved_at,
            reviewer_note=approved.reviewer_note,
        )

    return app


app = create_app()
