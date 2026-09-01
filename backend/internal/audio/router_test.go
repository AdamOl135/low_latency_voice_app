package audio

import (
	"bytes"
	"net"
	"sync"
	"testing"
	"time"
)

type mockPacketWriter struct {
	mu      sync.Mutex
	packets map[string][][]byte
}

func newMockPacketWriter() *mockPacketWriter {
	return &mockPacketWriter{
		packets: make(map[string][][]byte),
	}
}

func (w *mockPacketWriter) WriteTo(p []byte, addr net.Addr) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	cp := make([]byte, len(p))
	copy(cp, p)
	key := addr.String()
	w.packets[key] = append(w.packets[key], cp)
	return len(p), nil
}

func (w *mockPacketWriter) getPackets(addr net.Addr) [][]byte {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.packets[addr.String()]
}

func (w *mockPacketWriter) clear() {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.packets = make(map[string][][]byte)
}

type mockVADNotifier struct {
	mu     sync.Mutex
	events []vadEvent
}

type vadEvent struct {
	channelID uint32
	userID    uint32
	speaking  bool
	energy    uint8
}

func (n *mockVADNotifier) BroadcastVoiceState(channelID uint32, userID uint32, speaking bool, energy uint8) {
	n.mu.Lock()
	defer n.mu.Unlock()
	n.events = append(n.events, vadEvent{channelID, userID, speaking, energy})
}

func (n *mockVADNotifier) getEvents() []vadEvent {
	n.mu.Lock()
	defer n.mu.Unlock()
	cp := make([]vadEvent, len(n.events))
	copy(cp, n.events)
	return cp
}

func TestRouterPingPongProbe(t *testing.T) {
	writer := newMockPacketWriter()
	router := NewRouter(nil, nil, nil, writer)

	clientAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40001")
	pingPayload := []byte{0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04}

	pingPkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypePing,
		SenderID:    101,
		ChannelID:   1,
		Sequence:    77,
		Timestamp:   48000,
		PayloadLen:  uint16(len(pingPayload)),
		Payload:     pingPayload,
	}

	rawPing := pingPkt.Encode()
	err := router.HandlePacket(rawPing, clientAddr)
	if err != nil {
		t.Fatalf("HandlePacket(ping) failed: %v", err)
	}

	pkts := writer.getPackets(clientAddr)
	if len(pkts) != 1 {
		t.Fatalf("expected 1 pong response, got %d", len(pkts))
	}

	pongPkt, err := Decode(pkts[0])
	if err != nil {
		t.Fatalf("failed to decode pong: %v", err)
	}

	if pongPkt.Type != TypePong {
		t.Errorf("expected type TypePong (0x03), got 0x%02X", pongPkt.Type)
	}
	if pongPkt.Sequence != 77 {
		t.Errorf("expected sequence 77, got %d", pongPkt.Sequence)
	}
	if pongPkt.Timestamp != 48000 {
		t.Errorf("expected timestamp 48000, got %d", pongPkt.Timestamp)
	}
	if !bytes.Equal(pongPkt.Payload, pingPayload) {
		t.Errorf("pong payload mismatch: got %v, expected %v", pongPkt.Payload, pingPayload)
	}
}

