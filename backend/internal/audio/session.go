package audio

import (
	"net"
	"sync"
	"time"
)

// Session represents an authenticated active voice client endpoint.
type Session struct {
	UserID         uint32
	ChannelID      uint32
	SSRC           uint32
	Addr           net.Addr
	LastSeen       time.Time
	ServerMuted    bool
	ServerDeafened bool
	IsSpeaking     bool
	EnergyLevel    uint8
	mu             sync.RWMutex
}

// NewSession creates a new Session.
func NewSession(userID, channelID, ssrc uint32, addr net.Addr) *Session {
	return &Session{
		UserID:    userID,
		ChannelID: channelID,
		SSRC:      ssrc,
		Addr:      addr,
		LastSeen:  time.Now(),
	}
}

// GetAddr returns the current UDP destination address.
func (s *Session) GetAddr() net.Addr {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.Addr
}

// SetAddr updates the session's UDP address (supports NAT rebinding & Tailscale mesh roaming).
func (s *Session) SetAddr(addr net.Addr) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Addr = addr
	s.LastSeen = time.Now()
}

// Touch updates the LastSeen timestamp.
func (s *Session) Touch() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.LastSeen = time.Now()
}

// SetServerMute toggles server-side mute status.
func (s *Session) SetServerMute(muted bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ServerMuted = muted
}

// IsMuted returns true if the user is server-muted.
func (s *Session) IsMuted() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.ServerMuted
}

// SetServerDeafen toggles server-side deafen status.
func (s *Session) SetServerDeafen(deafened bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ServerDeafened = deafened
}

// IsDeafened returns true if the user is server-deafened.
func (s *Session) IsDeafened() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.ServerDeafened
}

// UpdateSpeakingState updates VAD speaking and energy level.
// Returns true if speaking state transitioned or energy changed by >= 3 dBFS quantization levels.
func (s *Session) UpdateSpeakingState(speaking bool, energy uint8) bool {
	s.mu.Lock()
	defer s.mu.Unlock()

	diff := int(energy) - int(s.EnergyLevel)
	if diff < 0 {
		diff = -diff
	}

	stateChanged := (s.IsSpeaking != speaking) || (diff >= 3)
	s.IsSpeaking = speaking
	s.EnergyLevel = energy
	s.LastSeen = time.Now()

	return stateChanged
}

// PendingToken stores pre-issued voice tokens from WebSocket join_voice.
type PendingToken struct {
	Token     string
	UserID    uint32
	ChannelID uint32
	SSRC      uint32
	ExpiresAt time.Time
}

// SessionManager manages thread-safe lookups and room isolation for all active UDP sessions.
type SessionManager struct {
	mu            sync.RWMutex
	byUser        map[uint32]*Session
	byAddr        map[string]*Session
	byChannel     map[uint32]map[uint32]*Session
	pendingTokens map[string]*PendingToken
}

// NewSessionManager initializes an empty SessionManager.
func NewSessionManager() *SessionManager {
	return &SessionManager{
		byUser:        make(map[uint32]*Session),
		byAddr:        make(map[string]*Session),
		byChannel:     make(map[uint32]map[uint32]*Session),
		pendingTokens: make(map[string]*PendingToken),
	}
}

// RegisterPending stores a pending single-use token issued by WebSocket join_voice.
func (sm *SessionManager) RegisterPending(token string, userID, channelID, ssrc uint32, expiresAt time.Time) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sm.pendingTokens[token] = &PendingToken{
		Token:     token,
		UserID:    userID,
		ChannelID: channelID,
		SSRC:      ssrc,
		ExpiresAt: expiresAt,
	}
}

// ActivatePending consumes a pending token and registers the active UDP session.
func (sm *SessionManager) ActivatePending(token string, userID, channelID uint32, addr net.Addr) (*Session, error) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	pt, exists := sm.pendingTokens[token]
	if !exists {
		return nil, ErrUnauthorizedSession
	}

	if time.Now().After(pt.ExpiresAt) {
		delete(sm.pendingTokens, token)
		return nil, ErrUnauthorizedSession
	}

	if pt.UserID != userID || pt.ChannelID != channelID {
		return nil, ErrChannelMismatch
	}

	delete(sm.pendingTokens, token)

	// Check if existing session for this user exists; remove old address mapping
	if oldSess, ok := sm.byUser[userID]; ok {
		if oldSess.Addr != nil {
			delete(sm.byAddr, oldSess.Addr.String())
		}
		if chMap, ok := sm.byChannel[oldSess.ChannelID]; ok {
			delete(chMap, userID)
		}
	}

	session := &Session{
		UserID:    userID,
		ChannelID: channelID,
		SSRC:      pt.SSRC,
		Addr:      addr,
		LastSeen:  time.Now(),
	}

	sm.byUser[userID] = session
	if addr != nil {
		sm.byAddr[addr.String()] = session
	}

	if _, ok := sm.byChannel[channelID]; !ok {
		sm.byChannel[channelID] = make(map[uint32]*Session)
	}
	sm.byChannel[channelID][userID] = session

	return session, nil
}

