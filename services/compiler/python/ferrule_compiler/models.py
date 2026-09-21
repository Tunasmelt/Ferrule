"""Pydantic v2 boundary models for the milestone 3a/4b/4c HTTP API."""

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
    name: str
    base_url: str
    auth_kind: Literal["api_key", "bearer"]
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


class NodeCompileConstraints(StrictModel):
    methods: list[str] | None = None
    side_effect_profile: str | None = None


class NodeCompileRequest(StrictModel):
    source_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    execution_class: Literal["trigger", "action", "transform", "condition", "terminal"] = "action"
    sandbox_credential_ref: str | None = None
    constraints: NodeCompileConstraints | None = None


class NodeCompileSuccess(StrictModel):
    node_version_id: str
    status: Literal["proposed"]
    artifact_hash: str
    plan_coverage: Literal["representable", "representable_partial"]
    evidence_url: str


class NodeCompileFailure(StrictModel):
    # CLAUDE.md invariant 9 / API.md: "plan_coverage is always present,
    # including on failure" -- a not_representable compile is reported
    # here, not folded into the generic error envelope, so plan_coverage
    # stays a first-class, always-visible field rather than one more
    # detail buried in an error message.
    status: Literal["failed"] = "failed"
    plan_coverage: Literal["not_representable"]
    reasons: list[str]


class RequestPreviewEntry(StrictModel):
    step_id: str
    method: str
    url: str
    headers: dict[str, str]
    rendered_from: dict[str, dict[str, object]]


class EvidenceCapabilities(StrictModel):
    hosts: list[str]
    methods: list[str]
    secrets: list[str]
    egress_default: str


class Assumption(StrictModel):
    claim: str
    basis: str
    source_document_id: str
    source_span: list[int]


class StaticVerification(StrictModel):
    passed: bool
    checks: list[str]


class MockVerification(StrictModel):
    passed: bool
    cases: int


class SandboxVerification(StrictModel):
    passed: bool
    cases: int
    account: str | None


class PermissionVerification(StrictModel):
    passed: bool
    attempted_violations: int


class Verification(StrictModel):
    static: StaticVerification
    mock: MockVerification
    sandbox: SandboxVerification
    permission: PermissionVerification


class TraceEntry(StrictModel):
    case: str
    trace_url: str


class Provenance(StrictModel):
    source_documents: list[str]
    compiler_version: str
    builder_model: str
    prompt_version: str
    plan_coverage: str


class EvidenceResponse(StrictModel):
    artifact_hash: str
    status: str
    behaviour_summary: str
    request_preview: list[RequestPreviewEntry]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    capabilities: EvidenceCapabilities
    side_effect_profile: str
    assumptions: list[Assumption]
    verification: Verification
    traces: list[TraceEntry]
    provenance: Provenance


class ApproveRequest(StrictModel):
    reviewer_note: str = Field(min_length=1)


class ApprovalResponse(StrictModel):
    node_version_id: str
    node_id: str
    semver: str
    status: Literal["approved"]
    artifact_hash: str
    # The exact canonical bytes ferrule_artifact.build() would reproduce
    # from this plan, and the detached signature/key over them -- reused
    # directly by `ferrule node verify` (phase-0's verify(), not a
    # reimplementation) rather than a bespoke approval-token format.
    plan: dict[str, object]
    signature: str
    public_key_pem: str
    approved_at: str
    reviewer_note: str


class NodeVersionDetail(StrictModel):
    """A node version's own record -- distinct from the human-facing evidence
    bundle, and the one place the raw `plan` is exposed (evidence.md's
    schema deliberately doesn't include it, only derived input/output
    schemas and a rendered preview) so `ferrule node verify` can
    reconstruct and check a signature without needing a locally-saved copy.
    """

    node_version_id: str
    node_id: str
    semver: str
    status: str
    artifact_hash: str
    plan: dict[str, object]
    signature: str | None
    public_key_pem: str | None
    approved_at: str | None
    reviewer_note: str | None
