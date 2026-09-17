package proxy

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
)

var marker = regexp.MustCompile(`{{\s*((?:input|response|secret)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*}}`)

func render(template string, input, response map[string]any) string {
	return marker.ReplaceAllStringFunc(template, func(match string) string {
		path := marker.FindStringSubmatch(match)[1]
		parts := strings.Split(path, ".")
		if parts[0] == "secret" {
			return "{{ " + path + " }}"
		}
		var value any = input
		if parts[0] == "response" {
			value = response
		}
		for _, part := range parts[1:] {
			mapping, ok := value.(map[string]any)
			if !ok {
				return ""
			}
			value, ok = mapping[part]
			if !ok {
				return ""
			}
		}
		return pythonString(value)
	})
}

func pythonString(value any) string {
	switch value := value.(type) {
	case nil:
		return "None"
	case bool:
		return strconv.FormatBool(value)
	case string:
		return value
	case json.Number:
		return string(value)
	default:
		return fmt.Sprint(value)
	}
}

// RenderRequest returns the canonical JSON request shape used for comparison:
// method, URL, sorted normalized headers, and a raw JSON body or null.
func RenderRequest(step, input, response map[string]any) ([]byte, error) {
	method, ok := step["method"].(string)
	if !ok {
		return nil, errors.New("step method is not a string")
	}
	urlTemplate, ok := step["url"].(string)
	if !ok {
		return nil, errors.New("step URL is not a string")
	}
	renderedURL := render(urlTemplate, input, response)
	parsed, err := url.Parse(renderedURL)
	if err != nil {
		return nil, err
	}
	query := make(url.Values)
	for key, values := range parsed.Query() {
		if len(values) > 0 {
			query.Set(key, values[len(values)-1])
		}
	}
	if values, ok := step["query"].(map[string]any); ok {
		for key, value := range values {
			query.Set(key, render(pythonString(value), input, response))
		}
	}
	baseURL := strings.SplitN(renderedURL, "#", 2)[0]
	baseURL = strings.SplitN(baseURL, "?", 2)[0]
	canonicalURL := baseURL
	if encoded := query.Encode(); encoded != "" {
		canonicalURL += "?" + encoded
	}

	rawHeaders := make(map[string]string)
	if values, ok := step["headers"].(map[string]any); ok {
		keys := make([]string, 0, len(values))
		for key := range values {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		for _, key := range keys {
			value := values[key]
			rawHeaders[key] = render(pythonString(value), input, response)
		}
	}

	var body []byte
	addContentType := false
	if values, ok := step["body"].(map[string]any); ok {
		body = encodePythonJSONObject(values, input, response)
		if _, exists := rawHeaders["Content-Type"]; !exists {
			addContentType = true
		}
	}
	headers := make(map[string]string, len(rawHeaders))
	rawKeys := make([]string, 0, len(rawHeaders))
	for key := range rawHeaders {
		rawKeys = append(rawKeys, key)
	}
	sort.Strings(rawKeys)
	for _, key := range rawKeys {
		headers[pythonHeaderName(key)] = rawHeaders[key]
	}
	if addContentType {
		headers["Content-Type"] = "application/json"
	}

	var output bytes.Buffer
	output.WriteString(`{"method":`)
	writePythonString(&output, method)
	output.WriteString(`,"url":`)
	writePythonString(&output, canonicalURL)
	output.WriteString(`,"headers":{`)
	keys := sortedKeys(headers)
	for i, key := range keys {
		if i > 0 {
			output.WriteByte(',')
		}
		writePythonString(&output, key)
		output.WriteByte(':')
		writePythonString(&output, headers[key])
	}
	output.WriteString(`},"body":`)
	if body == nil {
		output.WriteString("null")
	} else {
		output.Write(body)
	}
	output.WriteByte('}')
	return output.Bytes(), nil
}

func pythonHeaderName(name string) string {
	parts := strings.Split(name, "-")
	for i, part := range parts {
		if part != "" {
			parts[i] = strings.ToUpper(part[:1]) + strings.ToLower(part[1:])
		}
	}
	return strings.Join(parts, "-")
}

func encodePythonJSONObject(values map[string]any, input, response map[string]any) []byte {
	var output bytes.Buffer
	output.WriteByte('{')
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for i, key := range keys {
		if i > 0 {
			output.WriteByte(',')
		}
		writePythonString(&output, key)
		output.WriteByte(':')
		writePythonString(&output, render(pythonString(values[key]), input, response))
	}
	output.WriteByte('}')
	return output.Bytes()
}

func writePythonString(output *bytes.Buffer, value string) {
	output.WriteByte('"')
	for _, char := range value {
		switch char {
		case '"', '\\':
			output.WriteByte('\\')
			output.WriteRune(char)
		case '\b':
			output.WriteString(`\b`)
		case '\f':
			output.WriteString(`\f`)
		case '\n':
			output.WriteString(`\n`)
		case '\r':
			output.WriteString(`\r`)
		case '\t':
			output.WriteString(`\t`)
		default:
			if char < 0x20 || char > 0x7f {
				if char > 0xffff {
					high, low := utf16.EncodeRune(char)
					fmt.Fprintf(output, `\u%04x\u%04x`, high, low)
				} else {
					fmt.Fprintf(output, `\u%04x`, char)
				}
			} else {
				output.WriteRune(char)
			}
		}
	}
	output.WriteByte('"')
}

func sortedKeys(values map[string]string) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
