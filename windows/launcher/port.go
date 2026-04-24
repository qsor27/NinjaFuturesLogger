package main

import (
	"fmt"
	"net"
)

// TryBind verifies that a TCP listener can be opened on 127.0.0.1:port.
// Returns nil on success (listener is closed immediately; the port is free
// but not held). Returns an error describing the conflict on failure.
func TryBind(port int) error {
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	l, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("port %d is in use: %w", port, err)
	}
	_ = l.Close()
	return nil
}
