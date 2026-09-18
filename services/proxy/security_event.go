package proxy

// SecurityEvent is a denial emitted by a proxy authorization check.
//
// FailureClass is one of SPEC.md section 7's named classes
// ("permission_denied" for every denial in this package -- an unauthorized
// or policy-violating request is exactly what that class means: no retry,
// route to permanent_error, raise a security event). Found missing during
// a whole-phase audit: this field did not exist at all, so a caller had no
// SPEC-defined signal to route on for most denials, only this package's
// own Code strings.
type SecurityEvent struct {
	Code            string `json:"code"`
	FailureClass    string `json:"failure_class"`
	Reason          string `json:"reason"`
	NodeVersionHash string `json:"node_version_hash"`
	RunID           string `json:"run_id"`
	StepSeq         int    `json:"step_seq"`
	StepID          string `json:"step_id"`
}
