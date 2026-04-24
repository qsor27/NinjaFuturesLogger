package main

import (
	"context"
	"net"
	"testing"
	"time"
)

func TestWaitForServer_SucceedsWhenServerIsUp(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	port := l.Addr().(*net.TCPAddr).Port

	go func() {
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			c.Close()
		}
	}()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := WaitForServer(ctx, port); err != nil {
		t.Errorf("WaitForServer returned error: %v", err)
	}
}

func TestWaitForServer_TimesOutWhenServerIsDown(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	if err := WaitForServer(ctx, 1); err == nil {
		t.Errorf("WaitForServer returned nil, expected timeout error")
	}
}
