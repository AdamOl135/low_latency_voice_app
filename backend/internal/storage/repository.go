package storage

import (
	"errors"
	"time"

	"low_latency_voice_app/backend/internal/model"
)

var (
	ErrDuplicateUser       = errors.New("username already exists")
	ErrUserNotFound        = errors.New("user not found")
	ErrChannelNotFound     = errors.New("channel not found")
	ErrRoleNotFound        = errors.New("role not found")
	ErrSessionNotFound     = errors.New("session not found")
	ErrSessionExpired      = errors.New("session expired")
	ErrVoiceTokenNotFound  = errors.New("voice token not found")
	ErrVoiceTokenExpired   = errors.New("voice token expired")
	ErrVoiceTokenConsumed  = errors.New("voice token already consumed")
	ErrImmutableCreator    = errors.New("creator admin role cannot be modified or removed")
)

// Repository defines all persistent operations for the communication server.
type Repository interface {
	// Users
	CreateUser(username, passwordHash string) (*model.User, error)
	GetUserByID(id uint32) (*model.User, error)
	GetUserByUsername(username string) (*model.User, error)
	GetUserCount() (int, error)
	GetAllUsers() ([]*model.User, error)
	GetUserWithRoles(id uint32) (*model.User, []string, uint32, error)
	GetAllUsersWithRoles() ([]*model.User, error)

	// Roles & Permissions
	GetRoleByName(name string) (*model.Role, error)
	GetRoleByID(id uint32) (*model.Role, error)
	GetDefaultRole() (*model.Role, error)
	AssignUserRole(userID uint32, roleID uint32) error
	RemoveUserRole(userID uint32, roleID uint32) error
	GetUserRoles(userID uint32) ([]*model.Role, error)
	GetEffectivePermissions(userID uint32) (uint32, error)

	// Channels
	CreateChannel(name, channelType, category string, position, bitrate, userLimit int) (*model.Channel, error)
	GetChannelByID(id uint32) (*model.Channel, error)
	GetChannels() ([]*model.Channel, error)
	DeleteChannel(id uint32) error

	// Messages
	CreateMessage(channelID, senderID uint32, content string) (*model.Message, error)
	GetMessages(channelID uint32, beforeID uint64, limit int) ([]*model.Message, bool, error)
	GetMessageByID(id uint64) (*model.Message, error)

	// Sessions
	CreateSession(token string, userID uint32, expiresAt time.Time) (*model.Session, error)
	GetSession(token string) (*model.Session, error)
	DeleteSession(token string) error
	DeleteUserSessions(userID uint32) error

	// Voice Tokens
	CreateVoiceToken(token string, userID, channelID, ssrc uint32, expiresAt time.Time) (*model.VoiceToken, error)
	GetVoiceToken(token string) (*model.VoiceToken, error)
	ConsumeVoiceToken(token string) (*model.VoiceToken, error)
	RevokeVoiceTokens(userID uint32) error
}
