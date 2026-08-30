package storage

import (
	"database/sql"
	"fmt"
	"strings"
	"time"

	"low_latency_voice_app/backend/internal/model"
)

// SQLiteRepository implements Repository backed by SQLite WAL.
type SQLiteRepository struct {
	db *sql.DB
}

// NewSQLiteRepository creates a new SQLite repository instance.
func NewSQLiteRepository(db *sql.DB) *SQLiteRepository {
	return &SQLiteRepository{db: db}
}

// --- Users ---

func (r *SQLiteRepository) CreateUser(username, passwordHash string) (*model.User, error) {
	username = strings.TrimSpace(username)
	now := time.Now().UTC()

	var id int64
	query := `INSERT INTO users (username, password_hash, is_active, created_at, updated_at) VALUES (?, ?, 1, ?, ?) RETURNING id`
	err := r.db.QueryRow(query, username, passwordHash, now, now).Scan(&id)
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") || strings.Contains(strings.ToLower(err.Error()), "constraint") {
			return nil, ErrDuplicateUser
		}
		return nil, fmt.Errorf("failed to insert user: %w", err)
	}

	return &model.User{
		ID:           uint32(id),
		Username:     username,
		PasswordHash: passwordHash,
		IsActive:     true,
		CreatedAt:    now,
		UpdatedAt:    now,
	}, nil
}

func (r *SQLiteRepository) GetUserByID(id uint32) (*model.User, error) {
	query := `SELECT id, username, password_hash, is_active, created_at, updated_at FROM users WHERE id = ?`
	row := r.db.QueryRow(query, id)

	var u model.User
	var createdAt, updatedAt string
	var isActive int
	err := row.Scan(&u.ID, &u.Username, &u.PasswordHash, &isActive, &createdAt, &updatedAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrUserNotFound
		}
		return nil, fmt.Errorf("failed to get user by id %d: %w", id, err)
	}
	u.IsActive = (isActive == 1)
	u.CreatedAt, _ = parseTime(createdAt)
	u.UpdatedAt, _ = parseTime(updatedAt)
	return &u, nil
}

func (r *SQLiteRepository) GetUserByUsername(username string) (*model.User, error) {
	query := `SELECT id, username, password_hash, is_active, created_at, updated_at FROM users WHERE username = ? COLLATE NOCASE`
	row := r.db.QueryRow(query, strings.TrimSpace(username))

	var u model.User
	var createdAt, updatedAt string
	var isActive int
	err := row.Scan(&u.ID, &u.Username, &u.PasswordHash, &isActive, &createdAt, &updatedAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrUserNotFound
		}
		return nil, fmt.Errorf("failed to get user by username %s: %w", username, err)
	}
	u.IsActive = (isActive == 1)
	u.CreatedAt, _ = parseTime(createdAt)
	u.UpdatedAt, _ = parseTime(updatedAt)
	return &u, nil
}

func (r *SQLiteRepository) GetUserCount() (int, error) {
	var count int
	err := r.db.QueryRow(`SELECT COUNT(*) FROM users`).Scan(&count)
	if err != nil {
		return 0, fmt.Errorf("failed to count users: %w", err)
	}
	return count, nil
}

func (r *SQLiteRepository) GetAllUsers() ([]*model.User, error) {
	rows, err := r.db.Query(`SELECT id, username, password_hash, is_active, created_at, updated_at FROM users ORDER BY id ASC`)
	if err != nil {
		return nil, fmt.Errorf("failed to query all users: %w", err)
	}
	defer rows.Close()

	var users []*model.User
	for rows.Next() {
		var u model.User
		var createdAt, updatedAt string
		var isActive int
		if err := rows.Scan(&u.ID, &u.Username, &u.PasswordHash, &isActive, &createdAt, &updatedAt); err != nil {
			return nil, fmt.Errorf("failed to scan user: %w", err)
		}
		u.IsActive = (isActive == 1)
		u.CreatedAt, _ = parseTime(createdAt)
		u.UpdatedAt, _ = parseTime(updatedAt)
		users = append(users, &u)
	}
	return users, nil
}

