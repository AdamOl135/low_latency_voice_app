package storage

import (
	"database/sql"
	"fmt"
	"time"
)

// Migration represents a database schema version step.
type Migration struct {
	Version int
	Up      string
}

var migrations = []Migration{
	{
		Version: 1,
		Up: `
		CREATE TABLE IF NOT EXISTS schema_migrations (
			version INTEGER PRIMARY KEY,
			applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
		);

		CREATE TABLE IF NOT EXISTS users (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			username TEXT COLLATE NOCASE NOT NULL UNIQUE,
			password_hash TEXT NOT NULL,
			is_active INTEGER DEFAULT 1 NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
		);
		CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);

		CREATE TABLE IF NOT EXISTS roles (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL UNIQUE,
			permissions INTEGER NOT NULL,
			position INTEGER DEFAULT 0 NOT NULL,
			is_default INTEGER DEFAULT 0 NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
		);

		CREATE TABLE IF NOT EXISTS user_roles (
			user_id INTEGER NOT NULL,
			role_id INTEGER NOT NULL,
			assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
			PRIMARY KEY (user_id, role_id),
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
			FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
		);
		CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
		CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id);

		CREATE TABLE IF NOT EXISTS channels (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			name TEXT NOT NULL,
			type TEXT CHECK(type IN ('text', 'voice')) NOT NULL,
			category TEXT DEFAULT 'General' NOT NULL,
			position INTEGER DEFAULT 0 NOT NULL,
			bitrate INTEGER DEFAULT 64000 NOT NULL,
			user_limit INTEGER DEFAULT 15 NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_channels_type_category ON channels(type, category, position);

		CREATE TABLE IF NOT EXISTS messages (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			channel_id INTEGER NOT NULL,
			sender_id INTEGER NOT NULL,
			content TEXT NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
			FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
			FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
		);
		CREATE INDEX IF NOT EXISTS idx_messages_channel_id ON messages(channel_id, id DESC);
		CREATE INDEX IF NOT EXISTS idx_messages_sender_id ON messages(sender_id);

		CREATE TABLE IF NOT EXISTS sessions (
			token TEXT PRIMARY KEY,
			user_id INTEGER NOT NULL,
			expires_at TIMESTAMP NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
		);
		CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
		CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

		CREATE TABLE IF NOT EXISTS voice_tokens (
			token TEXT PRIMARY KEY,
			user_id INTEGER NOT NULL,
			channel_id INTEGER NOT NULL,
			ssrc INTEGER NOT NULL,
			is_consumed INTEGER DEFAULT 0 NOT NULL,
			expires_at TIMESTAMP NOT NULL,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
			FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
			FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE
		);
		CREATE INDEX IF NOT EXISTS idx_voice_tokens_lookup ON voice_tokens(token, is_consumed, expires_at);

		-- Seed default roles
		INSERT OR IGNORE INTO roles (id, name, permissions, position, is_default, created_at)
		VALUES 
			(1, 'Admin', 4294967295, 100, 0, CURRENT_TIMESTAMP),
			(2, 'Moderator', 510, 50, 0, CURRENT_TIMESTAMP),
			(3, 'Member', 448, 0, 1, CURRENT_TIMESTAMP);

		-- Seed default channels
		INSERT OR IGNORE INTO channels (id, name, type, category, position, bitrate, user_limit, created_at)
		VALUES
			(1, 'general', 'text', 'Text Channels', 1, 64000, 0, CURRENT_TIMESTAMP),
			(2, 'lounge', 'voice', 'Voice Channels', 1, 64000, 15, CURRENT_TIMESTAMP),
			(3, 'gaming', 'voice', 'Voice Channels', 2, 64000, 15, CURRENT_TIMESTAMP);
		`,
	},
}

// RunMigrations executes pending database migrations within an isolated transaction.
func RunMigrations(db *sql.DB) error {
	// Ensure migration table exists
	_, err := db.Exec(`
		CREATE TABLE IF NOT EXISTS schema_migrations (
			version INTEGER PRIMARY KEY,
			applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
		);
	`)
	if err != nil {
		return fmt.Errorf("failed to create schema_migrations table: %w", err)
	}

	for _, m := range migrations {
		var count int
		err := db.QueryRow("SELECT COUNT(*) FROM schema_migrations WHERE version = ?", m.Version).Scan(&count)
		if err != nil {
			return fmt.Errorf("failed to check migration version %d: %w", m.Version, err)
		}
		if count > 0 {
			continue // Already applied
		}

		tx, err := db.Begin()
		if err != nil {
			return fmt.Errorf("failed to start migration tx for version %d: %w", m.Version, err)
		}

		if _, err := tx.Exec(m.Up); err != nil {
			_ = tx.Rollback()
			return fmt.Errorf("migration %d failed: %w", m.Version, err)
		}

		if _, err := tx.Exec("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", m.Version, time.Now()); err != nil {
			_ = tx.Rollback()
			return fmt.Errorf("failed to record migration %d: %w", m.Version, err)
		}

		if err := tx.Commit(); err != nil {
			return fmt.Errorf("failed to commit migration %d: %w", m.Version, err)
		}
	}
	return nil
}
