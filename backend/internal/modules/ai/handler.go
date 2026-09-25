package ai

import (
	"context"
	"errors"
	"net/http"

	"github.com/abdelrahmanAhmed1x/core/httpx"
	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/gin-gonic/gin"
)

type ChatService interface {
	Chat(context.Context, ChatRequest) (ChatResponse, error)
}

type Handler struct {
	service ChatService
	log     logger.Logger
}

func NewHandler(service ChatService, log logger.Logger) *Handler {
	return &Handler{service: service, log: log}
}

func (h *Handler) Chat(c *gin.Context) {
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 16<<10)
	req, ok := httpx.BindJSON[ChatRequest](c)
	if !ok {
		return
	}
	response, err := h.service.Chat(c.Request.Context(), req)
	if err == nil {
		httpx.OK(c, response)
		return
	}
	switch {
	case errors.Is(err, ErrInvalidRequest):
		httpx.AbortBadRequest(c, err.Error(), nil)
	case errors.Is(err, ErrSessionNotFound):
		httpx.AbortNotFound(c, "Chat session not found")
	default:
		h.log.Error(c.Request.Context(), "AI chat failed", "error", err)
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
			"success": false,
			"error":   gin.H{"code": "SERVICE_UNAVAILABLE", "message": "The assistant is temporarily unavailable"},
		})
	}
}