func (r *SQLiteRepository) GetUserWithRoles(id uint32) (*model.User, []string, uint32, error) {
	u, err := r.GetUserByID(id)
	if err != nil {
		return nil, nil, 0, err
	}

	roles, err := r.GetUserRoles(id)
	if err != nil {
		return nil, nil, 0, err
	}

	var roleNames []string
	var perms uint32
	for _, role := range roles {
		roleNames = append(roleNames, role.Name)
		perms |= uint32(role.Permissions)
	}

	// User ID 1 is always Admin with full permissions
	if u.ID == 1 {
		perms = uint32(model.PermAll)
		hasAdmin := false
		for _, name := range roleNames {
			if name == "Admin" {
				hasAdmin = true
				break
			}
		}
		if !hasAdmin {
			roleNames = append([]string{"Admin"}, roleNames...)
		}
	}

	isAdmin := model.HasPermission(perms, model.PermAdmin)
	u.Roles = roleNames
	u.Permissions = perms
	u.IsAdmin = isAdmin

	return u, roleNames, perms, nil
}

func (r *SQLiteRepository) GetAllUsersWithRoles() ([]*model.User, error) {
	users, err := r.GetAllUsers()
	if err != nil {
		return nil, err
	}

	for _, u := range users {
		roles, err := r.GetUserRoles(u.ID)
		if err != nil {
			return nil, err
		}

		var roleNames []string
		var perms uint32
		for _, role := range roles {
			roleNames = append(roleNames, role.Name)
			perms |= uint32(role.Permissions)
		}

		if u.ID == 1 {
			perms = uint32(model.PermAll)
			hasAdmin := false
			for _, name := range roleNames {
				if name == "Admin" {
					hasAdmin = true
					break
				}
			}
			if !hasAdmin {
				roleNames = append([]string{"Admin"}, roleNames...)
			}
		}

		u.Roles = roleNames
		u.Permissions = perms
		u.IsAdmin = model.HasPermission(perms, model.PermAdmin)
	}

	return users, nil
}

// --- Roles & Permissions ---

func (r *SQLiteRepository) GetRoleByName(name string) (*model.Role, error) {
	query := `SELECT id, name, permissions, position, is_default, created_at FROM roles WHERE name = ?`
	row := r.db.QueryRow(query, name)

	var role model.Role
	var createdAt string
	var isDefault int
	err := row.Scan(&role.ID, &role.Name, &role.Permissions, &role.Position, &isDefault, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrRoleNotFound
		}
		return nil, fmt.Errorf("failed to get role by name %s: %w", name, err)
	}
	role.IsDefault = (isDefault == 1)
	role.CreatedAt, _ = parseTime(createdAt)
	return &role, nil
}

func (r *SQLiteRepository) GetRoleByID(id uint32) (*model.Role, error) {
	query := `SELECT id, name, permissions, position, is_default, created_at FROM roles WHERE id = ?`
	row := r.db.QueryRow(query, id)

	var role model.Role
	var createdAt string
	var isDefault int
	err := row.Scan(&role.ID, &role.Name, &role.Permissions, &role.Position, &isDefault, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrRoleNotFound
		}
		return nil, fmt.Errorf("failed to get role by id %d: %w", id, err)
	}
	role.IsDefault = (isDefault == 1)
	role.CreatedAt, _ = parseTime(createdAt)
	return &role, nil
}

func (r *SQLiteRepository) GetDefaultRole() (*model.Role, error) {
	query := `SELECT id, name, permissions, position, is_default, created_at FROM roles WHERE is_default = 1 ORDER BY position ASC LIMIT 1`
	row := r.db.QueryRow(query)

	var role model.Role
	var createdAt string
	var isDefault int
	err := row.Scan(&role.ID, &role.Name, &role.Permissions, &role.Position, &isDefault, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrRoleNotFound
		}
		return nil, fmt.Errorf("failed to get default role: %w", err)
	}
	role.IsDefault = (isDefault == 1)
	role.CreatedAt, _ = parseTime(createdAt)
	return &role, nil
}

func (r *SQLiteRepository) AssignUserRole(userID uint32, roleID uint32) error {
	now := time.Now().UTC()
	_, err := r.db.Exec(`INSERT OR IGNORE INTO user_roles (user_id, role_id, assigned_at) VALUES (?, ?, ?)`, userID, roleID, now)
	if err != nil {
		return fmt.Errorf("failed to assign role %d to user %d: %w", roleID, userID, err)
	}
	return nil
}

func (r *SQLiteRepository) RemoveUserRole(userID uint32, roleID uint32) error {
	if userID == 1 && roleID == 1 {
		return ErrImmutableCreator
	}
	_, err := r.db.Exec(`DELETE FROM user_roles WHERE user_id = ? AND role_id = ?`, userID, roleID)
	if err != nil {
		return fmt.Errorf("failed to remove role %d from user %d: %w", roleID, userID, err)
	}
	return nil
}

