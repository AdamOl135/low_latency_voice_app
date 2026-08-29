package control

import (
	"context"
	"encoding/json"
	"log"
	"sync"
	"time"

	"low_latency_voice_app/backend/internal/audio"
	"low_latency_voice_app/backend/internal/auth"
	"low_latency_voice_app/backend/internal/model"
	"low_latency_voice_app/backend/internal/storage"
)

// BroadcastMessage defines a scoped broadcast targeting all or filtered clients.
type BroadcastMessage struct {
	Payload   []byte
	ChannelID uint32 // 0 = global broadcast to all authenticated clients
	Exclude   *Client
}

// Hub maintains active client connections, channel memberships, and broadcasts messages.
type Hub struct {
	// Registered active clients.
	clients map[*Client]bool

	// Mapping of User ID -> set of active Clients (supports multiple devices/tabs).
	userClients map[uint32]map[*Client]bool

	// Voice channel occupancy: ChannelID -> set of Clients in that voice channel.
	voiceChannels map[uint32]map[*Client]bool

	// In-memory voice state cache: UserID -> VoiceState.
	voiceStates map[uint32]*model.VoiceState

	// Inbound registration requests from clients.
	register chan *Client

	// Inbound unregister requests from clients.
	unregister chan *Client

	// Inbound messages to broadcast.
	broadcast chan *BroadcastMessage

	// RWMutex protecting maps.
	mu sync.RWMutex

	// Storage repository for database operations.
	storage storage.Repository

	// Auth service for token management and validation.
	authService auth.Service

	// Attached UDP SFU audio router for media plane synchronization.
	audioRouter *audio.Router

	// Context for graceful shutdown.
	ctx    context.Context
	cancel context.CancelFunc
}

// NewHub creates a new WebSocket Hub instance.
func NewHub(storage storage.Repository, authService auth.Service) *Hub {
	ctx, cancel := context.WithCancel(context.Background())
	return &Hub{
		clients:       make(map[*Client]bool),
		userClients:   make(map[uint32]map[*Client]bool),
		voiceChannels: make(map[uint32]map[*Client]bool),
		voiceStates:   make(map[uint32]*model.VoiceState),
		register:      make(chan *Client, 128),
		unregister:    make(chan *Client, 128),
		broadcast:     make(chan *BroadcastMessage, 256),
		storage:       storage,
		authService:   authService,
		ctx:           ctx,
		cancel:        cancel,
	}
}

// RegisterClient adds an active client to the hub connection set.
func (h *Hub) RegisterClient(client *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	client.mu.RLock()
	isClosed := client.closed
	client.mu.RUnlock()
	if !isClosed {
		h.clients[client] = true
	}
}

// UnregisterClient removes a client and handles complete disconnection cleanup.
func (h *Hub) UnregisterClient(client *Client) {
	h.handleClientDisconnect(client)
}

// Run executes the central Hub event loop.
func (h *Hub) Run() {
	for {
		select {
		case <-h.ctx.Done():
			h.cleanupAll()
			return

		case client := <-h.register:
			h.RegisterClient(client)

		case client := <-h.unregister:
			h.UnregisterClient(client)

		case message := <-h.broadcast:
			h.dispatchBroadcast(message)
		}
	}
}

// Close gracefully stops the Hub and shuts down client connections.
func (h *Hub) Close() {
	h.cancel()
}

func (h *Hub) cleanupAll() {
	h.mu.Lock()
	defer h.mu.Unlock()
	for client := range h.clients {
		client.Close()
		delete(h.clients, client)
	}
}

// handleClientDisconnect cleans up client data structures and broadcasts departure events.
func (h *Hub) handleClientDisconnect(client *Client) {
	h.mu.Lock()
	if _, ok := h.clients[client]; !ok {
		h.mu.Unlock()
		return
	}

	delete(h.clients, client)
	client.Close()

	var departedVoiceChannel uint32
	var userID uint32
	var username string
	wasAuthenticated := client.isAuthenticated

	if wasAuthenticated {
		userID = client.userID
		username = client.username

		// Remove from userClients map
		if userMap, exists := h.userClients[userID]; exists {
			delete(userMap, client)
			if len(userMap) == 0 {
				delete(h.userClients, userID)
			}
		}

		// Remove from voice channel if active
		if client.activeVoiceChannel > 0 {
			departedVoiceChannel = client.activeVoiceChannel
			if vMap, exists := h.voiceChannels[departedVoiceChannel]; exists {
				delete(vMap, client)
				if len(vMap) == 0 {
					delete(h.voiceChannels, departedVoiceChannel)
				}
			}
		}

		// If this client had active voice or user has no active sessions, clean up voice state
		if client.activeVoiceChannel > 0 || len(h.userClients[userID]) == 0 {
			delete(h.voiceStates, userID)
		}
	}
	h.mu.Unlock()

	if wasAuthenticated {
		// If user left a voice channel, broadcast voice state update
		if departedVoiceChannel > 0 {
			if h.audioRouter != nil {
				h.audioRouter.Sessions().RemoveSession(userID)
			}
			h.BroadcastEvent("voice_state_update", map[string]interface{}{
				"user_id":         userID,
				"username":        username,
				"channel_id":      nil,
				"is_speaking":     false,
				"self_muted":      false,
				"self_deafened":   false,
				"server_muted":    false,
				"server_deafened": false,
			})
		}

		// If no remaining active connections exist for this user, broadcast offline presence
		h.mu.RLock()
		remainingSessions := len(h.userClients[userID])
		h.mu.RUnlock()

		if remainingSessions == 0 {
			h.BroadcastEvent("presence_update", map[string]interface{}{
				"user_id":          userID,
				"username":         username,
				"online":           false,
				"status":           "offline",
				"voice_channel_id": nil,
				"last_seen":        time.Now().UTC().Unix(),
			})
		}
	}
}

