package audio

import (
	"net"
	"testing"
	"time"
)

func TestSessionSpeakingStateDelta(t *testing.T) {
	addr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:12345")
	sess := NewSession(1, 101, 5555, addr)

	// Initial state: silent, energy 0
	if sess.IsSpeaking || sess.EnergyLevel != 0 {
		t.Fatalf("expected initial speaking=false, energy=0")
	}

	// Small change: energy 2 (delta = 2 < 3) while still silent -> false
	changed := sess.UpdateSpeakingState(false, 2)
	if changed {
		t.Errorf("expected no change for delta 2, got true")
	}
	if sess.EnergyLevel != 2 {
		t.Errorf("expected energy updated to 2, got %d", sess.EnergyLevel)
	}

	// State transition to speaking -> true
	changed = sess.UpdateSpeakingState(true, 10)
	if !changed {
		t.Errorf("expected state change when transitioning to speaking, got false")
	}
	if !sess.IsSpeaking {
		t.Errorf("expected isSpeaking to be true")
	}

	// Speaking energy delta >= 3 (10 -> 14, diff = 4) -> true
	changed = sess.UpdateSpeakingState(true, 14)
	if !changed {
		t.Errorf("expected change when energy delta >= 3, got false")
	}

	// State transition to silent -> true
	changed = sess.UpdateSpeakingState(false, 0)
	if !changed {
		t.Errorf("expected state change when transitioning to silence, got false")
	}
}

func TestSessionManagerRouting(t *testing.T) {
	sm := NewSessionManager()

	addr1, _ := net.ResolveUDPAddr("udp", "127.0.0.1:10001")
	addr2, _ := net.ResolveUDPAddr("udp", "127.0.0.1:10002")
	addr3, _ := net.ResolveUDPAddr("udp", "127.0.0.1:10003")

	sess1 := NewSession(1, 101, 101, addr1)
	sess2 := NewSession(2, 101, 102, addr2)
	sess3 := NewSession(3, 102, 103, addr3) // In Channel 102

	sm.RegisterSession(sess1)
	sm.RegisterSession(sess2)
	sm.RegisterSession(sess3)

	if sm.Count() != 3 {
		t.Errorf("expected 3 sessions, got %d", sm.Count())
	}

	// Lookup by UserID
	if sm.GetByUser(1) != sess1 {
		t.Errorf("failed to lookup session 1 by UserID")
	}

	// Lookup by Addr
	if sm.GetByAddr(addr2) != sess2 {
		t.Errorf("failed to lookup session 2 by Addr")
	}

	// Channel Peers for User 1 in Channel 101 (should only contain User 2, not User 1 and not User 3)
	peers101 := sm.GetChannelPeers(101, 1)
	if len(peers101) != 1 {
		t.Fatalf("expected 1 peer for User 1 in 101, got %d", len(peers101))
	}
	if peers101[0].UserID != 2 {
		t.Errorf("expected peer to be User 2, got %d", peers101[0].UserID)
	}

	// Channel Peers for Channel 102
	peers102 := sm.GetChannelPeers(102, 999)
	if len(peers102) != 1 || peers102[0].UserID != 3 {
		t.Errorf("expected 1 peer in 102 (User 3)")
	}

	// Test MoveMember
	sm.MoveMember(3, 101)
	peers101AfterMove := sm.GetChannelPeers(101, 1)
	if len(peers101AfterMove) != 2 {
		t.Fatalf("expected 2 peers in 101 after move, got %d", len(peers101AfterMove))
	}

	// Test Mute and Deafen toggles
	sm.SetServerMute(1, true)
	if !sess1.IsMuted() {
		t.Errorf("expected user 1 to be muted")
	}

	sm.SetServerDeafen(2, true)
	if !sess2.IsDeafened() {
		t.Errorf("expected user 2 to be deafened")
	}

	// Test RemoveSession
	sm.RemoveSession(1)
	if sm.GetByUser(1) != nil {
		t.Errorf("expected session 1 to be nil after remove")
	}
	if sm.GetByAddr(addr1) != nil {
		t.Errorf("expected addr1 to be nil after remove")
	}
	if sm.Count() != 2 {
		t.Errorf("expected 2 sessions remaining, got %d", sm.Count())
	}
}

func TestSessionPendingActivation(t *testing.T) {
	sm := NewSessionManager()

	token := "valid_test_token_123"
	expires := time.Now().Add(10 * time.Second)
	sm.RegisterPending(token, 10, 101, 9999, expires)

	addr, _ := net.ResolveUDPAddr("udp", "127.0.0.1:45678")

	// Activate with wrong channel
	_, err := sm.ActivatePending(token, 10, 102, addr)
	if err != ErrChannelMismatch {
		t.Errorf("expected ErrChannelMismatch, got %v", err)
	}

	// Activate successfully
	sess, err := sm.ActivatePending(token, 10, 101, addr)
	if err != nil || sess == nil {
		t.Fatalf("failed to activate pending token: %v", err)
	}

	if sess.UserID != 10 || sess.ChannelID != 101 || sess.SSRC != 9999 {
		t.Errorf("activated session fields mismatch: %+v", sess)
	}

	// Second activation should fail (single-use)
	_, err = sm.ActivatePending(token, 10, 101, addr)
	if err != ErrUnauthorizedSession {
		t.Errorf("expected ErrUnauthorizedSession on replay, got %v", err)
	}
}
