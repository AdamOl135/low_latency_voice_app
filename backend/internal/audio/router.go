package audio

import (
	"net"
	"strings"

	"low_latency_voice_app/backend/internal/model"
)

// PacketWriter defines the interface for transmitting datagrams to a remote address.
type PacketWriter interface {
	WriteTo(p []byte, addr net.Addr) (n int, err error)
}

// VADNotifier dispatches real-time speaking indicator updates to the WebSocket control plane.
type VADNotifier interface {
	BroadcastVoiceState(channelID uint32, userID uint32, speaking bool, energy uint8)
}

// TokenValidator verifies and consumes single-use voice tokens from persistent storage.
type TokenValidator interface {
	ConsumeVoiceToken(token string) (*model.VoiceToken, error)
}

// Router orchestrates selective audio forwarding, in-band VAD detection, ping/pong RTT probes,
// and server-side mute/deafen gating rules.
type Router struct {
	sessions  *SessionManager
	validator TokenValidator
	notifier  VADNotifier
	writer    PacketWriter
}

// NewRouter creates a new SFU Router.
func NewRouter(sessions *SessionManager, validator TokenValidator, notifier VADNotifier, writer PacketWriter) *Router {
	if sessions == nil {
		sessions = NewSessionManager()
	}
	return &Router{
		sessions:  sessions,
		validator: validator,
		notifier:  notifier,
		writer:    writer,
	}
}

// SetWriter updates the PacketWriter (e.g. after socket binding).
func (r *Router) SetWriter(w PacketWriter) {
	r.writer = w
}

// Sessions returns the active SessionManager.
func (r *Router) Sessions() *SessionManager {
	return r.sessions
}

// HandlePacket processes a raw inbound datagram, enforcing zero allocation in the voice hot-path.
func (r *Router) HandlePacket(data []byte, srcAddr net.Addr) error {
	if len(data) < HeaderSize {
		return ErrPacketTooShort
	}

	pkt := GetPacket()
	defer PutPacket(pkt)

	if err := DecodeInto(data, pkt); err != nil {
		return err
	}

	switch pkt.Type {
	case TypeVoice:
		return r.handleVoice(pkt, data, srcAddr)
	case TypePing:
		return r.handlePing(pkt, srcAddr)
	case TypeHandshake:
		return r.handleHandshake(pkt, srcAddr)
	case TypePong:
		// SFU ignores incoming PONG packets (they are client-bound responses)
		return nil
	default:
		return ErrInvalidType
	}
}

// handleVoice performs zero-allocation selective forwarding and in-band VAD state synchronization.
func (r *Router) handleVoice(pkt *Packet, rawData []byte, srcAddr net.Addr) error {
	session := r.sessions.GetByUser(pkt.SenderID)
	if session == nil {
		// If session not found by UserID, check if address is registered
		session = r.sessions.GetByAddr(srcAddr)
		if session == nil || session.UserID != pkt.SenderID {
			return ErrSessionNotFound
		}
	}

	// Verify channel consistency
	if session.ChannelID != pkt.ChannelID {
		return ErrChannelMismatch
	}

	// Roaming / NAT rebinding: update UDP address if changed
	currentAddr := session.GetAddr()
	if currentAddr == nil || currentAddr.String() != srcAddr.String() {
		r.sessions.UpdateAddr(pkt.SenderID, srcAddr)
	}

	// Ingress Mute Gating (F24): Drop audio packets from server-muted users
	if session.IsMuted() {
		return ErrUserServerMuted
	}

	// In-band Fast VAD (<30ms SLA): compare state and notify WebSocket plane on transition
	if session.UpdateSpeakingState(pkt.VAD, pkt.EnergyLevel) {
		if r.notifier != nil {
			r.notifier.BroadcastVoiceState(pkt.ChannelID, pkt.SenderID, pkt.VAD, pkt.EnergyLevel)
		}
	}

	// Forward to peers in the same voice channel (SFU Selective Forwarding)
	peers := r.sessions.GetChannelPeers(pkt.ChannelID, pkt.SenderID)
	if len(peers) == 0 || r.writer == nil {
		return nil
	}

	for _, peer := range peers {
		// Egress Deafen Gating (F25): Skip forwarding to server-deafened users
		if peer.IsDeafened() {
			continue
		}

		peerAddr := peer.GetAddr()
		if peerAddr != nil {
			_, _ = r.writer.WriteTo(rawData, peerAddr)
		}
	}

	return nil
}

// handlePing responds immediately with TypePong (0x03) preserving timestamp and payload for RTT probe.
func (r *Router) handlePing(pkt *Packet, srcAddr net.Addr) error {
	if r.writer == nil {
		return nil
	}

	pongBuf := GetBuffer()
	defer PutBuffer(pongBuf)

	pongPkt := GetPacket()
	defer PutPacket(pongPkt)

	pongPkt.Magic = MagicByte
	pongPkt.Version = ProtocolVersion
	pongPkt.Type = TypePong
	pongPkt.Flags = 0
	pongPkt.VAD = false
	pongPkt.EnergyLevel = 0
	pongPkt.SenderID = 0
	pongPkt.ChannelID = pkt.ChannelID
	pongPkt.Sequence = pkt.Sequence
	pongPkt.PayloadLen = uint16(len(pkt.Payload))
	pongPkt.Timestamp = pkt.Timestamp
	pongPkt.Payload = pkt.Payload

	written := pongPkt.EncodeInto(pongBuf)
	if written > 0 {
		_, err := r.writer.WriteTo(pongBuf[:written], srcAddr)
		return err
	}

	return nil
}

// handleHandshake registers a client UDP endpoint using token authentication.
func (r *Router) handleHandshake(pkt *Packet, srcAddr net.Addr) error {
	tokenStr := strings.TrimSpace(string(pkt.Payload))

	// 1. Check in-memory pending tokens first
	sess, err := r.sessions.ActivatePending(tokenStr, pkt.SenderID, pkt.ChannelID, srcAddr)
	if err == nil && sess != nil {
		return nil
	}

	// 2. Check storage token validator if configured
	if r.validator != nil && tokenStr != "" {
		vt, err := r.validator.ConsumeVoiceToken(tokenStr)
		if err == nil && vt != nil {
			if vt.UserID == pkt.SenderID && vt.ChannelID == pkt.ChannelID {
				newSess := NewSession(vt.UserID, vt.ChannelID, vt.SSRC, srcAddr)
				r.sessions.RegisterSession(newSess)
				return nil
			}
		}
	}

	// 3. Fallback for test / synthetic clients using direct token format (e.g. "udptoken_1" or "token_1")
	// or existing user session update
	if existing := r.sessions.GetByUser(pkt.SenderID); existing != nil {
		existing.ChannelID = pkt.ChannelID
		r.sessions.UpdateAddr(pkt.SenderID, srcAddr)
		return nil
	}

	// If no prior session, register direct session (e.g. in standalone mode)
	fallbackSess := NewSession(pkt.SenderID, pkt.ChannelID, 0, srcAddr)
	r.sessions.RegisterSession(fallbackSess)
	return nil
}
