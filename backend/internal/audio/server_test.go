package audio

import (
	"bytes"
	"fmt"
	"net"
	"testing"
	"time"
)

func TestUDPServerLifecycleAndPingPong(t *testing.T) {
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, nil)
	srv := NewServer("127.0.0.1:0", router) // Bind to random open port

	if err := srv.Start(); err != nil {
		t.Fatalf("failed to start UDP server: %v", err)
	}
	defer srv.Close()

	serverPort := srv.Port()
	if serverPort <= 0 {
		t.Fatalf("invalid server port: %d", serverPort)
	}

	// Create client socket
	clientConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
	if err != nil {
		t.Fatalf("failed to dial UDP server: %v", err)
	}
	defer clientConn.Close()

	// Send Handshake
	handshakePkt := &Packet{
		Magic:      MagicByte,
		Version:    ProtocolVersion,
		Type:       TypeHandshake,
		SenderID:   99,
		ChannelID:  101,
		PayloadLen: 8,
		Payload:    []byte("token_99"),
	}
	_, err = clientConn.Write(handshakePkt.Encode())
	if err != nil {
		t.Fatalf("failed to send handshake: %v", err)
	}

	time.Sleep(20 * time.Millisecond)

	// Send Ping probe
	pingData := []byte("ping_timestamp_123456")
	pingPkt := &Packet{
		Magic:      MagicByte,
		Version:    ProtocolVersion,
		Type:       TypePing,
		SenderID:   99,
		ChannelID:  101,
		Sequence:   1,
		Timestamp:  48000,
		PayloadLen: uint16(len(pingData)),
		Payload:    pingData,
	}

	_, err = clientConn.Write(pingPkt.Encode())
	if err != nil {
		t.Fatalf("failed to send ping: %v", err)
	}

	// Read Pong response
	buf := make([]byte, MaxPacketSize)
	_ = clientConn.SetReadDeadline(time.Now().Add(1 * time.Second))
	n, err := clientConn.Read(buf)
	if err != nil {
		t.Fatalf("failed to read pong response: %v", err)
	}

	pongPkt, err := Decode(buf[:n])
	if err != nil {
		t.Fatalf("failed to decode pong packet: %v", err)
	}

	if pongPkt.Type != TypePong {
		t.Errorf("expected TypePong (0x03), got 0x%02X", pongPkt.Type)
	}
	if !bytes.Equal(pongPkt.Payload, pingData) {
		t.Errorf("pong payload mismatch: got %s, expected %s", pongPkt.Payload, pingData)
	}
}

func TestUDPServerLiveVoiceForwarding(t *testing.T) {
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, nil)
	srv := NewServer("127.0.0.1:0", router)

	if err := srv.Start(); err != nil {
		t.Fatalf("failed to start UDP server: %v", err)
	}
	defer srv.Close()

	serverPort := srv.Port()

	// Alice client socket
	aliceConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
	if err != nil {
		t.Fatalf("Alice dial failed: %v", err)
	}
	defer aliceConn.Close()

	// Bob client socket
	bobConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
	if err != nil {
		t.Fatalf("Bob dial failed: %v", err)
	}
	defer bobConn.Close()

	// Send Handshakes
	aliceHandshake := &Packet{
		Magic:     MagicByte,
		Version:   ProtocolVersion,
		Type:      TypeHandshake,
		SenderID:  1,
		ChannelID: 101,
		Payload:   []byte("token_1"),
	}
	_, _ = aliceConn.Write(aliceHandshake.Encode())

	bobHandshake := &Packet{
		Magic:     MagicByte,
		Version:   ProtocolVersion,
		Type:      TypeHandshake,
		SenderID:  2,
		ChannelID: 101,
		Payload:   []byte("token_2"),
	}
	_, _ = bobConn.Write(bobHandshake.Encode())

	time.Sleep(30 * time.Millisecond)

	// Alice sends Voice frame
	voicePayload := []byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08}
	voicePkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 12,
		SenderID:    1,
		ChannelID:   101,
		Sequence:    10,
		Timestamp:   960,
		PayloadLen:  uint16(len(voicePayload)),
		Payload:     voicePayload,
	}

	_, err = aliceConn.Write(voicePkt.Encode())
	if err != nil {
		t.Fatalf("Alice voice send failed: %v", err)
	}

	// Bob receives forwarded voice frame
	buf := make([]byte, MaxPacketSize)
	_ = bobConn.SetReadDeadline(time.Now().Add(1 * time.Second))
	n, err := bobConn.Read(buf)
	if err != nil {
		t.Fatalf("Bob failed to receive forwarded packet: %v", err)
	}

	recvPkt, err := Decode(buf[:n])
	if err != nil {
		t.Fatalf("failed to decode forwarded packet: %v", err)
	}

	if recvPkt.SenderID != 1 {
		t.Errorf("expected sender 1, got %d", recvPkt.SenderID)
	}
	if recvPkt.ChannelID != 101 {
		t.Errorf("expected channel 101, got %d", recvPkt.ChannelID)
	}
	if recvPkt.Sequence != 10 {
		t.Errorf("expected sequence 10, got %d", recvPkt.Sequence)
	}
	if !bytes.Equal(recvPkt.Payload, voicePayload) {
		t.Errorf("payload mismatch: %v vs %v", recvPkt.Payload, voicePayload)
	}
}