func TestRouterSFUSelectiveForwarding(t *testing.T) {
	writer := newMockPacketWriter()
	notifier := &mockVADNotifier{}
	sm := NewSessionManager()
	router := NewRouter(sm, nil, notifier, writer)

	aliceAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:50001")
	bobAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:50002")
	charlieAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:50003") // In different channel 102

	aliceSess := NewSession(1, 101, 1001, aliceAddr)
	bobSess := NewSession(2, 101, 1002, bobAddr)
	charlieSess := NewSession(3, 102, 1003, charlieAddr)

	sm.RegisterSession(aliceSess)
	sm.RegisterSession(bobSess)
	sm.RegisterSession(charlieSess)

	// Alice sends audio frame in channel 101
	audioPayload := make([]byte, 80)
	for i := range audioPayload {
		audioPayload[i] = byte(i)
	}

	voicePkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 14,
		SenderID:    1,
		ChannelID:   101,
		Sequence:    1,
		Timestamp:   960,
		Payload:     audioPayload,
	}

	rawVoice := voicePkt.Encode()
	err := router.HandlePacket(rawVoice, aliceAddr)
	if err != nil {
		t.Fatalf("HandlePacket(voice) failed: %v", err)
	}

	// 1. Bob (peer in 101) must receive the packet
	bobPkts := writer.getPackets(bobAddr)
	if len(bobPkts) != 1 {
		t.Fatalf("expected Bob to receive 1 packet, got %d", len(bobPkts))
	}
	if !bytes.Equal(bobPkts[0], rawVoice) {
		t.Errorf("forwarded packet content mismatch")
	}

	// 2. Alice (sender) must NOT receive her own packet (no self-echo)
	alicePkts := writer.getPackets(aliceAddr)
	if len(alicePkts) != 0 {
		t.Errorf("expected Alice to receive 0 packets (no self-echo), got %d", len(alicePkts))
	}

	// 3. Charlie (in channel 102) must NOT receive packet (channel isolation)
	charliePkts := writer.getPackets(charlieAddr)
	if len(charliePkts) != 0 {
		t.Errorf("expected Charlie in 102 to receive 0 packets (channel isolation), got %d", len(charliePkts))
	}

	// 4. VAD Notifier must receive state transition event
	events := notifier.getEvents()
	if len(events) != 1 {
		t.Fatalf("expected 1 VAD event, got %d", len(events))
	}
	if events[0].userID != 1 || events[0].channelID != 101 || !events[0].speaking || events[0].energy != 14 {
		t.Errorf("unexpected VAD event: %+v", events[0])
	}
}

func TestRouterServerMuteAndDeafenGating(t *testing.T) {
	writer := newMockPacketWriter()
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, writer)

	aliceAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:51001")
	bobAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:51002")
	charlieAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:51003")

	aliceSess := NewSession(1, 101, 1001, aliceAddr)
	bobSess := NewSession(2, 101, 1002, bobAddr)
	charlieSess := NewSession(3, 101, 1003, charlieAddr)

	sm.RegisterSession(aliceSess)
	sm.RegisterSession(bobSess)
	sm.RegisterSession(charlieSess)

	// Case 1: Bob is server-deafened (Egress Deafen Gating)
	bobSess.SetServerDeafen(true)

	voicePkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 10,
		SenderID:    1,
		ChannelID:   101,
		Sequence:    1,
		Timestamp:   960,
		Payload:     []byte{1, 2, 3},
	}

	err := router.HandlePacket(voicePkt.Encode(), aliceAddr)
	if err != nil {
		t.Fatalf("HandlePacket failed: %v", err)
	}

	// Charlie should receive, but deafened Bob should NOT
	if len(writer.getPackets(bobAddr)) != 0 {
		t.Errorf("deafened Bob should receive 0 packets, got %d", len(writer.getPackets(bobAddr)))
	}
	if len(writer.getPackets(charlieAddr)) != 1 {
		t.Errorf("Charlie should receive 1 packet, got %d", len(writer.getPackets(charlieAddr)))
	}

	// Case 2: Alice is server-muted (Ingress Mute Gating)
	writer.clear()
	aliceSess.SetServerMute(true)

	err = router.HandlePacket(voicePkt.Encode(), aliceAddr)
	if err != ErrUserServerMuted {
		t.Errorf("expected ErrUserServerMuted, got %v", err)
	}

	// Nobody should receive audio from muted Alice
	if len(writer.getPackets(charlieAddr)) != 0 {
		t.Errorf("Charlie should receive 0 packets from muted Alice, got %d", len(writer.getPackets(charlieAddr)))
	}
}

