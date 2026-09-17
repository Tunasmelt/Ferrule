package proxy

import "testing"

func TestRenderRequestEscapesDeleteInBody(t *testing.T) {
	step := map[string]any{
		"method":  "POST",
		"url":     "https://x.test",
		"headers": map[string]any{},
		"body":    map[string]any{"v": "\x7f"},
	}

	got, err := RenderRequest(step, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := `{"method":"POST","url":"https://x.test","headers":{"Content-Type":"application/json"},"body":{"v":"\u007f"}}`
	if string(got) != want {
		t.Fatalf("got  %s\nwant %s", got, want)
	}
}

func TestRenderRequestHeaderCollisionUsesValueTieBreak(t *testing.T) {
	tests := []struct {
		name    string
		headers map[string]any
	}{
		{
			name: "lowercase key inserted first",
			headers: func() map[string]any {
				headers := make(map[string]any)
				headers["x-a"] = "lower"
				headers["X-A"] = "upper"
				return headers
			}(),
		},
		{
			name: "uppercase key inserted first",
			headers: func() map[string]any {
				headers := make(map[string]any)
				headers["X-A"] = "upper"
				headers["x-a"] = "lower"
				return headers
			}(),
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			step := map[string]any{
				"method":  "GET",
				"url":     "https://x.test",
				"headers": test.headers,
			}
			got, err := RenderRequest(step, nil, nil)
			if err != nil {
				t.Fatal(err)
			}
			want := `{"method":"GET","url":"https://x.test","headers":{"X-A":"upper"},"body":null}`
			if string(got) != want {
				t.Fatalf("got  %s\nwant %s", got, want)
			}
		})
	}
}
