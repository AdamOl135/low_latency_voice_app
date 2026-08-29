package model

import "time"

// Message represents an immutable text chat entry in a text channel.
type Message struct {
	ID        uint64    `json:"id" db:"id"`
	ChannelID uint32    `json:"channel_id" db:"channel_id"`
	SenderID  uint32    `json:"sender_id" db:"sender_id"`
	SenderName string   `json:"sender_name"`
	Content   string    `json:"content" db:"content"`
	CreatedAt time.Time `json:"created_at" db:"created_at"`
	Timestamp int64     `json:"timestamp"`
}
