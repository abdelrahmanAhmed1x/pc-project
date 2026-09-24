package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"pc/internal/app"

	"github.com/abdelrahmanAhmed1x/core/logger"
)

func main() {
	startupLog := logger.New(logger.Config{Level: "info", Format: "json", MaskSensitives: true})
	if err := run(); err != nil {
		startupLog.Error(context.Background(), "application stopped", "error", err)
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
	a, err := app.New(ctx, cfg)
	if err != nil {
		return fmt.Errorf("initialize application: %w", err)
	}
	defer a.Close()
	serverErr := make(chan error, 1)
	go func() { serverErr <- a.Server.ListenAndServe() }()
	a.Log.Info(ctx, "server listening", "addr", a.Server.Addr)
	select {
	case err = <-serverErr:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("serve HTTP: %w", err)
		}
	case <-ctx.Done():
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := a.Server.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shutdown HTTP server: %w", err)
	}
	return nil
}
