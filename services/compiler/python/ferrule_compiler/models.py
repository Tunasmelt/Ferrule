"""Pydantic v2 boundary models for the milestone 3a HTTP API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCreate(StrictModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    auth_kind: Literal["api_key", "bearer"]


class SourceResponse(StrictModel):
    id: str
    spec_status: Literal["none"] = "none"


class DocumentResponse(StrictModel):
    id: str
    sha256: str
    kind: Literal["openapi", "prose_doc", "example_payload"]


class ExtractResult(StrictModel):
    extracted_spec_id: str
    confidence: float
    operations_found: int
    claims: int


class ExtractJobResponse(StrictModel):
    job_id: str
    status: Literal["succeeded"]
    poll_url: str
    result: ExtractResult


class ParameterResponse(StrictModel):
    name: str
    location: str
    required: bool
    schema_type: str


class OperationResponse(StrictModel):
    operation_id: str
    method: str
    path: str
    summary: str
    description: str
    tags: list[str]
    parameters: list[ParameterResponse]


class OperationsResponse(StrictModel):
    data: list[OperationResponse]


class ResolveRequest(StrictModel):
    task: str = Field(min_length=1)


class ResolvedResponse(StrictModel):
    job_id: str
    status: Literal["succeeded"]
    poll_url: str
    operation: OperationResponse


class ResolutionOption(StrictModel):
    operation_id: str
    path: str


class NeedsInputResponse(StrictModel):
    status: Literal["needs_input"]
    question: str
    options: list[ResolutionOption]
    resume_url: str


class ResumeRequest(StrictModel):
    choice: str = Field(min_length=1)
