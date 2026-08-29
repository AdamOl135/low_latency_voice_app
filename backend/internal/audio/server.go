package audio

import (
	"context"
	"fmt"
	"log"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// Server encapsulates the high-performance UDP media plane socket listener.
type Server struct {
	bindAddr string
	conn     *net.UDPConn
	router   *Router
	running  atomic.Bool
	stopChan chan struct{}
	wg       sync.WaitGroup
	ctx      context.Context
	cancel   context.CancelFunc
}

// NewServer initializes an audio UDP server listening on bindAddr.
func NewServer(bindAddr string, router *Router) *Server {
	if bindAddr == "" {
		bindAddr = fmt.Sprintf("0.0.0.0:%d", DefaultPort)
	}
	ctx, cancel := context.WithCancel(context.Background())
	return &Server{
		bindAddr: bindAddr,
		router:   router,
		stopChan: make(chan struct{}),
		ctx:      ctx,
		cancel:   cancel,
	}
}

// Start binds the UDP listener socket and launches the reader and cleanup loops.
func (s *Server) Start() error {
	udpAddr, err := net.ResolveUDPAddr("udp", s.bindAddr)
	if err != nil {
		return fmt.Errorf("audio: resolve UDP addr failed: %w", err)
	}

	conn, err := net.ListenUDP("udp", udpAddr)
	if err != nil {
		return fmt.Errorf("audio: listen UDP failed on %s: %w", s.bindAddr, err)
	}

	// Optimize socket buffer sizes for high throughput
	_ = conn.SetReadBuffer(4 * 1024 * 1024)  // 4MB read buffer
	_ = conn.SetWriteBuffer(4 * 1024 * 1024) // 4MB write buffer

	s.conn = conn
	s.router.SetWriter(conn)
	s.running.Store(true)

	log.Printf("[Audio SFU] UDP Server listening on %s (local: %s)", s.bindAddr, conn.LocalAddr())

	// Launch reader worker loop
	s.wg.Add(1)
	go s.readLoop()

	// Launch stale session scavenger loop
	s.wg.Add(1)
	go s.cleanupLoop()

	return nil
}

// Serve starts the server and blocks until the context is canceled or Close is called.
func (s *Server) Serve() error {
	if err := s.Start(); err != nil {
		return err
	}
	<-s.stopChan
	return nil
}

// Close gracefully terminates the UDP listener and releases network resources.
func (s *Server) Close() error {
	if !s.running.Swap(false) {
		return nil
	}

	s.cancel()
	close(s.stopChan)

	var err error
	if s.conn != nil {
		err = s.conn.Close()
	}

	s.wg.Wait()
	log.Printf("[Audio SFU] UDP Server shut down successfully")
	return err
}

// LocalAddr returns the bound network address of the UDP socket.
func (s *Server) LocalAddr() net.Addr {
	if s.conn == nil {
		return nil
	}
	return s.conn.LocalAddr()
}

// Port returns the bound UDP port number.
func (s *Server) Port() int {
	addr := s.LocalAddr()
	if addr == nil {
		return 0
	}
	if udpAddr, ok := addr.(*net.UDPAddr); ok {
		return udpAddr.Port
	}
	return 0
}

// Router returns the attached Router instance.
func (s *Server) Router() *Router {
	return s.router
}

// readLoop reads datagrams from the UDP socket in a zero-allocation loop.
func (s *Server) readLoop() {
	defer s.wg.Done()

	for s.running.Load() {
		buf := GetBuffer()
		n, srcAddr, err := s.conn.ReadFrom(buf)
		if err != nil {
			PutBuffer(buf)
			if !s.running.Load() {
				break
			}
			continue
		}

		if n < HeaderSize {
			PutBuffer(buf)
			continue
		}

		// Process packet in hot-path
		_ = s.router.HandlePacket(buf[:n], srcAddr)
		PutBuffer(buf)
	}
}

// cleanupLoop periodically removes inactive sessions (idle > 60s).
func (s *Server) cleanupLoop() {
	defer s.wg.Done()
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-s.ctx.Done():
			return
		case <-ticker.C:
			if s.router != nil && s.router.Sessions() != nil {
				_ = s.router.Sessions().CleanStaleSessions(60 * time.Second)
			}
		}
	}
}
