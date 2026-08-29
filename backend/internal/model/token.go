package model

import "time"

// VoiceToken represents an ephemeral single-use cryptographic token for authenticating UDP audio streams.
type VoiceToken struct {
	Token      string    `json:"token" db:"token"`
	UserID     uint32    `json:"user_id" db:"user_id"`
	ChannelID  uint32    `json:"channel_id" db:"channel_id"`
	SSRC       uint32    `json:"ssrc" db:"ssrc"`
	IsConsumed bool      `json:"is_consumed" db:"is_consumed"`
	ExpiresAt  time.Time `json:"expires_at" db:"expires_at"`
	CreatedAt  time.Time `json:"created_at" db:"created_at"`
}
