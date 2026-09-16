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
	decoder := json.NewDecoder(bytes.NewReader(input))
	decoder.UseNumber()
	var value any
	if err := decoder.Decode(&value); err != nil {
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
