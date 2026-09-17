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
	Port       string `json:"port"`
	Field      string `json:"field"`
	Change     string `json:"change"`
	Constraint string `json:"constraint,omitempty"`
	Type       any    `json:"type,omitempty"`
	From       any    `json:"from,omitempty"`
	To         any    `json:"to,omitempty"`
}

// New cross-language change values: became_required, became_optional,
// constraint_changed, and port_removed.
var constraints = []string{"enum", "const", "pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "additionalProperties"}

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
			result[path] = fieldSchema
		}
	}
	return result
}

func requiredField(portSchema any, field string) bool {
	required, ok := object(portSchema)["required"].([]any)
	if !ok {
		return false
	}
	top := strings.SplitN(field, ".", 2)[0]
	for _, value := range required {
		if value == top {
			return true
		}
	}
	return false
}

func enumContains(values any, target any) bool {
	items, ok := values.([]any)
	if !ok {
		return false
	}
	for _, item := range items {
		if reflect.DeepEqual(item, target) {
			return true
		}
	}
	return false
}

func number(value any) (float64, bool) {
	switch value := value.(type) {
	case int:
		return float64(value), true
	case float64:
		return value, true
	case json.Number:
		parsed, err := value.Float64()
		return parsed, err == nil
	default:
		return 0, false
	}
}

func constraintTightened(name string, old any, oldExists bool, new any, newExists bool) bool {
	if !newExists {
		return false
	}
	if !oldExists {
		return name != "additionalProperties" || !reflect.DeepEqual(new, true)
	}
	if name == "enum" {
		if values, ok := old.([]any); ok {
			for _, value := range values {
				if !enumContains(new, value) {
					return true
				}
			}
			return false
		}
	}
	oldNumber, oldIsNumber := number(old)
	newNumber, newIsNumber := number(new)
	if oldIsNumber && newIsNumber {
		if name == "minimum" || name == "exclusiveMinimum" {
			return newNumber > oldNumber
		}
		if name == "maximum" || name == "exclusiveMaximum" {
			return newNumber < oldNumber
		}
	}
	if name == "additionalProperties" {
		return !reflect.DeepEqual(old, false) && !reflect.DeepEqual(new, true)
	}
	return !reflect.DeepEqual(old, new)
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
		if _, exists := newPorts[port]; !exists {
			changes = append(changes, SchemaChange{Port: port, Field: "", Change: "port_removed"})
			if reason == nil {
				value := fmt.Sprintf("output port '%s' was removed", port)
				reason = &value
			}
			continue
		}
		oldFields, newFields := fieldTypes(oldPorts[port], ""), fieldTypes(newPorts[port], "")
		for _, field := range sortedUnion(oldFields, newFields) {
			oldType, inOld := oldFields[field]
			newType, inNew := newFields[field]
			switch {
			case !inOld:
				changes = append(changes, SchemaChange{Port: port, Field: field, Change: "added", Type: object(newType)["type"]})
				if _, portExisted := oldPorts[port]; portExisted && requiredAddition(newPorts[port], field) && reason == nil {
					value := fmt.Sprintf("output port '%s' gained a required field", port)
					reason = &value
				}
			case !inNew:
				changes = append(changes, SchemaChange{Port: port, Field: field, Change: "removed", Type: object(oldType)["type"]})
				if reason == nil {
					value := fmt.Sprintf("output port '%s' lost field '%s'", port, field)
					reason = &value
				}
			default:
				oldField, newField := object(oldType), object(newType)
				if !reflect.DeepEqual(oldField["type"], newField["type"]) {
					changes = append(changes, SchemaChange{Port: port, Field: field, Change: "type_changed", From: oldField["type"], To: newField["type"]})
					if reason == nil {
						value := fmt.Sprintf("output port '%s' field '%s' changed type", port, field)
						reason = &value
					}
				}
				oldRequired, newRequired := requiredField(oldPorts[port], field), requiredField(newPorts[port], field)
				if oldRequired != newRequired {
					// Whole-field change values shared with Python: became_required/became_optional.
					change := "became_optional"
					if newRequired {
						change = "became_required"
					}
					changes = append(changes, SchemaChange{Port: port, Field: field, Change: change, From: oldRequired, To: newRequired})
					if newRequired && reason == nil {
						value := fmt.Sprintf("output port '%s' field '%s' became required", port, field)
						reason = &value
					}
				}
				for _, constraint := range constraints {
					before, beforeExists := oldField[constraint]
					after, afterExists := newField[constraint]
					if beforeExists == afterExists && reflect.DeepEqual(before, after) {
						continue
					}
					// Field-constraint changes use constraint_changed in both implementations.
					changes = append(changes, SchemaChange{Port: port, Field: field, Change: "constraint_changed", Constraint: constraint, From: before, To: after})
					if constraintTightened(constraint, before, beforeExists, after, afterExists) && reason == nil {
						value := fmt.Sprintf("output port '%s' field '%s' constraint '%s' tightened", port, field, constraint)
						reason = &value
					}
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
