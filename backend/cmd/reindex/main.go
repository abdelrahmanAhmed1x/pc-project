package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"pc/internal/app"
	"pc/internal/modules/products"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	cfg, err := app.Load()
	if err != nil {
		return fmt.Errorf("load configuration: %w", err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	pg, ts, err := app.InitDBs(ctx, cfg.DatabaseURL, app.TypesenseConfig{URL: cfg.TypesenseURL, APIKey: cfg.TypesenseAPIKey})
	if err != nil {
		return fmt.Errorf("initialize databases: %w", err)
	}
	defer pg.Close()
	if err := products.ReindexProducts(ctx, pg, ts); err != nil {
		return fmt.Errorf("reindex products: %w", err)
	}
	return nil
}