func TestRouterSelectiveForwardingPCMFrame(t *testing.T) {
	sm := NewSessionManager()
	writer := newMockPacketWriter()
	notifier := &mockVADNotifier{}
	router := NewRouter(sm, nil, notifier, writer)

	aliceAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40001")
	bobAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40002")
	charlieAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40003")

	aliceSess := NewSession(1, 101, 1001, aliceAddr)
	bobSess := NewSession(2, 101, 1002, bobAddr)
	charlieSess := NewSession(3, 102, 1003, charlieAddr) // Channel 102

	sm.RegisterSession(aliceSess)
	sm.RegisterSession(bobSess)
	sm.RegisterSession(charlieSess)

	// 1920-byte PCM frame
	pcmPayload := make([]byte, 1920)
	for i := range pcmPayload {
		pcmPayload[i] = byte((i * 3) % 256)
	}

	voicePkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 14,
		SenderID:    1,
		ChannelID:   101,
		Sequence:    100,
		Timestamp:   48000,
		PayloadLen:  uint16(len(pcmPayload)),
		Payload:     pcmPayload,
	}

	rawPCM := voicePkt.Encode()
	if len(rawPCM) != 1940 {
		t.Fatalf("expected raw PCM packet length 1940, got %d", len(rawPCM))
	}

	err := router.HandlePacket(rawPCM, aliceAddr)
	if err != nil {
		t.Fatalf("HandlePacket failed for PCM frame: %v", err)
	}

	// 1. Bob in channel 101 must receive the 1940-byte packet
	bobPkts := writer.getPackets(bobAddr)
	if len(bobPkts) != 1 {
		t.Fatalf("expected Bob to receive 1 packet, got %d", len(bobPkts))
	}
	if len(bobPkts[0]) != 1940 {
		t.Errorf("expected Bob packet size 1940, got %d", len(bobPkts[0]))
	}
	decodedBob, err := Decode(bobPkts[0])
	if err != nil {
		t.Fatalf("failed to decode Bob's packet: %v", err)
	}
	if decodedBob.VAD != true || decodedBob.EnergyLevel != 14 {
		t.Errorf("Bob packet VAD/Energy mismatch: VAD=%v, Energy=%d", decodedBob.VAD, decodedBob.EnergyLevel)
	}
	if !bytes.Equal(decodedBob.Payload, pcmPayload) {
		t.Errorf("Bob packet payload corrupted")
	}

	// 2. Alice (sender) must receive 0 packets (no self-echo)
	alicePkts := writer.getPackets(aliceAddr)
	if len(alicePkts) != 0 {
		t.Errorf("Alice received %d packets, expected 0 (self-echo)", len(alicePkts))
	}

	// 3. Charlie (channel 102) must receive 0 packets (channel isolation)
	charliePkts := writer.getPackets(charlieAddr)
	if len(charliePkts) != 0 {
		t.Errorf("Charlie in channel 102 received %d packets, expected 0", len(charliePkts))
	}

	// 4. VAD notification dispatched for Alice
	events := notifier.getEvents()
	if len(events) == 0 {
		t.Errorf("expected VAD events to be broadcasted, got 0")
	} else {
		lastEvent := events[len(events)-1]
		if lastEvent.userID != 1 || !lastEvent.speaking || lastEvent.energy != 14 {
			t.Errorf("unexpected VAD event: %+v", lastEvent)
		}
	}
}

