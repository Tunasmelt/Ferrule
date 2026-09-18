package proxy

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sync"

	artifact "ferrule/packages/artifact/go"
)

// JournalEntry.Context is the canonical envelope {"input": ..., "previous":
// ...} -- NOT just the raw workflow input. A step's URL/header/body
// templates can reference {{ response.x }}, which the Python interpreter
// binds to the PREVIOUS step's mapped output (see interpreter.py's
// `previous` variable), not the live HTTP response of the current step.
// Real fixtures already depend on this (tests/fixtures/plans/valid/
// cursor.json uses "{{ response.next_cursor }}" for pagination). The
// journal must record both, and the digest must cover both, or the proxy's
// independent re-render silently diverges from what the worker actually
// executed the moment a step depends on prior-step output.
//
// NodeVersionHash and StepID bind this entry to the specific artifact and
// step it was journaled for. Found missing during a whole-phase audit: a
// journal keyed by (run_id, step_seq) alone lets Authorize borrow one
// step's journaled input to authorize a COMPLETELY DIFFERENT artifact or
// step, as long as the caller supplies the same (run_id, step_seq) and the
// digest that was actually stored for it -- reproduced directly, a
// destructive step in one artifact was fully authorized using a read-only
// step's journal entry from a different artifact, sharing only the run_id/
// step_seq/digest. Authorize checks these two fields match the request
// before proceeding, closing that substitution.
type JournalEntry struct {
	Context         json.RawMessage
	Digest          string
	NodeVersionHash string
	StepID          string
}

type RunJournal interface {
	RecordInput(runID string, stepSeq int, nodeVersionHash, stepID string, input, previous json.RawMessage) (JournalEntry, error)
	LookupInput(runID string, stepSeq int) (JournalEntry, bool)
}

type journalKey struct {
	runID   string
	stepSeq int
}

type MemoryRunJournal struct {
	mu      sync.RWMutex
	entries map[journalKey]JournalEntry
}

func NewMemoryRunJournal() *MemoryRunJournal {
	return &MemoryRunJournal{entries: make(map[journalKey]JournalEntry)}
}

func (journal *MemoryRunJournal) RecordInput(runID string, stepSeq int, nodeVersionHash, stepID string, input, previous json.RawMessage) (JournalEntry, error) {
	if len(previous) == 0 {
		previous = json.RawMessage("{}")
	}
	envelope, err := json.Marshal(map[string]json.RawMessage{"input": input, "previous": previous})
	if err != nil {
		return JournalEntry{}, err
	}
	canonical, err := artifact.Canonicalize(envelope)
	if err != nil {
		return JournalEntry{}, err
	}
	digest := sha256.Sum256(canonical)
	entry := JournalEntry{
		Context:         append(json.RawMessage(nil), canonical...),
		Digest:          "sha256:" + hex.EncodeToString(digest[:]),
		NodeVersionHash: nodeVersionHash,
		StepID:          stepID,
	}
	key := journalKey{runID, stepSeq}
	journal.mu.Lock()
	defer journal.mu.Unlock()
	if _, exists := journal.entries[key]; exists {
		return JournalEntry{}, errors.New("run journal entry already exists")
	}
	journal.entries[key] = entry
	return cloneEntry(entry), nil
}

func (journal *MemoryRunJournal) LookupInput(runID string, stepSeq int) (JournalEntry, bool) {
	journal.mu.RLock()
	defer journal.mu.RUnlock()
	entry, ok := journal.entries[journalKey{runID, stepSeq}]
	return cloneEntry(entry), ok
}

func cloneEntry(entry JournalEntry) JournalEntry {
	entry.Context = append(json.RawMessage(nil), entry.Context...)
	return entry
}
