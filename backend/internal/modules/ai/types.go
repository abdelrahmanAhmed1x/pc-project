package ai

import (
	"errors"
	"strings"
)

var (
	ErrInvalidRequest  = errors.New("invalid chat request")
	ErrSessionNotFound = errors.New("chat session not found")
	ErrUnavailable     = errors.New("AI assistant unavailable")
)

type ChatRequest struct {
	SessionID string `json:"session_id"`
	Message   string `json:"message" binding:"required"`
}

type ChatResponse struct {
	SessionID      string               `json:"session_id"`
	Message        string               `json:"message"`
	Products       []RecommendedProduct `json:"products"`
	EstimatedTotal *Money               `json:"estimated_total,omitempty"`
}

type Money struct {
	Amount   string `json:"amount"`
	Currency string `json:"currency"`
}

type RecommendedProduct struct {
	ID                  int64   `json:"id"`
	Name                string  `json:"name"`
	Price               string  `json:"price"`
	Currency            string  `json:"currency"`
	InStock             *bool   `json:"in_stock"`
	Provider            string  `json:"provider"`
	CanonicalProductURL string  `json:"canonical_product_url"`
	ImageURL            *string `json:"image_url,omitempty"`
}

type ClassificationStatus string

const (
	ClassificationValid     ClassificationStatus = "valid"
	ClassificationInvalid   ClassificationStatus = "invalid"
	ClassificationUncertain ClassificationStatus = "uncertain"
)

type Classification struct {
	Status     ClassificationStatus `json:"status"`
	Confidence float64              `json:"confidence"`
	Reason     string               `json:"reason"`
}

func (c Classification) valid() bool {
	if c.Confidence < 0 || c.Confidence > 1 || strings.TrimSpace(c.Reason) == "" {
		return false
	}
	switch c.Status {
	case ClassificationValid, ClassificationInvalid, ClassificationUncertain:
		return true
	default:
		return false
	}
}

type assistantAnswer struct {
	Message    string  `json:"message"`
	ProductIDs []int64 `json:"product_ids"`
}
