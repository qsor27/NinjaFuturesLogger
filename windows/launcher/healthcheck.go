package main

import (
	"context"
	"fmt"
	"net"
	"time"
)

// WaitForServer polls 127.0.0.1:port via TCP connect every 200 ms until the
// context is canceled. Returns nil when a connection succeeds (the server
// is accepting connections), or the context error if the context is done
// before that happens.
func WaitForServer(ctx context.Context, port int) error {
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	ticker := time.NewTicker(200 * time.Millisecond)
	defer ticker.Stop()

	if canConnect(addr) {
		return nil
	}

	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("server did not respond on %s: %w", addr, ctx.Err())
		case <-ticker.C:
			if canConnect(addr) {
				return nil
			}
		}
	}
}

func canConnect(addr string) bool {
	c, err := net.DialTimeout("tcp", addr, 100*time.Millisecond)
	if err != nil {
		return false
	}
	_ = c.Close()
	return true
}
