package audio

import (
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func Test15ConcurrentVoiceStreams(t *testing.T) {
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, nil)
	srv := NewServer("127.0.0.1:0", router)

	if err := srv.Start(); err != nil {
		t.Fatalf("failed to start UDP server: %v", err)
	}
	defer srv.Close()

	serverPort := srv.Port()
	numClients := 15
	framesPerClient := 20
	channelID := uint32(101)

	var conns []*net.UDPConn
	for i := 1; i <= numClients; i++ {
		c, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
		if err != nil {
			t.Fatalf("client %d dial failed: %v", i, err)
		}
		conns = append(conns, c.(*net.UDPConn))

		// Handshake
		hs := &Packet{
			Magic:     MagicByte,
			Version:   ProtocolVersion,
			Type:      TypeHandshake,
			SenderID:  uint32(i),
			ChannelID: channelID,
			Payload:   []byte(fmt.Sprintf("token_%d", i)),
		}
		_, _ = c.Write(hs.Encode())
	}
	defer func() {
		for _, c := range conns {
			_ = c.Close()
		}
	}()

	time.Sleep(50 * time.Millisecond)

	var totalReceived atomic.Int64
	var wgRecv sync.WaitGroup

	// Start readers on each client
	for i := 0; i < numClients; i++ {
		wgRecv.Add(1)
		conn := conns[i]
		userID := uint32(i + 1)

		go func(c *net.UDPConn, uid uint32) {
			defer wgRecv.Done()
			buf := make([]byte, MaxPacketSize)
			_ = c.SetReadDeadline(time.Now().Add(2 * time.Second))

			for {
				n, err := c.Read(buf)
				if err != nil {
					break
				}
				pkt, err := Decode(buf[:n])
				if err == nil && pkt.Type == TypeVoice {
					if pkt.SenderID != uid { // Must not be self-echo
						totalReceived.Add(1)
					}
				}
			}
		}(conn, userID)
	}

	// Concurrently stream audio from all 15 clients
	var wgSend sync.WaitGroup
	for i := 0; i < numClients; i++ {
		wgSend.Add(1)
		conn := conns[i]
		userID := uint32(i + 1)

		go func(c *net.UDPConn, uid uint32) {
			defer wgSend.Done()
			for seq := 1; seq <= framesPerClient; seq++ {
				pkt := &Packet{
					Magic:       MagicByte,
					Version:     ProtocolVersion,
					Type:        TypeVoice,
					VAD:         true,
					EnergyLevel: 12,
					SenderID:    uid,
					ChannelID:   channelID,
					Sequence:    uint16(seq),
					Timestamp:   uint32(seq * 960),
					PayloadLen:  80,
					Payload:     make([]byte, 80),
				}
				_, _ = c.Write(pkt.Encode())
				time.Sleep(5 * time.Millisecond)
			}
		}(conn, userID)
	}

	wgSend.Wait()
	time.Sleep(200 * time.Millisecond)

	// Close client sockets to stop readers
	for _, c := range conns {
		_ = c.SetReadDeadline(time.Now())
	}
	wgRecv.Wait()

	received := totalReceived.Load()
	expectedMin := int64(numClients * framesPerClient * (numClients - 2)) // High delivery rate

	if received < expectedMin {
		t.Errorf("received %d forwarded packets, expected at least %d", received, expectedMin)
	}
}
