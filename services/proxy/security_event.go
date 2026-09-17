package proxy

// SecurityEvent is a denial emitted by a proxy authorization check.
type SecurityEvent struct {
	Code            string `json:"code"`
	Reason          string `json:"reason"`
	NodeVersionHash string `json:"node_version_hash"`
	RunID           string `json:"run_id"`
	StepSeq         int    `json:"step_seq"`
	StepID          string `json:"step_id"`
}
