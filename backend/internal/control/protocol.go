package control

import (
	"encoding/json"
	"time"
)

// RequestEnvelope is the universal envelope for inbound client messages.
type RequestEnvelope struct {
	ID        interface{}            `json:"id,omitempty"`
	Action    string                 `json:"action"`
	RequestID string                 `json:"request_id,omitempty"`
	Params    map[string]interface{} `json:"params,omitempty"`

	// Direct top-level fields for convenience
	Token         string  `json:"token,omitempty"`
	Username      string  `json:"username,omitempty"`
	Password      string  `json:"password,omitempty"`
	ClientVersion string  `json:"client_version,omitempty"`
	ChannelID     uint32  `json:"channel_id,omitempty"`
	Content       string  `json:"content,omitempty"`
	BeforeID      uint64  `json:"before_id,omitempty"`
	Limit         int     `json:"limit,omitempty"`
	Name          string  `json:"name,omitempty"`
	Type          string  `json:"type,omitempty"`
	Category      string  `json:"category,omitempty"`
	Position      int     `json:"position,omitempty"`
	Bitrate       int     `json:"bitrate,omitempty"`
	UserLimit     int     `json:"user_limit,omitempty"`
	SelfMuted     bool    `json:"self_muted,omitempty"`
	SelfDeafened  bool    `json:"self_deafened,omitempty"`
	TargetUserID  uint32  `json:"target_user_id,omitempty"`
	ToChannelID   uint32  `json:"to_channel_id,omitempty"`
	Muted         bool    `json:"muted,omitempty"`
	Deafened      bool    `json:"deafened,omitempty"`
	Reason        string  `json:"reason,omitempty"`
	RawPayload    json.RawMessage `json:"-"`
}

// SuccessResponse represents a standard JSON-RPC success response.
type SuccessResponse struct {
	ID        interface{} `json:"id"`
	Status    string      `json:"status"` // "ok"
	Action    string      `json:"action,omitempty"`
	RequestID string      `json:"request_id,omitempty"`
	Result    interface{} `json:"result,omitempty"`
	Data      interface{} `json:"data,omitempty"`
}

// BroadcastEvent represents an outbound fan-out event.
type BroadcastEvent struct {
	Event     string      `json:"event"`
	Data      interface{} `json:"data"`
	Timestamp int64       `json:"timestamp"`
}

// NewSuccessResponse formats a standard success response with both 'result' and 'data' fields populated.
func NewSuccessResponse(id interface{}, action string, payload interface{}) map[string]interface{} {
	var reqIDStr string
	if s, ok := id.(string); ok {
		reqIDStr = s
	}

	resp := map[string]interface{}{
		"id":        id,
		"status":    "ok",
		"action":    action,
		"result":    payload,
		"data":      payload,
	}
	if reqIDStr != "" {
		resp["request_id"] = reqIDStr
	}

	// Flatten struct/map fields into top-level for alternative JSON-RPC client styles
	if m, ok := payload.(map[string]interface{}); ok {
		for k, v := range m {
			if _, exists := resp[k]; !exists {
				resp[k] = v
			}
		}
	}

	return resp
}

// NewBroadcastPayload formats an event envelope with timestamp.
func NewBroadcastPayload(eventName string, data map[string]interface{}) map[string]interface{} {
	now := time.Now().UTC().Unix()
	envelope := map[string]interface{}{
		"event":     eventName,
		"data":      data,
		"timestamp": now,
	}
	// Also expose top-level fields for flat consumer clients
	for k, v := range data {
		if _, exists := envelope[k]; !exists {
			envelope[k] = v
		}
	}
	return envelope
}

// ChatMessageEvent is the typed structure for chat broadcast events.
type ChatMessageEvent struct {
	ID         uint64 `json:"id"`
	ChannelID  uint32 `json:"channel_id"`
	SenderID   uint32 `json:"sender_id"`
	SenderName string `json:"sender_name"`
	Content    string `json:"content"`
	Timestamp  int64  `json:"timestamp"`
}

// PresenceUpdateEvent is the typed structure for online/offline updates.
type PresenceUpdateEvent struct {
	UserID         uint32   `json:"user_id"`
	Username       string   `json:"username"`
	Online         bool     `json:"online"`
	Status         string   `json:"status"` // "online" or "offline"
	Roles          []string `json:"roles,omitempty"`
	VoiceChannelID *uint32  `json:"voice_channel_id,omitempty"`
	LastSeen       int64    `json:"last_seen,omitempty"`
}

// VoiceStateUpdateEvent is the typed structure for voice membership/mute changes.
type VoiceStateUpdateEvent struct {
	UserID         uint32  `json:"user_id"`
	Username       string  `json:"username,omitempty"`
	ChannelID      *uint32 `json:"channel_id"`
	IsSpeaking     bool    `json:"is_speaking"`
	SelfMuted      bool    `json:"self_muted"`
	SelfDeafened   bool    `json:"self_deafened"`
	ServerMuted    bool    `json:"server_muted"`
	ServerDeafened bool    `json:"server_deafened"`
}
