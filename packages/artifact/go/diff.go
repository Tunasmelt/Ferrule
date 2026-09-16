package artifact

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"reflect"
	"sort"
	"strings"
)

type SchemaChange struct {
	Port   string `json:"port"`
	Field  string `json:"field"`
	Change string `json:"change"`
	Type   any    `json:"type,omitempty"`
	From   any    `json:"from,omitempty"`
	To     any    `json:"to,omitempty"`
}

type ValueChange struct {
	Step  string `json:"step,omitempty"`
	Field string `json:"field"`
	From  any    `json:"from"`
	To    any    `json:"to"`
}

type DiffResult struct {
	SchemaChanges     []SchemaChange `json:"schema_changes"`
	PlanChanges       []ValueChange  `json:"plan_changes"`
	CapabilityChanges []ValueChange  `json:"capability_changes"`
	Breaking          bool           `json:"breaking"`
	BreakingReason    *string        `json:"breaking_reason"`
}

func manifest(value any) (map[string]any, error) {
	var data []byte
	switch value := value.(type) {
	case []byte:
		data = value
	case string:
		data = []byte(value)
	default:
		var err error
		data, err = json.Marshal(value)
		if err != nil {
			return nil, fmt.Errorf("encode manifest: %w", err)
		}
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var object map[string]any
	if err := decoder.Decode(&object); err != nil {
		return nil, err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("multiple JSON values")
		}
		return nil, err
	}
	if object == nil {
		return nil, errors.New("manifest must be a JSON object")
	}
	return object, nil
}

func object(value any) map[string]any {
	if value, ok := value.(map[string]any); ok {
		return value
	}
	return map[string]any{}
}

func sortedUnion(left, right map[string]any) []string {
	set := make(map[string]struct{}, len(left)+len(right))
	for key := range left {
		set[key] = struct{}{}
	}
	for key := range right {
		set[key] = struct{}{}
	}
	keys := make([]string, 0, len(set))
	for key := range set {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func fieldTypes(schema any, prefix string) map[string]any {
	result := map[string]any{}
	properties := object(object(schema)["properties"])
	for _, name := range sortedUnion(properties, nil) {
		fieldSchema := object(properties[name])
		path := name
		if prefix != "" {
			path = prefix + "." + name
		}
		nested := fieldTypes(fieldSchema, path)
		if len(nested) > 0 {
			for key, value := range nested {
				result[key] = value
			}
		} else {
			result[path] = fieldSchema["type"]
		}
	}
	return result
}

func requiredAddition(portSchema any, field string) bool {
	required, exists := object(portSchema)["required"]
	values, ok := required.([]any)
	if !exists || !ok {
		return true
	}
	top := strings.SplitN(field, ".", 2)[0]
	for _, value := range values {
		if value == top {
			return true
		}
	}
	return false
}

func schemaDiff(old, new map[string]any) ([]SchemaChange, *string) {
	oldPorts := object(object(old["output_schema"])["ports"])
	newPorts := object(object(new["output_schema"])["ports"])
	changes := []SchemaChange{}
	var reason *string
	for _, port := range sortedUnion(oldPorts, newPorts) {
		oldFields, newFields := fieldTypes(oldPorts[port], ""), fieldTypes(newPorts[port], "")
		for _, field := range sortedUnion(oldFields, newFields) {
			oldType, inOld := oldFields[field]
			newType, inNew := newFields[field]
			switch {
			case !inOld:
				changes = append(changes, SchemaChange{Port: port, Field: field, Change: "added", Type: newType})
				if _, portExisted := oldPorts[port]; portExisted && requiredAddition(newPorts[port], field) && reason == nil {
					value := fmt.Sprintf("output port '%s' gained a required field", port)
					reason = &value
				}
			case !inNew:
				changes = append(changes, SchemaChange{Port: port, Field: field, Change: "removed", Type: oldType})
				if reason == nil {
					value := fmt.Sprintf("output port '%s' lost field '%s'", port, field)
					reason = &value
				}
			case !reflect.DeepEqual(oldType, newType):
				changes = append(changes, SchemaChange{Port: port, Field: field, Change: "type_changed", From: oldType, To: newType})
				if reason == nil {
					value := fmt.Sprintf("output port '%s' field '%s' changed type", port, field)
					reason = &value
				}
			}
		}
	}
	return changes, reason
}

func leafChanges(old map[string]any, new map[string]any, prefix string) []ValueChange {
	changes := []ValueChange{}
	for _, key := range sortedUnion(old, new) {
		path := key
		if prefix != "" {
			path = prefix + "." + key
		}
		before, inOld := old[key]
		after, inNew := new[key]
		oldObject, oldIsObject := before.(map[string]any)
		newObject, newIsObject := after.(map[string]any)
		if oldIsObject && newIsObject {
			changes = append(changes, leafChanges(oldObject, newObject, path)...)
		} else if !inOld || !inNew || !reflect.DeepEqual(before, after) {
			changes = append(changes, ValueChange{Field: path, From: before, To: after})
		}
	}
	return changes
}

func planSteps(value any) map[string]map[string]any {
	result := map[string]map[string]any{}
	steps, _ := object(value)["steps"].([]any)
	for _, raw := range steps {
		step := object(raw)
		id, ok := step["id"].(string)
		if ok {
			result[id] = step
		}
	}
	return result
}

func planDiff(old, new map[string]any) []ValueChange {
	oldSteps, newSteps := planSteps(old["plan"]), planSteps(new["plan"])
	oldKeys, newKeys := map[string]any{}, map[string]any{}
	for key := range oldSteps {
		oldKeys[key] = nil
	}
	for key := range newSteps {
		newKeys[key] = nil
	}
	result := []ValueChange{}
	for _, id := range sortedUnion(oldKeys, newKeys) {
		oldStep, newStep := map[string]any{}, map[string]any{}
		for key, value := range oldSteps[id] {
			if key != "id" {
				oldStep[key] = value
			}
		}
		for key, value := range newSteps[id] {
			if key != "id" {
				newStep[key] = value
			}
		}
		changes := leafChanges(oldStep, newStep, "")
		for index := range changes {
			changes[index].Step = id
		}
		result = append(result, changes...)
	}
	return result
}

// Diff compares the externally meaningful schema, plan, and capability blocks.
func Diff(oldManifest, newManifest any) (DiffResult, error) {
	old, err := manifest(oldManifest)
	if err != nil {
		return DiffResult{}, err
	}
	new, err := manifest(newManifest)
	if err != nil {
		return DiffResult{}, err
	}
	schemaChanges, reason := schemaDiff(old, new)
	return DiffResult{
		SchemaChanges:     schemaChanges,
		PlanChanges:       planDiff(old, new),
		CapabilityChanges: leafChanges(object(old["capabilities"]), object(new["capabilities"]), ""),
		Breaking:          reason != nil,
		BreakingReason:    reason,
	}, nil
}
