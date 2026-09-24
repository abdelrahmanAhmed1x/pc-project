package app

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/abdelrahmanAhmed1x/core/logger"
)

func TestServerMiddleware(t *testing.T) {
	cfg := &Config{CORSOrigins: []string{"https://example.com"}, CORSAllowCredentials: true}
	router := Server(cfg, logger.New(logger.Config{Output: io.Discard}))

	req := httptest.NewRequest(http.MethodOptions, "/health", nil)
	req.Header.Set("Origin", "https://example.com")
	req.Header.Set("Access-Control-Request-Method", http.MethodGet)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent || w.Header().Get("Access-Control-Allow-Origin") != "https://example.com" || w.Header().Get("Access-Control-Allow-Credentials") != "true" {
		t.Fatalf("unexpected allowed preflight: status=%d headers=%v", w.Code, w.Header())
	}
	if w.Header().Get("X-Content-Type-Options") != "nosniff" || w.Header().Get("X-Request-ID") == "" {
		t.Fatalf("missing security or tracing headers: %v", w.Header())
	}

	req = httptest.NewRequest(http.MethodOptions, "/health", nil)
	req.Header.Set("Origin", "https://evil.example")
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusForbidden || w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("unexpected denied preflight: status=%d headers=%v", w.Code, w.Header())
	}

	req = httptest.NewRequest(http.MethodGet, "/health", nil)
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"status":"ok"`) {
		t.Fatalf("unexpected health response: status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestWildcardCORS(t *testing.T) {
	cfg := &Config{Port: 8082, CORSOrigins: []string{"*"}}
	if err := cfg.Validate(); err != nil {
		t.Fatal(err)
	}
	router := Server(cfg, logger.New(logger.Config{Output: io.Discard}))
	req := httptest.NewRequest(http.MethodOptions, "/health", nil)
	req.Header.Set("Origin", "https://any.example")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)
	if w.Code != http.StatusNoContent || w.Header().Get("Access-Control-Allow-Origin") != "*" || w.Header().Get("Access-Control-Allow-Credentials") != "" {
		t.Fatalf("unexpected wildcard preflight: status=%d headers=%v", w.Code, w.Header())
	}
	cfg.CORSAllowCredentials = true
	if cfg.Validate() == nil {
		t.Fatal("wildcard origin with credentials should fail validation")
	}
}
