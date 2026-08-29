package storage

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"low_latency_voice_app/backend/internal/model"
)

func setupTestDB(t *testing.T) (*SQLiteRepository, func()) {
	t.Helper()
	// Use in-memory database with isolated connection
	db, err := OpenDB(fmt.Sprintf("file:memdb_%d?mode=memory&cache=shared", time.Now().UnixNano()))
	if err != nil {
		t.Fatalf("failed to open test db: %v", err)
	}

	repo := NewSQLiteRepository(db)
	cleanup := func() {
		_ = db.Close()
	}
	return repo, cleanup
}

func TestDB_InitWALAndDefaults(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	// Verify default roles seeded
	adminRole, err := repo.GetRoleByName("Admin")
	if err != nil {
		t.Fatalf("expected Admin role, got err: %v", err)
	}
	if adminRole.Permissions != model.PermAll {
		t.Errorf("expected Admin permissions 0xFFFFFFFF, got %v", adminRole.Permissions)
	}

	memberRole, err := repo.GetDefaultRole()
	if err != nil {
		t.Fatalf("expected default Member role, got err: %v", err)
	}
	if memberRole.Name != "Member" {
		t.Errorf("expected default role Member, got %s", memberRole.Name)
	}

	// Verify default channels seeded
	channels, err := repo.GetChannels()
	if err != nil {
		t.Fatalf("failed to get channels: %v", err)
	}
	if len(channels) < 3 {
		t.Errorf("expected at least 3 default channels, got %d", len(channels))
	}
}

func TestUser_CreateFindAndCaseInsensitive(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	// Create user
	u1, err := repo.CreateUser("Alice", "hashed_secret")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}
	if u1.ID == 0 || u1.Username != "Alice" {
		t.Errorf("unexpected user: %+v", u1)
	}

	// Find by ID
	found, err := repo.GetUserByID(u1.ID)
	if err != nil {
		t.Fatalf("failed to get user by id: %v", err)
	}
	if found.Username != "Alice" {
		t.Errorf("expected username Alice, got %s", found.Username)
	}

	// Find by username case-insensitively
	foundLower, err := repo.GetUserByUsername("alice")
	if err != nil {
		t.Fatalf("failed to get user by lowercase username: %v", err)
	}
	if foundLower.ID != u1.ID {
		t.Errorf("expected id %d, got %d", u1.ID, foundLower.ID)
	}

	// Reject duplicate case-insensitive username
	_, err = repo.CreateUser("ALICE", "another_hash")
	if err != ErrDuplicateUser {
		t.Errorf("expected ErrDuplicateUser, got %v", err)
	}
}

func TestRole_AssignmentAndEffectivePermissions(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	// User 1 (Creator)
	u1, err := repo.CreateUser("Creator", "hash1")
	if err != nil {
		t.Fatalf("failed to create creator: %v", err)
	}

	// Assign Admin role
	adminRole, _ := repo.GetRoleByName("Admin")
	_ = repo.AssignUserRole(u1.ID, adminRole.ID)

	perms1, err := repo.GetEffectivePermissions(u1.ID)
	if err != nil {
		t.Fatalf("failed to get perms for user 1: %v", err)
	}
	if !model.HasPermission(perms1, model.PermAdmin) {
		t.Errorf("expected creator to have Admin permission")
	}

	// Creator cannot have Admin role removed
	err = repo.RemoveUserRole(u1.ID, adminRole.ID)
	if err != ErrImmutableCreator {
		t.Errorf("expected ErrImmutableCreator, got %v", err)
	}

	// User 2 (Standard Member)
	u2, err := repo.CreateUser("Bob", "hash2")
	if err != nil {
		t.Fatalf("failed to create Bob: %v", err)
	}

	perms2, err := repo.GetEffectivePermissions(u2.ID)
	if err != nil {
		t.Fatalf("failed to get perms for user 2: %v", err)
	}
	if model.HasPermission(perms2, model.PermManageChannels) {
		t.Errorf("standard member should not have ManageChannels permission")
	}
	if !model.HasPermission(perms2, model.PermSendMessages) {
		t.Errorf("standard member should have SendMessages permission")
	}
}

func TestChannel_CRUD(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	ch, err := repo.CreateChannel("dev-chat", "text", "Development", 10, 0, 0)
	if err != nil {
		t.Fatalf("failed to create channel: %v", err)
	}
	if ch.Name != "dev-chat" || ch.Type != "text" {
		t.Errorf("unexpected channel: %+v", ch)
	}

	got, err := repo.GetChannelByID(ch.ID)
	if err != nil {
		t.Fatalf("failed to get channel: %v", err)
	}
	if got.Name != "dev-chat" {
		t.Errorf("expected name dev-chat, got %s", got.Name)
	}

	err = repo.DeleteChannel(ch.ID)
	if err != nil {
		t.Fatalf("failed to delete channel: %v", err)
	}

	_, err = repo.GetChannelByID(ch.ID)
	if err != ErrChannelNotFound {
		t.Errorf("expected ErrChannelNotFound, got %v", err)
	}
}

