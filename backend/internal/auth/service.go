package auth

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"low_latency_voice_app/backend/internal/model"
	"low_latency_voice_app/backend/internal/storage"
)

var (
	ErrInvalidUsernameFormat = errors.New("username must be between 3 and 32 characters and contain only alphanumeric, underscore, or hyphen")
	ErrPasswordTooShort      = errors.New("password must be at least 8 characters")
	ErrPasswordTooLong       = errors.New("password cannot exceed 128 characters")
	ErrInvalidCredentials    = errors.New("invalid username or password")
	ErrUserDisabled          = errors.New("user account is deactivated")
)

var usernameRegex = regexp.MustCompile(`^[a-zA-Z0-9_-]{3,32}$`)

type AuthResult struct {
	User        *model.User `json:"user"`
	UserID      uint32      `json:"user_id"`
	Username    string      `json:"username"`
	Token       string      `json:"token"`
	IsAdmin     bool        `json:"is_admin"`
	Roles       []string    `json:"roles"`
	Permissions uint32      `json:"permissions"`
	UDPPort     int         `json:"udp_port"`
	UDPToken    string      `json:"udp_token,omitempty"`
}

type Service interface {
	Register(username, password, clientVersion string) (*AuthResult, error)
	Login(username, password, clientVersion string) (*AuthResult, error)
	ValidateSession(token string) (*model.Session, error)
	GenerateUDPToken(userID, channelID uint32) (*model.VoiceToken, error)
	GenerateSessionToken() (string, error)
	UDPPort() int
}

type AuthService struct {
	storage storage.Repository
	udpPort int
}

func NewAuthService(storage storage.Repository, udpPort int) *AuthService {
	if udpPort == 0 {
		udpPort = 7878
	}
	return &AuthService{
		storage: storage,
		udpPort: udpPort,
	}
}

// UDPPort returns the configured UDP audio port.
func (s *AuthService) UDPPort() int {
	if s.udpPort == 0 {
		return 7878
	}
	return s.udpPort
}

func (s *AuthService) Register(username, password, clientVersion string) (*AuthResult, error) {
	username = strings.TrimSpace(username)
	if !usernameRegex.MatchString(username) {
		return nil, ErrInvalidUsernameFormat
	}
	if len(password) < 8 {
		return nil, ErrPasswordTooShort
	}
	if len(password) > 128 {
		return nil, ErrPasswordTooLong
	}

	hash, err := HashPassword(password)
	if err != nil {
		return nil, fmt.Errorf("failed to hash password: %w", err)
	}

	user, err := s.storage.CreateUser(username, hash)
	if err != nil {
		return nil, err
	}

	var roles []string
	var perms uint32
	var isAdmin bool

	// Check if this is the first user registered on the server (Creator Bootstrap: User ID == 1)
	if user.ID == 1 {
		// Bootstrap Creator as Admin
		adminRole, err := s.storage.GetRoleByName("Admin")
		if err == nil && adminRole != nil {
			_ = s.storage.AssignUserRole(user.ID, adminRole.ID)
		}
		roles = []string{"Admin"}
		perms = uint32(model.PermAll)
		isAdmin = true
	} else {
		// Assign default Member role
		memberRole, err := s.storage.GetDefaultRole()
		if err == nil && memberRole != nil {
			_ = s.storage.AssignUserRole(user.ID, memberRole.ID)
			roles = []string{memberRole.Name}
			perms = uint32(memberRole.Permissions)
		} else {
			roles = []string{"Member"}
			perms = uint32(model.PermDefaultMember)
		}
		isAdmin = false
	}

	user.Roles = roles
	user.Permissions = perms
	user.IsAdmin = isAdmin

	// Generate 256-bit session token
	sessionToken, err := s.GenerateSessionToken()
	if err != nil {
		return nil, err
	}

	expiresAt := time.Now().UTC().Add(30 * 24 * time.Hour) // 30 days
	_, err = s.storage.CreateSession(sessionToken, user.ID, expiresAt)
	if err != nil {
		return nil, fmt.Errorf("failed to save session: %w", err)
	}

	return &AuthResult{
		User:        user,
		UserID:      user.ID,
		Username:    user.Username,
		Token:       sessionToken,
		IsAdmin:     isAdmin,
		Roles:       roles,
		Permissions: perms,
		UDPPort:     s.udpPort,
	}, nil
}

func (s *AuthService) Login(username, password, clientVersion string) (*AuthResult, error) {
	username = strings.TrimSpace(username)
	if username == "" || password == "" {
		return nil, ErrInvalidCredentials
	}

	user, err := s.storage.GetUserByUsername(username)
	if err != nil {
		if errors.Is(err, storage.ErrUserNotFound) {
			return nil, ErrInvalidCredentials
		}
		return nil, err
	}

	if !user.IsActive {
		return nil, ErrUserDisabled
	}

	match, err := VerifyPassword(password, user.PasswordHash)
	if err != nil || !match {
		return nil, ErrInvalidCredentials
	}

	// Fetch roles and permissions
	userWithRoles, roles, perms, err := s.storage.GetUserWithRoles(user.ID)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch user roles: %w", err)
	}

	sessionToken, err := s.GenerateSessionToken()
	if err != nil {
		return nil, err
	}

	expiresAt := time.Now().UTC().Add(30 * 24 * time.Hour)
	_, err = s.storage.CreateSession(sessionToken, user.ID, expiresAt)
	if err != nil {
		return nil, fmt.Errorf("failed to save session: %w", err)
	}

	return &AuthResult{
		User:        userWithRoles,
		UserID:      user.ID,
		Username:    user.Username,
		Token:       sessionToken,
		IsAdmin:     userWithRoles.IsAdmin,
		Roles:       roles,
		Permissions: perms,
		UDPPort:     s.udpPort,
	}, nil
}

func (s *AuthService) ValidateSession(token string) (*model.Session, error) {
	token = strings.TrimSpace(token)
	if token == "" {
		return nil, storage.ErrSessionNotFound
	}
	return s.storage.GetSession(token)
}

func (s *AuthService) GenerateUDPToken(userID, channelID uint32) (*model.VoiceToken, error) {
	tokenBytes := make([]byte, 16)
	if _, err := rand.Read(tokenBytes); err != nil {
		return nil, fmt.Errorf("failed to generate random token bytes: %w", err)
	}
	token := hex.EncodeToString(tokenBytes)

	// Random 32-bit SSRC
	var ssrcBytes [4]byte
	if _, err := rand.Read(ssrcBytes[:]); err != nil {
		return nil, fmt.Errorf("failed to generate random SSRC: %w", err)
	}
	ssrc := binary.BigEndian.Uint32(ssrcBytes[:])
	if ssrc == 0 {
		ssrc = 100001
	}

	expiresAt := time.Now().UTC().Add(30 * time.Second)
	return s.storage.CreateVoiceToken(token, userID, channelID, ssrc, expiresAt)
}

func (s *AuthService) GenerateSessionToken() (string, error) {
	b := make([]byte, 32) // 256-bit entropy
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("failed to generate crypto rand bytes: %w", err)
	}
	return hex.EncodeToString(b), nil
}
