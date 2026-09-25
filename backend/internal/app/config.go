package app

import (
	"fmt"
	"time"

	"github.com/caarlos0/env/v11"
	"github.com/joho/godotenv"
)

type Config struct {
	DatabaseURL          string        `env:"DATABASE_URL,required"`
	TypesenseURL         string        `env:"TYPESENSE_URL,required"`
	TypesenseAPIKey      string        `env:"TYPESENSE_API_KEY,required"`
	Port                 int           `env:"PORT" envDefault:"8082"`
	CORSOrigins          []string      `env:"CORS_ALLOWED_ORIGINS" envDefault:"*"`
	CORSAllowCredentials bool          `env:"CORS_ALLOW_CREDENTIALS" envDefault:"false"`
	AIBaseURL            string        `env:"AI_BASE_URL,required"`
	AIModel              string        `env:"AI_MODEL,required"`
	AIAPIKey             string        `env:"AI_API_KEY"`
	AITimeout            time.Duration `env:"AI_TIMEOUT" envDefault:"180s"`
	AISessionStorage     string        `env:"AI_SESSION_STORAGE" envDefault:"memory"`
}

func Load() (*Config, error) {
	_ = godotenv.Load()
	cfg, err := env.ParseAs[Config]()
	if err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

func (c *Config) Validate() error {
	if c.Port < 1 || c.Port > 65535 {
		return fmt.Errorf("PORT must be between 1 and 65535")
	}
	if c.AITimeout < 0 || c.AITimeout > 10*time.Minute {
		return fmt.Errorf("AI_TIMEOUT must be between 0 and 10 minutes")
	}
	if c.AISessionStorage != "" && c.AISessionStorage != "memory" && c.AISessionStorage != "postgres" {
		return fmt.Errorf("AI_SESSION_STORAGE must be memory or postgres")
	}
	if len(c.CORSOrigins) == 0 {
		return fmt.Errorf("CORS_ALLOWED_ORIGINS must contain at least one origin")
	}
	for _, origin := range c.CORSOrigins {
		if origin == "*" {
			if c.CORSAllowCredentials || len(c.CORSOrigins) != 1 {
				return fmt.Errorf("wildcard CORS origin must be used alone without credentials")
			}
		} else if origin == "" {
			return fmt.Errorf("CORS_ALLOWED_ORIGINS contains an empty origin")
		}
	}
	return nil
}
