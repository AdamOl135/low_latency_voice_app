package model

import "time"

// Session represents an authenticated WebSocket/HTTP session token.
type Session struct {
	Token     string    `json:"token" db:"token"`
	UserID    uint32    `json:"user_id" db:"user_id"`
	ExpiresAt time.Time `json:"expires_at" db:"expires_at"`
	CreatedAt time.Time `json:"created_at" db:"created_at"`
}
