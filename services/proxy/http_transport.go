package proxy

import (
	"bytes"
	"io"
	"net/http"
	"strings"
)

// NewHTTPTransport returns a Transport backed by net/http. It copies the
// supplied client before disabling automatic redirects so Forward always sees
// and enforces each redirect itself; the caller's client is not mutated.
func NewHTTPTransport(client *http.Client) Transport {
	if client == nil {
		client = http.DefaultClient
	}
	configured := *client
	configured.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}

	return func(outbound OutboundRequest, maxResponseBytes int) (OutboundResponse, error) {
		var body io.Reader
		if outbound.Body != nil {
			body = bytes.NewReader(outbound.Body)
		}
		request, err := http.NewRequest(outbound.Method, outbound.URL, body)
		if err != nil {
			return OutboundResponse{}, err
		}
		for name, value := range outbound.Headers {
			request.Header.Set(name, value)
		}

		response, err := configured.Do(request)
		if err != nil {
			return OutboundResponse{}, err
		}
		defer response.Body.Close()
		responseBody, err := BoundedRead(response.Body, maxResponseBytes)
		if err != nil {
			return OutboundResponse{}, err
		}
		headers := make(map[string]string, len(response.Header))
		for name, values := range response.Header {
			// OutboundResponse has one value per name, so preserve all wire
			// values in their received order using the RFC list separator.
			headers[name] = strings.Join(values, ", ")
		}
		return OutboundResponse{Status: response.StatusCode, Headers: headers, Body: responseBody}, nil
	}
}