func (r *SQLiteRepository) GetUserRoles(userID uint32) ([]*model.Role, error) {
	query := `
		SELECT r.id, r.name, r.permissions, r.position, r.is_default, r.created_at
		FROM roles r
		INNER JOIN user_roles ur ON ur.role_id = r.id
		WHERE ur.user_id = ?
		ORDER BY r.position DESC
	`
	rows, err := r.db.Query(query, userID)
	if err != nil {
		return nil, fmt.Errorf("failed to query user roles: %w", err)
	}
	defer rows.Close()

	var roles []*model.Role
	for rows.Next() {
		var role model.Role
		var createdAt string
		var isDefault int
		if err := rows.Scan(&role.ID, &role.Name, &role.Permissions, &role.Position, &isDefault, &createdAt); err != nil {
			return nil, fmt.Errorf("failed to scan role: %w", err)
		}
		role.IsDefault = (isDefault == 1)
		role.CreatedAt, _ = parseTime(createdAt)
		roles = append(roles, &role)
	}

	// If no roles assigned, load default role(s)
	if len(roles) == 0 {
		defRole, err := r.GetDefaultRole()
		if err == nil && defRole != nil {
			roles = append(roles, defRole)
		}
	}

	return roles, nil
}

func (r *SQLiteRepository) GetEffectivePermissions(userID uint32) (uint32, error) {
	if userID == 1 {
		return uint32(model.PermAll), nil
	}

	roles, err := r.GetUserRoles(userID)
	if err != nil {
		return 0, err
	}

	var perms uint32
	for _, role := range roles {
		perms |= uint32(role.Permissions)
	}
	return perms, nil
}

// --- Channels ---

func (r *SQLiteRepository) CreateChannel(name, channelType, category string, position, bitrate, userLimit int) (*model.Channel, error) {
	name = strings.TrimSpace(name)
	if category == "" {
		category = "General"
	}
	if bitrate == 0 {
		bitrate = 64000
	}
	if userLimit == 0 && channelType == "voice" {
		userLimit = 15
	}
	now := time.Now().UTC()

	var id int64
	query := `INSERT INTO channels (name, type, category, position, bitrate, user_limit, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id`
	err := r.db.QueryRow(query, name, channelType, category, position, bitrate, userLimit, now).Scan(&id)
	if err != nil {
		return nil, fmt.Errorf("failed to insert channel: %w", err)
	}

	return &model.Channel{
		ID:        uint32(id),
		Name:      name,
		Type:      channelType,
		Category:  category,
		Position:  position,
		Bitrate:   bitrate,
		UserLimit: userLimit,
		CreatedAt: now,
	}, nil
}

func (r *SQLiteRepository) GetChannelByID(id uint32) (*model.Channel, error) {
	query := `SELECT id, name, type, category, position, bitrate, user_limit, created_at FROM channels WHERE id = ?`
	row := r.db.QueryRow(query, id)

	var ch model.Channel
	var createdAt string
	err := row.Scan(&ch.ID, &ch.Name, &ch.Type, &ch.Category, &ch.Position, &ch.Bitrate, &ch.UserLimit, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrChannelNotFound
		}
		return nil, fmt.Errorf("failed to get channel by id %d: %w", id, err)
	}
	ch.CreatedAt, _ = parseTime(createdAt)
	return &ch, nil
}

func (r *SQLiteRepository) GetChannels() ([]*model.Channel, error) {
	query := `SELECT id, name, type, category, position, bitrate, user_limit, created_at FROM channels ORDER BY type DESC, category ASC, position ASC, id ASC`
	rows, err := r.db.Query(query)
	if err != nil {
		return nil, fmt.Errorf("failed to query channels: %w", err)
	}
	defer rows.Close()

	var channels []*model.Channel
	for rows.Next() {
		var ch model.Channel
		var createdAt string
		if err := rows.Scan(&ch.ID, &ch.Name, &ch.Type, &ch.Category, &ch.Position, &ch.Bitrate, &ch.UserLimit, &createdAt); err != nil {
			return nil, fmt.Errorf("failed to scan channel: %w", err)
		}
		ch.CreatedAt, _ = parseTime(createdAt)
		channels = append(channels, &ch)
	}
	return channels, nil
}

func (r *SQLiteRepository) DeleteChannel(id uint32) error {
	res, err := r.db.Exec(`DELETE FROM channels WHERE id = ?`, id)
	if err != nil {
		return fmt.Errorf("failed to delete channel %d: %w", id, err)
	}
	rowsAffected, err := res.RowsAffected()
	if err != nil {
		return err
	}
	if rowsAffected == 0 {
		return ErrChannelNotFound
	}
	return nil
}

