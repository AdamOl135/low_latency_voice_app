package storage

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"

	_ "modernc.org/sqlite"
)

// OpenDB opens a SQLite database in Write-Ahead Logging (WAL) mode with tuned concurrency pragmas.
func OpenDB(dataSourceName string) (*sql.DB, error) {
	// If path contains directories and is not in-memory, ensure directories exist
	if dataSourceName != ":memory:" && !filepath.IsAbs(dataSourceName) {
		dir := filepath.Dir(dataSourceName)
		if dir != "." && dir != "" {
			if err := os.MkdirAll(dir, 0755); err != nil {
				return nil, fmt.Errorf("failed to create db directory %s: %w", dir, err)
			}
		}
	} else if filepath.IsAbs(dataSourceName) {
		dir := filepath.Dir(dataSourceName)
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create db directory %s: %w", dir, err)
		}
	}

	db, err := sql.Open("sqlite", dataSourceName)
	if err != nil {
		return nil, fmt.Errorf("failed to open sqlite database: %w", err)
	}

	// SQLite connection pooling: Single writer serialization while allowing multiple readers
	if dataSourceName == ":memory:" {
		db.SetMaxOpenConns(1)
	} else {
		db.SetMaxOpenConns(10)
	}

	// Configure PRAGMAs
	pragmas := []string{
		"PRAGMA journal_mode = WAL;",
		"PRAGMA foreign_keys = ON;",
		"PRAGMA synchronous = NORMAL;",
		"PRAGMA busy_timeout = 5000;",
		"PRAGMA cache_size = -64000;",
		"PRAGMA temp_store = MEMORY;",
	}

	for _, p := range pragmas {
		if _, err := db.Exec(p); err != nil {
			_ = db.Close()
			return nil, fmt.Errorf("failed to execute pragma '%s': %w", p, err)
		}
	}

	// Run migrations
	if err := RunMigrations(db); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("failed to run database migrations: %w", err)
	}

	return db, nil
}