// RegisterSession registers an active session directly.
func (sm *SessionManager) RegisterSession(session *Session) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if oldSess, ok := sm.byUser[session.UserID]; ok {
		if oldSess.Addr != nil {
			delete(sm.byAddr, oldSess.Addr.String())
		}
		if chMap, ok := sm.byChannel[oldSess.ChannelID]; ok {
			delete(chMap, session.UserID)
		}
	}

	sm.byUser[session.UserID] = session
	if session.Addr != nil {
		sm.byAddr[session.Addr.String()] = session
	}

	if _, ok := sm.byChannel[session.ChannelID]; !ok {
		sm.byChannel[session.ChannelID] = make(map[uint32]*Session)
	}
	sm.byChannel[session.ChannelID][session.UserID] = session
}

// GetByUser returns the session for a given User ID.
func (sm *SessionManager) GetByUser(userID uint32) *Session {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.byUser[userID]
}

// GetByAddr returns the session for a given UDP address.
func (sm *SessionManager) GetByAddr(addr net.Addr) *Session {
	if addr == nil {
		return nil
	}
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return sm.byAddr[addr.String()]
}

// UpdateAddr updates the address of an existing session (roaming support).
func (sm *SessionManager) UpdateAddr(userID uint32, newAddr net.Addr) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sess, ok := sm.byUser[userID]
	if !ok {
		return
	}

	if sess.Addr != nil {
		delete(sm.byAddr, sess.Addr.String())
	}
	sess.SetAddr(newAddr)
	if newAddr != nil {
		sm.byAddr[newAddr.String()] = sess
	}
}

// SetServerMute updates mute gating for a user.
func (sm *SessionManager) SetServerMute(userID uint32, muted bool) {
	sm.mu.RLock()
	sess, ok := sm.byUser[userID]
	sm.mu.RUnlock()

	if ok && sess != nil {
		sess.SetServerMute(muted)
	}
}

// SetServerDeafen updates deafen gating for a user.
func (sm *SessionManager) SetServerDeafen(userID uint32, deafened bool) {
	sm.mu.RLock()
	sess, ok := sm.byUser[userID]
	sm.mu.RUnlock()

	if ok && sess != nil {
		sess.SetServerDeafen(deafened)
	}
}

// MoveMember moves a user to another channel in the routing table.
func (sm *SessionManager) MoveMember(userID uint32, toChannelID uint32) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	sess, ok := sm.byUser[userID]
	if !ok {
		return
	}

	fromChannelID := sess.ChannelID
	if chMap, ok := sm.byChannel[fromChannelID]; ok {
		delete(chMap, userID)
		if len(chMap) == 0 {
			delete(sm.byChannel, fromChannelID)
		}
	}

	sess.ChannelID = toChannelID
	if _, ok := sm.byChannel[toChannelID]; !ok {
		sm.byChannel[toChannelID] = make(map[uint32]*Session)
	}
	sm.byChannel[toChannelID][userID] = sess
}

// RemoveSession removes a user's session upon leaving voice or disconnect and purges pending tokens.
func (sm *SessionManager) RemoveSession(userID uint32) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	for tok, pt := range sm.pendingTokens {
		if pt.UserID == userID {
			delete(sm.pendingTokens, tok)
		}
	}

	sess, ok := sm.byUser[userID]
	if !ok {
		return
	}

	delete(sm.byUser, userID)
	if sess.Addr != nil {
		delete(sm.byAddr, sess.Addr.String())
	}
	if chMap, ok := sm.byChannel[sess.ChannelID]; ok {
		delete(chMap, userID)
		if len(chMap) == 0 {
			delete(sm.byChannel, sess.ChannelID)
		}
	}
}

// RevokePending removes all pending unconsumed tokens for a specific user ID.
func (sm *SessionManager) RevokePending(userID uint32) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	for tok, pt := range sm.pendingTokens {
		if pt.UserID == userID {
			delete(sm.pendingTokens, tok)
		}
	}
}

// GetChannelPeers retrieves all peer sessions in channelID except excludeUserID.
// Only returns sessions that have a valid destination Addr.
func (sm *SessionManager) GetChannelPeers(channelID uint32, excludeUserID uint32) []*Session {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	chMap, ok := sm.byChannel[channelID]
	if !ok || len(chMap) == 0 {
		return nil
	}

	peers := make([]*Session, 0, len(chMap))
	for uid, sess := range chMap {
		if uid != excludeUserID && sess.Addr != nil {
			peers = append(peers, sess)
		}
	}
	return peers
}

// Count returns the total number of active voice sessions.
func (sm *SessionManager) Count() int {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	return len(sm.byUser)
}

// CleanStaleSessions removes sessions inactive for longer than maxIdle.
func (sm *SessionManager) CleanStaleSessions(maxIdle time.Duration) []uint32 {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	now := time.Now()
	var removed []uint32

	for uid, sess := range sm.byUser {
		if now.Sub(sess.LastSeen) > maxIdle {
			removed = append(removed, uid)
			delete(sm.byUser, uid)
			if sess.Addr != nil {
				delete(sm.byAddr, sess.Addr.String())
			}
			if chMap, ok := sm.byChannel[sess.ChannelID]; ok {
				delete(chMap, uid)
				if len(chMap) == 0 {
					delete(sm.byChannel, sess.ChannelID)
				}
			}
		}
	}

	// Also clean expired pending tokens
	for tok, pt := range sm.pendingTokens {
		if now.After(pt.ExpiresAt) {
			delete(sm.pendingTokens, tok)
		}
	}

	return removed
}
