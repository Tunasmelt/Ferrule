package proxy

import (
	"bytes"
	"sort"
)

const redactionPlaceholder = "[REDACTED]"

// Redact returns a copy with every non-empty secret value removed. This is
// an exact byte-substring search: it cannot catch a secret value an
// upstream has re-encoded before echoing it back (URL-encoded, base64,
// case-folded, and so on -- an unbounded set not worth chasing here). It
// does additionally search for each value's JSON-string-escaped form
// (using the same escaper ResolveSecrets uses to embed values into a JSON
// request), since JSON is this proxy's own expected response format and an
// upstream reflecting a credential inside its own JSON response commonly
// re-escapes characters like a literal quote -- found and reproduced during
// the 2c audit: a credential containing a `"` survived redaction when an
// upstream echoed it back JSON-escaped as `\"`, because the raw-value
// search never matches the escaped substring.
//
// Values (raw and escaped) are replaced longest-first so an overlapping
// shorter value cannot expose a suffix of a longer credential.
func Redact(data []byte, secretValues []string) []byte {
	variants := make([]string, 0, len(secretValues)*2)
	for _, value := range secretValues {
		if value == "" {
			continue
		}
		variants = append(variants, value)
		if escaped := jsonStringContent(value); escaped != value {
			variants = append(variants, escaped)
		}
	}
	sort.Slice(variants, func(i, j int) bool { return len(variants[i]) > len(variants[j]) })
	redacted := append([]byte(nil), data...)
	for _, variant := range variants {
		redacted = bytes.ReplaceAll(redacted, []byte(variant), []byte(redactionPlaceholder))
	}
	return redacted
}

// jsonStringContent returns value as it would appear inside a JSON string
// literal, without the surrounding quotes -- the same escaping
// writePythonString (render.go) uses to embed a value into JSON.
func jsonStringContent(value string) string {
	var buffer bytes.Buffer
	writePythonString(&buffer, value)
	quoted := buffer.String()
	return quoted[1 : len(quoted)-1]
}