// --- Messages ---

func (r *SQLiteRepository) CreateMessage(channelID, senderID uint32, content string) (*model.Message, error) {
	// Verify channel exists and is text
	ch, err := r.GetChannelByID(channelID)
	if err != nil {
		return nil, err
	}
	if ch.Type != "text" {
		return nil, fmt.Errorf("cannot post message to non-text channel")
	}

	sender, err := r.GetUserByID(senderID)
	if err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	var id int64
	query := `INSERT INTO messages (channel_id, sender_id, content, created_at) VALUES (?, ?, ?, ?) RETURNING id`
	err = r.db.QueryRow(query, channelID, senderID, content, now).Scan(&id)
	if err != nil {
		return nil, fmt.Errorf("failed to insert message: %w", err)
	}

	return &model.Message{
		ID:         uint64(id),
		ChannelID:  channelID,
		SenderID:   senderID,
		SenderName: sender.Username,
		Content:    content,
		CreatedAt:  now,
		Timestamp:  now.Unix(),
	}, nil
}

func (r *SQLiteRepository) GetMessages(channelID uint32, beforeID uint64, limit int) ([]*model.Message, bool, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}

	// Verify channel exists
	_, err := r.GetChannelByID(channelID)
	if err != nil {
		return nil, false, err
	}

	// Fetch limit+1 to determine has_more
	fetchLimit := limit + 1
	var rows *sql.Rows

	if beforeID == 0 {
		// Newest messages
		query := `
			SELECT m.id, m.channel_id, m.sender_id, u.username, m.content, m.created_at
			FROM messages m
			JOIN users u ON m.sender_id = u.id
			WHERE m.channel_id = ?
			ORDER BY m.id DESC
			LIMIT ?
		`
		rows, err = r.db.Query(query, channelID, fetchLimit)
	} else {
		// Messages before cursor ID
		query := `
			SELECT m.id, m.channel_id, m.sender_id, u.username, m.content, m.created_at
			FROM messages m
			JOIN users u ON m.sender_id = u.id
			WHERE m.channel_id = ? AND m.id < ?
			ORDER BY m.id DESC
			LIMIT ?
		`
		rows, err = r.db.Query(query, channelID, beforeID, fetchLimit)
	}

	if err != nil {
		return nil, false, fmt.Errorf("failed to query messages: %w", err)
	}
	defer rows.Close()

	var fetched []*model.Message
	for rows.Next() {
		var m model.Message
		var createdAt string
		if err := rows.Scan(&m.ID, &m.ChannelID, &m.SenderID, &m.SenderName, &m.Content, &createdAt); err != nil {
			return nil, false, fmt.Errorf("failed to scan message: %w", err)
		}
		m.CreatedAt, _ = parseTime(createdAt)
		m.Timestamp = m.CreatedAt.Unix()
		fetched = append(fetched, &m)
	}

	hasMore := len(fetched) > limit
	if hasMore {
		fetched = fetched[:limit]
	}

	// Reverse to return in chronological ascending order
	messages := make([]*model.Message, len(fetched))
	for i, msg := range fetched {
		messages[len(fetched)-1-i] = msg
	}

	return messages, hasMore, nil
}

func (r *SQLiteRepository) GetMessageByID(id uint64) (*model.Message, error) {
	query := `
		SELECT m.id, m.channel_id, m.sender_id, u.username, m.content, m.created_at
		FROM messages m
		JOIN users u ON m.sender_id = u.id
		WHERE m.id = ?
	`
	row := r.db.QueryRow(query, id)

	var m model.Message
	var createdAt string
	err := row.Scan(&m.ID, &m.ChannelID, &m.SenderID, &m.SenderName, &m.Content, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("message not found")
		}
		return nil, fmt.Errorf("failed to get message %d: %w", id, err)
	}
	m.CreatedAt, _ = parseTime(createdAt)
	m.Timestamp = m.CreatedAt.Unix()
	return &m, nil
}

// --- Sessions ---

func (r *SQLiteRepository) CreateSession(token string, userID uint32, expiresAt time.Time) (*model.Session, error) {
	now := time.Now().UTC()
	_, err := r.db.Exec(`INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)`, token, userID, expiresAt, now)
	if err != nil {
		return nil, fmt.Errorf("failed to insert session: %w", err)
	}
	return &model.Session{
		Token:     token,
		UserID:    userID,
		ExpiresAt: expiresAt,
		CreatedAt: now,
	}, nil
}

