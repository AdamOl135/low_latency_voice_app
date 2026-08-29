package auth

import (
	"fmt"
	"testing"
	"time"

	"low_latency_voice_app/backend/internal/model"
	"low_latency_voice_app/backend/internal/storage"
)

func setupTestAuthService(t *testing.T) (*AuthService, *storage.SQLiteRepository, func()) {
	t.Helper()
	db, err := storage.OpenDB(fmt.Sprintf("file:memauth_%d?mode=memory&cache=shared", time.Now().UnixNano()))
	if err != nil {
		t.Fatalf("failed to open test db: %v", err)
	}

	repo := storage.NewSQLiteRepository(db)
	svc := NewAuthService(repo, 7878)
	cleanup := func() {
		_ = db.Close()
	}
	return svc, repo, cleanup
}

func TestPassword_Argon2idHashAndVerify(t *testing.T) {
	password := "SecurePassword123!"
	hash, err := HashPassword(password)
	if err != nil {
		t.Fatalf("failed to hash password: %v", err)
	}

	// Verify correct password
	match, err := VerifyPassword(password, hash)
	if err != nil {
		t.Fatalf("verify error: %v", err)
	}
	if !match {
		t.Errorf("expected password to match")
	}

	// Verify incorrect password
	match, err = VerifyPassword("WrongPassword", hash)
	if err != nil {
		t.Fatalf("verify error: %v", err)
	}
	if match {
		t.Errorf("expected wrong password to fail")
	}
}

func TestAuth_CreatorAdminBootstrapAndSecondUser(t *testing.T) {
	svc, _, cleanup := setupTestAuthService(t)
	defer cleanup()

	// First user -> Admin bootstrap
	res1, err := svc.Register("CreatorAdmin", "Password123!", "1.0.0")
	if err != nil {
		t.Fatalf("failed to register creator: %v", err)
	}
	if res1.UserID != 1 {
		t.Errorf("expected user id 1, got %d", res1.UserID)
	}
	if !res1.IsAdmin {
		t.Errorf("expected creator to be admin")
	}
	if res1.Permissions != uint32(model.PermAll) {
		t.Errorf("expected PermAll, got %d", res1.Permissions)
	}
	if len(res1.Token) != 64 {
		t.Errorf("expected 64-char hex token, got %d chars", len(res1.Token))
	}

	// Second user -> Member
	res2, err := svc.Register("RegularUser", "Password123!", "1.0.0")
	if err != nil {
		t.Fatalf("failed to register member: %v", err)
	}
	if res2.UserID != 2 {
		t.Errorf("expected user id 2, got %d", res2.UserID)
	}
	if res2.IsAdmin {
		t.Errorf("expected regular user to NOT be admin")
	}
	if !model.HasPermission(res2.Permissions, model.PermSendMessages) {
		t.Errorf("expected member to have PermSendMessages")
	}
}

func TestAuth_LoginAndSessionValidation(t *testing.T) {
	svc, _, cleanup := setupTestAuthService(t)
	defer cleanup()

	_, err := svc.Register("alice", "AlicePassword123!", "1.0.0")
	if err != nil {
		t.Fatalf("failed to register alice: %v", err)
	}

	// Valid login
	loginRes, err := svc.Login("alice", "AlicePassword123!", "1.0.0")
	if err != nil {
		t.Fatalf("failed to login: %v", err)
	}
	if loginRes.Username != "alice" || loginRes.Token == "" {
		t.Errorf("unexpected login result: %+v", loginRes)
	}

	// Validate session
	session, err := svc.ValidateSession(loginRes.Token)
	if err != nil {
		t.Fatalf("failed to validate session: %v", err)
	}
	if session.UserID != loginRes.UserID {
		t.Errorf("expected session user id %d, got %d", loginRes.UserID, session.UserID)
	}

	// Invalid password login
	_, err = svc.Login("alice", "WrongPassword", "1.0.0")
	if err != ErrInvalidCredentials {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}

	// Nonexistent user login
	_, err = svc.Login("nonexistent", "SomePassword", "1.0.0")
	if err != ErrInvalidCredentials {
		t.Errorf("expected ErrInvalidCredentials, got %v", err)
	}
}

func TestAuth_InputValidationEdgeCases(t *testing.T) {
	svc, _, cleanup := setupTestAuthService(t)
	defer cleanup()

	// Short username (<3)
	_, err := svc.Register("ab", "Password123!", "1.0.0")
	if err != ErrInvalidUsernameFormat {
		t.Errorf("expected ErrInvalidUsernameFormat, got %v", err)
	}

	// Long username (>32)
	_, err = svc.Register("this_username_is_way_too_long_and_should_be_rejected_by_validator", "Password123!", "1.0.0")
	if err != ErrInvalidUsernameFormat {
		t.Errorf("expected ErrInvalidUsernameFormat, got %v", err)
	}

	// Invalid characters in username
	_, err = svc.Register("alice@domain.com", "Password123!", "1.0.0")
	if err != ErrInvalidUsernameFormat {
		t.Errorf("expected ErrInvalidUsernameFormat, got %v", err)
	}

	// Short password (<8)
	_, err = svc.Register("valid_user", "short", "1.0.0")
	if err != ErrPasswordTooShort {
		t.Errorf("expected ErrPasswordTooShort, got %v", err)
	}
}

func TestAuth_GenerateUDPToken(t *testing.T) {
	svc, _, cleanup := setupTestAuthService(t)
	defer cleanup()

	reg, _ := svc.Register("VoiceUser", "Password123!", "1.0.0")

	vt, err := svc.GenerateUDPToken(reg.UserID, 2)
	if err != nil {
		t.Fatalf("failed to generate UDP token: %v", err)
	}
	if vt.Token == "" || vt.SSRC == 0 || vt.UserID != reg.UserID || vt.ChannelID != 2 {
		t.Errorf("unexpected voice token: %+v", vt)
	}
}
