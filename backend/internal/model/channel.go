package model

import "time"

// Channel represents a text or voice communication channel.
type Channel struct {
	ID        uint32    `json:"id" db:"id"`
	Name      string    `json:"name" db:"name"`
	Type      string    `json:"type" db:"type"` // "text" or "voice"
	Category  string    `json:"category" db:"category"`
	Position  int       `json:"position" db:"position"`
	Bitrate   int       `json:"bitrate" db:"bitrate"`       // Audio bitrate for voice (bps)
	UserLimit int       `json:"user_limit" db:"user_limit"` // Max concurrent users (default 15 for voice, 0 for unlimited text)
	CreatedAt time.Time `json:"created_at" db:"created_at"`
}
