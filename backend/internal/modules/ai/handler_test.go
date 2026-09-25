package ai

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/gin-gonic/gin"
)

type chatStub struct {
	request ChatRequest
	err     error
}

func (s *chatStub) Chat(_ context.Context, request ChatRequest) (ChatResponse, error) {
	s.request = request
	return ChatResponse{SessionID: "session", Message: "Hello", Products: []RecommendedProduct{}}, s.err
}

func TestChatHandlerEnvelopeAndErrors(t *testing.T) {
	gin.SetMode(gin.TestMode)
	service := &chatStub{}
	router := gin.New()
	router.POST("/ai/chat", NewHandler(service, logger.New(logger.Config{Output: io.Discard})).Chat)
	newRequest := func(body string) *http.Request {
		request := httptest.NewRequest(http.MethodPost, "/ai/chat", strings.NewReader(body))
		request.Header.Set("Content-Type", "application/json")
		return request
	}
	request := newRequest(`{"message":"Find an RX 9070"}`)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, request)
	if w.Code != http.StatusOK || service.request.Message != "Find an RX 9070" ||
		!strings.Contains(w.Body.String(), `"products":[]`) {
		t.Fatalf("chat response: status=%d body=%s", w.Code, w.Body.String())
	}
	service.err = ErrSessionNotFound
	w = httptest.NewRecorder()
	router.ServeHTTP(w, newRequest(`{"message":"Find an RX 9070"}`))
	if w.Code != http.StatusNotFound {
		t.Fatalf("missing session status=%d", w.Code)
	}
	service.err = errors.New("model failed")
	w = httptest.NewRecorder()
	router.ServeHTTP(w, newRequest(`{"message":"Find an RX 9070"}`))
	if w.Code != http.StatusServiceUnavailable || strings.Contains(w.Body.String(), "model failed") {
		t.Fatalf("internal error leaked: status=%d body=%s", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	router.ServeHTTP(w, newRequest(`{"message":""}`))
	if w.Code != http.StatusBadRequest {
		t.Fatalf("empty message status=%d", w.Code)
	}
}
