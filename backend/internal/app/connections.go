package app

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/typesense/typesense-go/v3/typesense"
)

type TypesenseConfig struct {
	URL    string
	APIKey string
}

func InitPostgres(parent context.Context, url string) (*pgxpool.Pool, error) {
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	poolConfig, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("parse postgres config: %w", err)
	}
	poolConfig.MaxConns = 12
	poolConfig.MinIdleConns = 2
	poolConfig.MaxConnIdleTime = 10 * time.Minute
	poolConfig.MaxConnLifetime = time.Hour
	poolConfig.MaxConnLifetimeJitter = 10 * time.Minute
	poolConfig.HealthCheckPeriod = time.Minute
	poolConfig.PingTimeout = 5 * time.Second
	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return nil, fmt.Errorf("create postgres pool: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}
	return pool, nil
}

func InitTypesense(ctx context.Context, cfg TypesenseConfig) (*typesense.Client, error) {
	client := typesense.NewClient(
		typesense.WithServer(cfg.URL), typesense.WithAPIKey(cfg.APIKey),
		typesense.WithConnectionTimeout(5*time.Second),
		typesense.WithCircuitBreakerMaxRequests(50),
		typesense.WithCircuitBreakerInterval(2*time.Minute),
		typesense.WithCircuitBreakerTimeout(time.Minute),
		typesense.WithHealthcheckInterval(10*time.Second),
	)
	ok, err := client.Health(ctx, 5*time.Second)
	if err != nil {
		return nil, fmt.Errorf("check typesense health: %w", err)
	}
	if !ok {
		return nil, fmt.Errorf("typesense is unhealthy")
	}
	return client, nil
}

func InitDBs(ctx context.Context, url string, cfg TypesenseConfig) (*pgxpool.Pool, *typesense.Client, error) {
	postgres, err := InitPostgres(ctx, url)
	if err != nil {
		return nil, nil, err
	}
	typesenseClient, err := InitTypesense(ctx, TypesenseConfig{URL: cfg.URL, APIKey: cfg.APIKey})
	if err != nil {
		postgres.Close()
		return nil, nil, err
	}
	return postgres, typesenseClient, nil

}
