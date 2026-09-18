"""FastAPI surface for compiler ingest and deterministic operation resolution."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import (
    DocumentResponse,
    ExtractJobResponse,
    ExtractResult,
    NeedsInputResponse,
    OperationResponse,
    OperationsResponse,
    ResolutionOption,
    ResolveRequest,
    ResolvedResponse,
    ResumeRequest,
    SourceCreate,
    SourceResponse,
)
from .openapi import OpenAPIIngestError, Operation, ingest
from .resolve import ResolutionStatus, resolve_operation
from .store import Document, ExtractedSpec, Job, Source, Store, new_id


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


def _operation_model(operation: Operation) -> OperationResponse:
    return OperationResponse(**asdict(operation))


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code,
        "message": message,
        "request_id": f"req_{uuid4().hex}",
    }})


def create_app() -> FastAPI:
    app = FastAPI(title="Ferrule compiler", version="3a")
    store = Store()

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

    @app.post("/sources", status_code=201, response_model=SourceResponse)
    def create_source(body: SourceCreate) -> SourceResponse:
        source = Source(new_id("src"), body.name, body.base_url, body.auth_kind)
        store.put_source(source)
        return SourceResponse(id=source.id)

    @app.post("/sources/{source_id}/documents", status_code=201, response_model=DocumentResponse)
    async def upload_document(
        source_id: str,
        kind: Literal["openapi", "prose_doc", "example_payload"] = Form(...),
        file: UploadFile = File(...),
    ) -> DocumentResponse:
        require_source(source_id)
        raw = await file.read()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        document = Document(new_id("doc"), source_id, kind, raw, digest)
        store.put_document(document)
        return DocumentResponse(id=document.id, sha256=digest, kind=kind)

    @app.post("/sources/{source_id}/extract", status_code=202, response_model=ExtractJobResponse)
    def extract_source(source_id: str) -> ExtractJobResponse:
        require_source(source_id)
        documents = [item for item in store.documents_for(source_id) if item.kind == "openapi"]
        if not documents:
            raise APIError(409, "openapi_document_missing", "source has no OpenAPI document")
        try:
            parsed = ingest(documents[-1].raw)
        except OpenAPIIngestError as error:
            raise APIError(422, "openapi_invalid", str(error)) from error
        spec = ExtractedSpec(new_id("spec"), source_id, parsed.source_hash, parsed.openapi_version, parsed.operations)
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

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> ExtractJobResponse | ResolvedResponse | NeedsInputResponse:
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
        return NeedsInputResponse(
            status="needs_input",
            question="Choose one matching operation.",
            options=[ResolutionOption(operation_id=item.operation_id, path=item.path) for item in job.options],
            resume_url=f"/jobs/{job.id}/resume",
        )

    @app.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str, body: ResumeRequest) -> ResolvedResponse:
        job = store.get_job(job_id)
        if job is None:
            raise APIError(404, "job_not_found", f"job {job_id} was not found")
        if job.status != "needs_input":
            raise APIError(409, "job_not_resumable", "job does not need input")
        selected = next((item for item in job.options if item.operation_id == body.choice), None)
        if selected is None:
            raise APIError(422, "invalid_operation_choice", "choice is not one of the job options")
        store.put_job(Job(job.id, "resolve", "succeeded", {"operation": asdict(selected)}))
        return ResolvedResponse(
            job_id=job.id,
            status="succeeded",
            poll_url=f"/jobs/{job.id}",
            operation=_operation_model(selected),
        )

    return app


app = create_app()
