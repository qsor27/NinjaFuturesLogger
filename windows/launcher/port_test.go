package main

import (
	"net"
	"testing"
)

func TestTryBind_SucceedsOnFreePort(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	l.Close()

	if err := TryBind(port); err != nil {
		t.Errorf("TryBind on free port returned error: %v", err)
	}
}

func TestTryBind_FailsWhenPortIsHeld(t *testing.T) {
	held, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	port := held.Addr().(*net.TCPAddr).Port

	if err := TryBind(port); err == nil {
		t.Errorf("TryBind on held port returned nil, expected error")
	}
}
