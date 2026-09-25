package ai

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/gin-gonic/gin"
	"google.golang.org/adk/v2/agent/llmagent"
	"google.golang.org/adk/v2/model/openaimodel"
	"google.golang.org/adk/v2/runner"
	"google.golang.org/adk/v2/session"
	"google.golang.org/adk/v2/session/database"
	"google.golang.org/genai"
	"gorm.io/driver/postgres"
)

type Config struct {
	BaseURL        string
	Model          string
	APIKey         string
	Timeout        time.Duration
	SessionStorage string // memory or postgres
	DatabaseURL    string
}

// RegisterRoutes builds the model, tools, agents, runners, and session service once.
func RegisterRoutes(ctx context.Context, router gin.IRouter, catalog Catalog, cfg Config, log logger.Logger) error {
	if cfg.BaseURL == "" || cfg.Model == "" {
		return fmt.Errorf("AI_BASE_URL and AI_MODEL are required")
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 180 * time.Second
	}
	sessions, err := newSessions(cfg)
	if err != nil {
		return err
	}
	model, err := openaimodel.NewModel(ctx, cfg.Model, &openaimodel.ClientConfig{
		APIKey: cfg.APIKey, BaseURL: cfg.BaseURL,
		HTTPClient: &http.Client{Timeout: cfg.Timeout},
	})
	if err != nil {
		return fmt.Errorf("create AI model: %w", err)
	}
	tools, err := newCatalogTools(catalog)
	if err != nil {
		return err
	}
	classifierTemp, assistantTemp := float32(0), float32(0.25)
	noThinking := int32(0)
	classifier, err := llmagent.New(llmagent.Config{
		Name: "buying_domain_classifier", Description: "Classifies whether the current message is about technology buying.",
		Model: model, Instruction: classifierInstruction,
		GenerateContentConfig: &genai.GenerateContentConfig{Temperature: &classifierTemp, MaxOutputTokens: 512,
			ResponseMIMEType: "application/json", ResponseSchema: classificationSchema(),
			ThinkingConfig: &genai.ThinkingConfig{ThinkingBudget: &noThinking}},
	})
	if err != nil {
		return fmt.Errorf("create classifier agent: %w", err)
	}
	assistant, err := llmagent.New(llmagent.Config{
		Name: "technology_buying_assistant", Description: "Finds real catalog listings and helps choose technology products.",
		Model: model, Instruction: assistantInstruction, Tools: tools,
		GenerateContentConfig: &genai.GenerateContentConfig{Temperature: &assistantTemp, MaxOutputTokens: 2048,
			ThinkingConfig: &genai.ThinkingConfig{ThinkingBudget: &noThinking}},
	})
	if err != nil {
		return fmt.Errorf("create technology assistant agent: %w", err)
	}
	classifierRunner, err := runner.New(runner.Config{AppName: classifierApp, Agent: classifier, SessionService: sessions})
	if err != nil {
		return fmt.Errorf("create classifier runner: %w", err)
	}
	assistantRunner, err := runner.New(runner.Config{AppName: assistantApp, Agent: assistant, SessionService: sessions})
	if err != nil {
		return fmt.Errorf("create assistant runner: %w", err)
	}
	handler := NewHandler(newService(sessions, classifierRunner, assistantRunner), log)
	router.Group("/ai").POST("/chat", handler.Chat)
	return nil
}

func newSessions(cfg Config) (session.Service, error) {
	switch cfg.SessionStorage {
	case "", "memory":
		return session.InMemoryService(), nil
	case "postgres":
		if cfg.DatabaseURL == "" {
			return nil, fmt.Errorf("DATABASE_URL is required for AI_SESSION_STORAGE=postgres")
		}
		service, err := database.NewSessionService(postgres.Open(cfg.DatabaseURL))
		if err != nil {
			return nil, fmt.Errorf("create ADK database sessions: %w", err)
		}
		if err := database.AutoMigrate(service); err != nil {
			return nil, fmt.Errorf("migrate ADK session tables: %w", err)
		}
		return service, nil
	default:
		return nil, fmt.Errorf("unknown AI_SESSION_STORAGE %q", cfg.SessionStorage)
	}
}

func classificationSchema() *genai.Schema {
	return &genai.Schema{Type: genai.TypeObject,
		Properties: map[string]*genai.Schema{
			"status":     {Type: genai.TypeString, Enum: []string{"valid", "invalid", "uncertain"}},
			"confidence": {Type: genai.TypeNumber},
			"reason":     {Type: genai.TypeString},
		}, Required: []string{"status", "confidence", "reason"},
	}
}
