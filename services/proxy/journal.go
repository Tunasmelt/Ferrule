package proxy

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sync"

	artifact "ferrule/packages/artifact/go"
)

type JournalEntry struct {
	Input  json.RawMessage
	Digest string
}

type RunJournal interface {
	RecordInput(runID string, stepSeq int, input json.RawMessage) (JournalEntry, error)
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

func (journal *MemoryRunJournal) RecordInput(runID string, stepSeq int, input json.RawMessage) (JournalEntry, error) {
	canonical, err := artifact.Canonicalize(input)
	if err != nil {
		return JournalEntry{}, err
	}
	digest := sha256.Sum256(canonical)
	entry := JournalEntry{Input: append(json.RawMessage(nil), canonical...), Digest: "sha256:" + hex.EncodeToString(digest[:])}
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
	entry.Input = append(json.RawMessage(nil), entry.Input...)
	return entry
}