// dispatchBroadcast sends bytes to target clients with non-blocking protection.
func (h *Hub) dispatchBroadcast(msg *BroadcastMessage) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	if msg.ChannelID == 0 {
		// Global broadcast to all authenticated clients
		for client := range h.clients {
			if client == msg.Exclude || !client.isAuthenticated {
				continue
			}
			client.Send(msg.Payload)
		}
	} else {
		// Scoped broadcast to clients in specific channel
		if clientsInChannel, ok := h.voiceChannels[msg.ChannelID]; ok {
			for client := range clientsInChannel {
				if client == msg.Exclude || !client.isAuthenticated {
					continue
				}
				client.Send(msg.Payload)
			}
		}
	}
}

// BroadcastEvent serializes an event envelope and broadcasts it globally.
func (h *Hub) BroadcastEvent(eventName string, data map[string]interface{}) {
	payload := NewBroadcastPayload(eventName, data)
	bytes, err := json.Marshal(payload)
	if err != nil {
		log.Printf("[Hub] Failed to marshal event %s: %v", eventName, err)
		return
	}
	msg := &BroadcastMessage{
		Payload:   bytes,
		ChannelID: 0,
	}
	select {
	case h.broadcast <- msg:
	default:
		go func() {
			select {
			case h.broadcast <- msg:
			case <-time.After(500 * time.Millisecond):
			}
		}()
	}
}

// BroadcastToChannel sends an event to members of a specific channel.
func (h *Hub) BroadcastToChannel(channelID uint32, eventName string, data map[string]interface{}) {
	payload := NewBroadcastPayload(eventName, data)
	bytes, err := json.Marshal(payload)
	if err != nil {
		log.Printf("[Hub] Failed to marshal channel event %s: %v", eventName, err)
		return
	}
	msg := &BroadcastMessage{
		Payload:   bytes,
		ChannelID: channelID,
	}
	select {
	case h.broadcast <- msg:
	default:
		go func() {
			select {
			case h.broadcast <- msg:
			case <-time.After(500 * time.Millisecond):
			}
		}()
	}
}

// Unicast sends a direct message to a specific user across all active sessions.
func (h *Hub) Unicast(userID uint32, payload []byte) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	if clients, exists := h.userClients[userID]; exists {
		for client := range clients {
			client.Send(payload)
		}
	}
}

// IsUserOnline returns true if user has at least one active WebSocket session.
func (h *Hub) IsUserOnline(userID uint32) bool {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.userClients[userID]) > 0
}

// GetUserVoiceState returns a copy of the user's active voice state if present.
func (h *Hub) GetUserVoiceState(userID uint32) *model.VoiceState {
	h.mu.RLock()
	defer h.mu.RUnlock()
	if vs, ok := h.voiceStates[userID]; ok {
		cp := *vs
		return &cp
	}
	return nil
}

// SetAudioRouter attaches the UDP SFU audio router to the control Hub.
func (h *Hub) SetAudioRouter(router *audio.Router) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.audioRouter = router
}

// AudioRouter returns the attached audio router if present.
func (h *Hub) AudioRouter() *audio.Router {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return h.audioRouter
}

// BroadcastVoiceState implements audio.VADNotifier to broadcast fast VAD updates to the channel.
func (h *Hub) BroadcastVoiceState(channelID uint32, userID uint32, speaking bool, energy uint8) {
	h.mu.Lock()
	if vs, ok := h.voiceStates[userID]; ok && vs != nil {
		vs.IsSpeaking = speaking
	}
	h.mu.Unlock()

	h.BroadcastToChannel(channelID, "voice_state_update", map[string]interface{}{
		"user_id":     userID,
		"channel_id":  channelID,
		"speaking":    speaking,
		"is_speaking": speaking,
		"energy":      energy,
	})
}