func (r *SQLiteRepository) GetSession(token string) (*model.Session, error) {
	query := `SELECT token, user_id, expires_at, created_at FROM sessions WHERE token = ?`
	row := r.db.QueryRow(query, token)

	var s model.Session
	var expiresAt, createdAt string
	err := row.Scan(&s.Token, &s.UserID, &expiresAt, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrSessionNotFound
		}
		return nil, fmt.Errorf("failed to get session: %w", err)
	}
	s.ExpiresAt, _ = parseTime(expiresAt)
	s.CreatedAt, _ = parseTime(createdAt)

	if time.Now().UTC().After(s.ExpiresAt) {
		_ = r.DeleteSession(token)
		return nil, ErrSessionExpired
	}

	return &s, nil
}

func (r *SQLiteRepository) DeleteSession(token string) error {
	_, err := r.db.Exec(`DELETE FROM sessions WHERE token = ?`, token)
	if err != nil {
		return fmt.Errorf("failed to delete session: %w", err)
	}
	return nil
}

func (r *SQLiteRepository) DeleteUserSessions(userID uint32) error {
	_, err := r.db.Exec(`DELETE FROM sessions WHERE user_id = ?`, userID)
	if err != nil {
		return fmt.Errorf("failed to delete user sessions: %w", err)
	}
	return nil
}

// --- Voice Tokens ---

func (r *SQLiteRepository) CreateVoiceToken(token string, userID, channelID, ssrc uint32, expiresAt time.Time) (*model.VoiceToken, error) {
	now := time.Now().UTC()
	_, err := r.db.Exec(`INSERT INTO voice_tokens (token, user_id, channel_id, ssrc, is_consumed, expires_at, created_at) VALUES (?, ?, ?, ?, 0, ?, ?)`,
		token, userID, channelID, ssrc, expiresAt, now)
	if err != nil {
		return nil, fmt.Errorf("failed to insert voice token: %w", err)
	}
	return &model.VoiceToken{
		Token:      token,
		UserID:     userID,
		ChannelID:  channelID,
		SSRC:       ssrc,
		IsConsumed: false,
		ExpiresAt:  expiresAt,
		CreatedAt:  now,
	}, nil
}

func (r *SQLiteRepository) GetVoiceToken(token string) (*model.VoiceToken, error) {
	query := `SELECT token, user_id, channel_id, ssrc, is_consumed, expires_at, created_at FROM voice_tokens WHERE token = ?`
	row := r.db.QueryRow(query, token)

	var vt model.VoiceToken
	var isConsumed int
	var expiresAt, createdAt string
	err := row.Scan(&vt.Token, &vt.UserID, &vt.ChannelID, &vt.SSRC, &isConsumed, &expiresAt, &createdAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, ErrVoiceTokenNotFound
		}
		return nil, fmt.Errorf("failed to get voice token: %w", err)
	}
	vt.IsConsumed = (isConsumed == 1)
	vt.ExpiresAt, _ = parseTime(expiresAt)
	vt.CreatedAt, _ = parseTime(createdAt)

	if vt.IsConsumed {
		return nil, ErrVoiceTokenConsumed
	}
	if time.Now().UTC().After(vt.ExpiresAt) {
		return nil, ErrVoiceTokenExpired
	}

	return &vt, nil
}

func (r *SQLiteRepository) ConsumeVoiceToken(token string) (*model.VoiceToken, error) {
	vt, err := r.GetVoiceToken(token)
	if err != nil {
		return nil, err
	}

	res, err := r.db.Exec(`UPDATE voice_tokens SET is_consumed = 1 WHERE token = ? AND is_consumed = 0`, token)
	if err != nil {
		return nil, fmt.Errorf("failed to consume voice token: %w", err)
	}
	affected, _ := res.RowsAffected()
	if affected == 0 {
		return nil, ErrVoiceTokenConsumed
	}

	vt.IsConsumed = true
	return vt, nil
}

func (r *SQLiteRepository) RevokeVoiceTokens(userID uint32) error {
	_, err := r.db.Exec(`DELETE FROM voice_tokens WHERE user_id = ?`, userID)
	if err != nil {
		return fmt.Errorf("failed to revoke voice tokens for user %d: %w", userID, err)
	}
	return nil
}

func parseTime(value string) (time.Time, error) {
	formats := []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02 15:04:05.999999999-07:00",
		"2006-01-02 15:04:05.999999999",
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05Z",
	}
	for _, f := range formats {
		if t, err := time.Parse(f, value); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("unrecognized time format: %s", value)
}
