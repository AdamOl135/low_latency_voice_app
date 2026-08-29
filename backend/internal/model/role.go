package model

import "time"

// Permission represents a 32-bit unsigned bitfield for role capabilities.
type Permission uint32

const (
	PermAdmin          Permission = 1 << 0 // 0x0001: Full administrative overrides
	PermManageChannels Permission = 1 << 1 // 0x0002: Create, edit, and delete channels
	PermMoveMembers    Permission = 1 << 2 // 0x0004: Move members between voice channels
	PermMuteMembers    Permission = 1 << 3 // 0x0008: Server-mute members
	PermDeafenMembers  Permission = 1 << 4 // 0x0010: Server-deafen members
	PermKickMembers    Permission = 1 << 5 // 0x0020: Kick members from server
	PermSendMessages   Permission = 1 << 6 // 0x0040: Send text messages in text channels
	PermConnectVoice   Permission = 1 << 7 // 0x0080: Connect to voice channels
	PermSpeak          Permission = 1 << 8 // 0x0100: Transmit audio in voice channels

	// Composite Presets
	PermAll           Permission = 0xFFFFFFFF
	PermDefaultMember Permission = PermSendMessages | PermConnectVoice | PermSpeak // 448 (0x01C0)
	PermModerator     Permission = PermManageChannels | PermMoveMembers | PermMuteMembers |
		PermDeafenMembers | PermKickMembers | PermSendMessages |
		PermConnectVoice | PermSpeak // 510 (0x01FE)
)

// Role represents a user grouping with assigned permission bitfield.
type Role struct {
	ID          uint32     `json:"id" db:"id"`
	Name        string     `json:"name" db:"name"`
	Permissions Permission `json:"permissions" db:"permissions"`
	Position    int        `json:"position" db:"position"`
	IsDefault   bool       `json:"is_default" db:"is_default"`
	CreatedAt   time.Time  `json:"created_at" db:"created_at"`
}

// HasPermission checks if the effective permissions contain the required flag.
// Admin permission (0x0001 or 0xFFFFFFFF) bypasses all capability checks.
func HasPermission(effectivePerms uint32, required Permission) bool {
	p := Permission(effectivePerms)
	if (p & PermAdmin) == PermAdmin {
		return true
	}
	return (p & required) == required
}
