package artifact

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

var ErrNonCanonical = errors.New("value cannot be represented as canonical JSON")

func Canonicalize(input []byte) ([]byte, error) {
	if !utf8.Valid(input) {
		return nil, fmt.Errorf("%w: input is not UTF-8", ErrNonCanonical)
	}
	if err := rejectUnpairedSurrogateEscapes(input); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrNonCanonical, err)
	}
	decoder := json.NewDecoder(bytes.NewReader(input))
	decoder.UseNumber()
	value, err := decodeValue(decoder)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrNonCanonical, err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		if err != nil {
			return nil, fmt.Errorf("%w: %v", ErrNonCanonical, err)
		}
		return nil, fmt.Errorf("%w: multiple JSON values", ErrNonCanonical)
	}
	var output bytes.Buffer
	if err := encode(&output, value); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

// rejectUnpairedSurrogateEscapes scans raw JSON text for \uXXXX escapes
// inside string literals and rejects a lone UTF-16 surrogate half.
// encoding/json silently substitutes U+FFFD for these instead of erroring,
// which lets it accept input Python's canonicalizer rejects -- a
// cross-language acceptance-domain mismatch. This must run on the raw
// bytes: by the time json.Decoder hands back a decoded string, an invalid
// escape has already been silently replaced, indistinguishable from a
// legitimate literal U+FFFD character in the source.
func rejectUnpairedSurrogateEscapes(input []byte) error {
	inString := false
	for i := 0; i < len(input); i++ {
		b := input[i]
		if !inString {
			if b == '"' {
				inString = true
			}
			continue
		}
		switch b {
		case '"':
			inString = false
		case '\\':
			if i+1 >= len(input) {
				return nil // malformed; let json.Decoder report the real error
			}
			if input[i+1] != 'u' {
				i++ // any other one-char escape (\\, \", \n, ...)
				continue
			}
			if i+6 > len(input) {
				return nil
			}
			code, err := strconv.ParseUint(string(input[i+2:i+6]), 16, 32)
			if err != nil {
				return nil // malformed hex; let json.Decoder report it
			}
			r := rune(code)
			switch {
			case r >= 0xD800 && r <= 0xDBFF: // high surrogate: needs a paired low next
				if i+12 <= len(input) && input[i+6] == '\\' && input[i+7] == 'u' {
					if code2, err2 := strconv.ParseUint(string(input[i+8:i+12]), 16, 32); err2 == nil {
						if r2 := rune(code2); r2 >= 0xDC00 && r2 <= 0xDFFF {
							i += 11 // consume both \uXXXX\uXXXX (loop's i++ adds the 12th)
							continue
						}
					}
				}
				return fmt.Errorf("unpaired UTF-16 surrogate escape")
			case r >= 0xDC00 && r <= 0xDFFF: // low surrogate with no preceding high
				return fmt.Errorf("unpaired UTF-16 surrogate escape")
			}
			i += 5 // consume \uXXXX (loop's i++ adds the 6th)
		}
	}
	return nil
}

func decodeValue(decoder *json.Decoder) (any, error) {
	token, err := decoder.Token()
	if err != nil {
		return nil, err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return token, nil
	}
	switch delimiter {
	case '{':
		value := make(map[string]any)
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return nil, err
			}
			key := keyToken.(string)
			if _, exists := value[key]; exists {
				return nil, fmt.Errorf("duplicate object key: %q", key)
			}
			item, err := decodeValue(decoder)
			if err != nil {
				return nil, err
			}
			value[key] = item
		}
		_, err = decoder.Token()
		return value, err
	case '[':
		value := make([]any, 0)
		for decoder.More() {
			item, err := decodeValue(decoder)
			if err != nil {
				return nil, err
			}
			value = append(value, item)
		}
		_, err = decoder.Token()
		return value, err
	default:
		return nil, fmt.Errorf("unexpected delimiter %q", delimiter)
	}
}

func encode(output *bytes.Buffer, value any) error {
	switch value := value.(type) {
	case nil:
		output.WriteString("null")
	case bool:
		output.WriteString(strconv.FormatBool(value))
	case string:
		writeString(output, value)
	case json.Number:
		number, err := normalizeNumber(string(value))
		if err != nil {
			return err
		}
		output.WriteString(number)
	case []any:
		output.WriteByte('[')
		for index, item := range value {
			if index > 0 {
				output.WriteByte(',')
			}
			if err := encode(output, item); err != nil {
				return err
			}
		}
		output.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(value))
		for key := range value {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		output.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				output.WriteByte(',')
			}
			writeString(output, key)
			output.WriteByte(':')
			if err := encode(output, value[key]); err != nil {
				return err
			}
		}
		output.WriteByte('}')
	default:
		return fmt.Errorf("%w: unsupported type %T", ErrNonCanonical, value)
	}
	return nil
}

func writeString(output *bytes.Buffer, value string) {
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
			if char < 0x20 {
				fmt.Fprintf(output, `\u%04x`, char)
			} else {
				output.WriteRune(char)
			}
		}
	}
	output.WriteByte('"')
}

func normalizeNumber(value string) (string, error) {
	negative := strings.HasPrefix(value, "-")
	if negative {
		value = value[1:]
	}
	exponent := 0
	if index := strings.IndexAny(value, "eE"); index >= 0 {
		parsed, err := strconv.Atoi(value[index+1:])
		if err != nil {
			return "", fmt.Errorf("%w: invalid number", ErrNonCanonical)
		}
		exponent, value = parsed, value[:index]
	}
	fraction := 0
	if index := strings.IndexByte(value, '.'); index >= 0 {
		fraction = len(value) - index - 1
		value = value[:index] + value[index+1:]
	}
	value = strings.TrimLeft(value, "0")
	if value == "" {
		return "0", nil
	}
	scale := fraction - exponent
	for scale > 0 && strings.HasSuffix(value, "0") {
		value = value[:len(value)-1]
		scale--
	}
	var result string
	if scale <= 0 {
		result = value + strings.Repeat("0", -scale)
	} else if scale >= len(value) {
		result = "0." + strings.Repeat("0", scale-len(value)) + value
	} else {
		result = value[:len(value)-scale] + "." + value[len(value)-scale:]
	}
	if negative {
		result = "-" + result
	}
	return result, nil
}