func TestMessages_MonotonicAndCursorPagination(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	u, _ := repo.CreateUser("Messenger", "hash")
	ch, _ := repo.CreateChannel("test-text", "text", "General", 1, 0, 0)

	// Insert 25 messages
	var lastID uint64
	for i := 1; i <= 25; i++ {
		msg, err := repo.CreateMessage(ch.ID, u.ID, fmt.Sprintf("Message %02d", i))
		if err != nil {
			t.Fatalf("failed to insert message %d: %v", i, err)
		}
		if msg.ID <= lastID {
			t.Fatalf("expected monotonic id increase, got %d <= %d", msg.ID, lastID)
		}
		lastID = msg.ID
	}

	// Fetch newest 10 (before_id = 0, limit = 10) -> Should return messages 16..25 in ascending order
	page1, hasMore, err := repo.GetMessages(ch.ID, 0, 10)
	if err != nil {
		t.Fatalf("failed to get page 1: %v", err)
	}
	if len(page1) != 10 {
		t.Fatalf("expected 10 messages, got %d", len(page1))
	}
	if !hasMore {
		t.Errorf("expected hasMore=true")
	}
	if page1[0].Content != "Message 16" || page1[9].Content != "Message 25" {
		t.Errorf("unexpected page 1 contents: first=%s, last=%s", page1[0].Content, page1[9].Content)
	}

	// Fetch next page before page1[0].ID -> Should return messages 6..15
	page2, hasMore, err := repo.GetMessages(ch.ID, page1[0].ID, 10)
	if err != nil {
		t.Fatalf("failed to get page 2: %v", err)
	}
	if len(page2) != 10 {
		t.Fatalf("expected 10 messages, got %d", len(page2))
	}
	if !hasMore {
		t.Errorf("expected hasMore=true")
	}
	if page2[0].Content != "Message 06" || page2[9].Content != "Message 15" {
		t.Errorf("unexpected page 2 contents: first=%s, last=%s", page2[0].Content, page2[9].Content)
	}

	// Fetch last page before page2[0].ID -> Should return messages 1..5 with hasMore=false
	page3, hasMore, err := repo.GetMessages(ch.ID, page2[0].ID, 10)
	if err != nil {
		t.Fatalf("failed to get page 3: %v", err)
	}
	if len(page3) != 5 {
		t.Fatalf("expected 5 messages, got %d", len(page3))
	}
	if hasMore {
		t.Errorf("expected hasMore=false for last page")
	}
	if page3[0].Content != "Message 01" || page3[4].Content != "Message 05" {
		t.Errorf("unexpected page 3 contents: first=%s, last=%s", page3[0].Content, page3[4].Content)
	}
}

func TestVoiceTokens_SingleUseAndExpiry(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	u, _ := repo.CreateUser("VoiceUser", "hash")

	// Valid token with 30s TTL
	vt, err := repo.CreateVoiceToken("token-12345", u.ID, 2, 99999, time.Now().UTC().Add(30*time.Second))
	if err != nil {
		t.Fatalf("failed to create voice token: %v", err)
	}
	if vt.Token != "token-12345" {
		t.Errorf("unexpected token: %+v", vt)
	}

	// First consumption
	consumed, err := repo.ConsumeVoiceToken("token-12345")
	if err != nil {
		t.Fatalf("failed to consume voice token: %v", err)
	}
	if !consumed.IsConsumed {
		t.Errorf("expected token to be marked consumed")
	}

	// Second consumption fails (Replay prevention)
	_, err = repo.ConsumeVoiceToken("token-12345")
	if err != ErrVoiceTokenConsumed {
		t.Errorf("expected ErrVoiceTokenConsumed, got %v", err)
	}

	// Expired token
	_, err = repo.CreateVoiceToken("expired-token", u.ID, 2, 88888, time.Now().UTC().Add(-10*time.Second))
	if err != nil {
		t.Fatalf("failed to create expired token: %v", err)
	}

	_, err = repo.ConsumeVoiceToken("expired-token")
	if err != ErrVoiceTokenExpired {
		t.Errorf("expected ErrVoiceTokenExpired, got %v", err)
	}
}

func TestConcurrent_WAL_Inserts(t *testing.T) {
	repo, cleanup := setupTestDB(t)
	defer cleanup()

	u, _ := repo.CreateUser("ConcurrentUser", "hash")
	ch, _ := repo.CreateChannel("concurrent-text", "text", "General", 1, 0, 0)

	var wg sync.WaitGroup
	numWorkers := 10
	msgsPerWorker := 20

	for w := 0; w < numWorkers; w++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			for i := 0; i < msgsPerWorker; i++ {
				_, err := repo.CreateMessage(ch.ID, u.ID, fmt.Sprintf("Worker %d Msg %d", workerID, i))
				if err != nil {
					t.Errorf("concurrent insert failed: %v", err)
					return
				}
			}
		}(w)
	}

	wg.Wait()

	// Verify total count in DB
	var count int
	err := repo.db.QueryRow("SELECT COUNT(*) FROM messages WHERE channel_id = ?", ch.ID).Scan(&count)
	if err != nil {
		t.Fatalf("failed to count messages: %v", err)
	}
	expected := numWorkers * msgsPerWorker
	if count != expected {
		t.Errorf("expected %d total messages in DB, got %d", expected, count)
	}
}
