package model

import "time"

// User represents an authenticated account in the system.
type User struct {
	ID           uint32    `json:"id" db:"id"`
	Username     string    `json:"username" db:"username"`
	PasswordHash string    `json:"-" db:"password_hash"`
	IsActive     bool      `json:"is_active" db:"is_active"`
	Roles        []string  `json:"roles,omitempty"`
	Permissions  uint32    `json:"permissions"`
	IsAdmin      bool      `json:"is_admin"`
	CreatedAt    time.Time `json:"created_at" db:"created_at"`
	UpdatedAt    time.Time `json:"updated_at" db:"updated_at"`
}

// UserProfile provides public user details for member listings and presence.
type UserProfile struct {
	ID        uint32    `json:"user_id"`
	Username  string    `json:"username"`
	Roles     []string  `json:"roles"`
	IsAdmin   bool      `json:"is_admin"`
	Online    bool      `json:"online"`
	LastSeen  int64     `json:"last_seen,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

// VoiceState represents a user's real-time voice channel participation and state.
type VoiceState struct {
	UserID         uint32    `json:"user_id"`
	Username       string    `json:"username"`
	ChannelID      uint32    `json:"channel_id"`
	IsSpeaking     bool      `json:"is_speaking"`
	SelfMuted      bool      `json:"self_muted"`
	SelfDeafened   bool      `json:"self_deafened"`
	ServerMuted    bool      `json:"server_muted"`
	ServerDeafened bool      `json:"server_deafened"`
	UpdatedAt      time.Time `json:"updated_at"`
}