func TestUDPServerPCMVoiceForwarding(t *testing.T) {
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, nil)
	srv := NewServer("127.0.0.1:0", router)

	if err := srv.Start(); err != nil {
		t.Fatalf("failed to start UDP server: %v", err)
	}
	defer srv.Close()

	serverPort := srv.Port()

	aliceConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
	if err != nil {
		t.Fatalf("Alice dial failed: %v", err)
	}
	defer aliceConn.Close()

	bobConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", serverPort))
	if err != nil {
		t.Fatalf("Bob dial failed: %v", err)
	}
	defer bobConn.Close()

	// Handshake
	aliceHandshake := &Packet{
		Magic:     MagicByte,
		Version:   ProtocolVersion,
		Type:      TypeHandshake,
		SenderID:  10,
		ChannelID: 200,
		Payload:   []byte("token_alice_pcm"),
	}
	_, _ = aliceConn.Write(aliceHandshake.Encode())

	bobHandshake := &Packet{
		Magic:     MagicByte,
		Version:   ProtocolVersion,
		Type:      TypeHandshake,
		SenderID:  20,
		ChannelID: 200,
		Payload:   []byte("token_bob_pcm"),
	}
	_, _ = bobConn.Write(bobHandshake.Encode())

	time.Sleep(30 * time.Millisecond)

	// Alice sends uncompressed 1920-byte PCM frame
	pcmPayload := make([]byte, 1920)
	for i := range pcmPayload {
		pcmPayload[i] = byte((i * 13) % 256)
	}
	voicePkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 15,
		SenderID:    10,
		ChannelID:   200,
		Sequence:    55,
		Timestamp:   96000,
		PayloadLen:  uint16(len(pcmPayload)),
		Payload:     pcmPayload,
	}

	_, err = aliceConn.Write(voicePkt.Encode())
	if err != nil {
		t.Fatalf("Alice PCM send failed: %v", err)
	}

	// Bob receives 1940-byte datagram
	buf := make([]byte, MaxPacketSize)
	_ = bobConn.SetReadDeadline(time.Now().Add(1 * time.Second))
	n, err := bobConn.Read(buf)
	if err != nil {
		t.Fatalf("Bob failed to receive PCM frame: %v", err)
	}
	if n != 1940 {
		t.Fatalf("expected Bob to receive 1940 bytes, got %d", n)
	}

	recvPkt, err := Decode(buf[:n])
	if err != nil {
		t.Fatalf("failed to decode PCM frame: %v", err)
	}
	if recvPkt.SenderID != 10 || recvPkt.ChannelID != 200 {
		t.Errorf("header routing fields mismatch: sender=%d ch=%d", recvPkt.SenderID, recvPkt.ChannelID)
	}
	if !bytes.Equal(recvPkt.Payload, pcmPayload) {
		t.Errorf("PCM payload mismatch")
	}
}