func TestRouterPingRefreshesLastSeen(t *testing.T) {
	writer := newMockPacketWriter()
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, writer)

	clientAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40001")
	session := NewSession(101, 1, 1001, clientAddr)
	// Simulate idle state by backdating LastSeen by 50 seconds
	staleTime := time.Now().Add(-50 * time.Second)
	session.LastSeen = staleTime
	sm.RegisterSession(session)

	pingPkt := &Packet{
		Magic:      MagicByte,
		Version:    ProtocolVersion,
		Type:       TypePing,
		SenderID:   101,
		ChannelID:  1,
		Sequence:   1,
		Timestamp:  1000,
		PayloadLen: 0,
		Payload:    nil,
	}

	err := router.HandlePacket(pingPkt.Encode(), clientAddr)
	if err != nil {
		t.Fatalf("HandlePacket(ping) failed: %v", err)
	}

	// Verify that LastSeen was refreshed
	if session.LastSeen.Equal(staleTime) || session.LastSeen.Before(staleTime) {
		t.Errorf("expected LastSeen to be updated, but was %v (stale was %v)", session.LastSeen, staleTime)
	}
	if time.Since(session.LastSeen) > 2*time.Second {
		t.Errorf("expected LastSeen to be within last 2s, but got %v", time.Since(session.LastSeen))
	}
}

func TestSilentListenerPingPreventsScavengerEviction(t *testing.T) {
	writer := newMockPacketWriter()
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, writer)

	clientAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40002")
	session := NewSession(102, 1, 1002, clientAddr)
	// Backdate LastSeen to 55 seconds ago (close to 60s eviction threshold)
	session.LastSeen = time.Now().Add(-55 * time.Second)
	sm.RegisterSession(session)

	if sm.Count() != 1 {
		t.Fatalf("expected 1 session registered, got %d", sm.Count())
	}

	// Client sends periodic ping probe
	pingPkt := &Packet{
		Magic:      MagicByte,
		Version:    ProtocolVersion,
		Type:       TypePing,
		SenderID:   102,
		ChannelID:  1,
		Sequence:   2,
		Timestamp:  2000,
		PayloadLen: 0,
		Payload:    nil,
	}

	err := router.HandlePacket(pingPkt.Encode(), clientAddr)
	if err != nil {
		t.Fatalf("HandlePacket(ping) failed: %v", err)
	}

	// Run idle session scavenger with 60s idle threshold
	evicted := sm.CleanStaleSessions(60 * time.Second)
	if len(evicted) != 0 {
		t.Errorf("expected 0 evicted sessions after ping refresh, got %d: %v", len(evicted), evicted)
	}

	if sm.GetByUser(102) == nil {
		t.Errorf("expected session 102 to remain in SessionManager, but was evicted")
	}

	// As a sanity check, if LastSeen is older than 60s and no ping arrives, it should be evicted
	session.LastSeen = time.Now().Add(-65 * time.Second)
	evictedStale := sm.CleanStaleSessions(60 * time.Second)
	if len(evictedStale) != 1 || evictedStale[0] != 102 {
		t.Errorf("expected session 102 to be evicted when stale, got: %v", evictedStale)
	}
	if sm.GetByUser(102) != nil {
		t.Errorf("expected session 102 to be removed after exceeding maxIdle")
	}
}

func TestRouterPingRoamingAddrUpdate(t *testing.T) {
	writer := newMockPacketWriter()
	sm := NewSessionManager()
	router := NewRouter(sm, nil, nil, writer)

	oldAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40003")
	newAddr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:40004")

	session := NewSession(103, 1, 1003, oldAddr)
	sm.RegisterSession(session)

	// Send ping from new roaming address
	pingPkt := &Packet{
		Magic:      MagicByte,
		Version:    ProtocolVersion,
		Type:       TypePing,
		SenderID:   103,
		ChannelID:  1,
		Sequence:   3,
		Timestamp:  3000,
		PayloadLen: 0,
		Payload:    nil,
	}

	err := router.HandlePacket(pingPkt.Encode(), newAddr)
	if err != nil {
		t.Fatalf("HandlePacket(ping) failed: %v", err)
	}

	// Verify session address is updated to newAddr
	if session.GetAddr().String() != newAddr.String() {
		t.Errorf("expected session addr %s, got %s", newAddr.String(), session.GetAddr().String())
	}
	if sm.GetByAddr(newAddr) != session {
		t.Errorf("expected session lookup by newAddr to succeed")
	}
	if sm.GetByAddr(oldAddr) != nil {
		t.Errorf("expected old address lookup to return nil")
	}
}

