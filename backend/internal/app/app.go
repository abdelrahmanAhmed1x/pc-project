package app

import (
	"context"
	"fmt"
	"net/http"
	"pc/internal/modules/products"
	"time"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/typesense/typesense-go/v3/typesense"
)

type App struct {
	Config    *Config
	Log       logger.Logger
	Postgres  *pgxpool.Pool
	Typesense *typesense.Client
	Server    *http.Server
}

func New(ctx context.Context, cfg *Config) (*App, error) {
	log := logger.New(logger.Config{Level: "info", Format: "json", MaskSensitives: true})
	pg, ts, err := InitDBs(ctx, cfg.DatabaseURL, TypesenseConfig{
		URL:    cfg.TypesenseURL,
		APIKey: cfg.TypesenseAPIKey,
	})
	if err != nil {
		return nil, err
	}
	engine := Server(cfg, log)
	products.RegisterRoutes(engine, pg, log)
	return &App{
		Config: cfg, Log: log, Postgres: pg, Typesense: ts,
		Server: &http.Server{
			Addr: fmt.Sprintf(":%d", cfg.Port), Handler: engine,
			ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second,
			WriteTimeout: 35 * time.Second, IdleTimeout: 60 * time.Second,
		},
	}, nil
}

func (a *App) Close() { a.Postgres.Close() }
