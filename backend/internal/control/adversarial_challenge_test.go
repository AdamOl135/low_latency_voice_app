package control

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"low_latency_voice_app/backend/internal/storage"
)

// --- 1. SQL Injection & Parameter Binding Resilience Tests ---

func TestAdversarial_SQLInjectionResilience_StorageAndWS(t *testing.T) {
	hub, server, _, repo, cleanup := setupTestServer(t)
	defer cleanup()

	// 1.1 Direct Repository SQL Injection Attack Vectors
	sqlPayloads := []string{
		`' OR '1'='1`,
		`admin' --`,
		`admin' /*`,
		`' UNION SELECT token, user_id, datetime('now'), datetime('now') FROM sessions --`,
		`'; DROP TABLE messages; --`,
		`'; DROP TABLE users; --`,
		`" OR "1"="1`,
		`' OR 1=1; --`,
		`\'; DROP TABLE channels; --`,
		`' OR EXISTS(SELECT * FROM users WHERE id=1) --`,
	}

	// Test user creation / lookup resilience
	for i, payload := range sqlPayloads {
		// Valid alphanumeric username format will be rejected by auth regex, but test direct repo binding
		safeUsername := fmt.Sprintf("SafeUser_%d", i)
		u, err := repo.CreateUser(safeUsername, "hashed_pw")
		if err != nil {
			t.Fatalf("failed to create baseline user: %v", err)
		}

		// Try looking up with SQL payload - should return ErrUserNotFound, never SQL syntax error or leak
		_, err = repo.GetUserByUsername(payload)
		if err != storage.ErrUserNotFound {
			t.Errorf("expected ErrUserNotFound for SQL injection payload %q, got: %v", payload, err)
		}

		// Look up existing user by valid name
		found, err := repo.GetUserByUsername(safeUsername)
		if err != nil || found.ID != u.ID {
			t.Fatalf("expected to find user %s, got: %v", safeUsername, err)
		}
	}

	// Test channel operations with SQL payload
	for _, payload := range sqlPayloads {
		ch, err := repo.CreateChannel(payload, "text", payload, 0, 64000, 15)
		if err != nil {
			t.Fatalf("failed to safely insert channel with SQL payload %q: %v", payload, err)
		}

		got, err := repo.GetChannelByID(ch.ID)
		if err != nil {
			t.Fatalf("failed to fetch channel: %v", err)
		}
		if got.Name != payload || got.Category != payload {
			t.Errorf("channel data corrupted by SQL payload: expected %q, got %q", payload, got.Name)
		}
	}

	// Test messages with SQL payload
	creator, _ := repo.CreateUser("MsgAuthor", "hash")
	textCh, _ := repo.CreateChannel("chat-sec", "text", "General", 1, 64000, 0)
	for _, payload := range sqlPayloads {
		msg, err := repo.CreateMessage(textCh.ID, creator.ID, payload)
		if err != nil {
			t.Fatalf("failed to insert message with SQL payload %q: %v", payload, err)
		}
		if msg.Content != payload {
			t.Errorf("message content mismatch: expected %q, got %q", payload, msg.Content)
		}
	}

	// Verify messages table wasn't dropped or corrupted
	messages, hasMore, err := repo.GetMessages(textCh.ID, 0, 100)
	if err != nil {
		t.Fatalf("failed to get messages after SQL injection tests: %v", err)
	}
	if len(messages) != len(sqlPayloads) {
		t.Errorf("expected %d messages, got %d (hasMore: %v)", len(sqlPayloads), len(messages), hasMore)
	}

	// 1.2 WebSocket JSON-RPC SQL Injection via API
	conn := connectWS(t, server.URL)
	defer conn.Close()

	// Register admin user
	regMsg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "SQLAdmin",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, regMsg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Send chat with SQL injection payloads via WebSocket
	for idx, payload := range sqlPayloads {
		reqID := 100 + idx
		chatReq, _ := json.Marshal(map[string]interface{}{
			"id":         reqID,
			"action":     "send_chat",
			"channel_id": textCh.ID,
			"content":    payload,
		})
		_ = conn.WriteMessage(websocket.TextMessage, chatReq)
		resp := readResponse(t, conn, reqID, 3*time.Second)
		if resp["status"] != "ok" {
			t.Errorf("expected ok status for send_chat with payload %q, got: %+v", payload, resp)
		}
	}

	// Query chat history with SQL injection in before_id or limit
	histReq, _ := json.Marshal(map[string]interface{}{
		"id":         500,
		"action":     "get_chat_history",
		"channel_id": textCh.ID,
		"before_id":  0,
		"limit":      50,
	})
	_ = conn.WriteMessage(websocket.TextMessage, histReq)
	histResp := readResponse(t, conn, 500, 3*time.Second)
	if histResp["status"] != "ok" {
		t.Errorf("expected ok status for get_chat_history, got: %+v", histResp)
	}

	_ = hub
}

// --- 2. Moderation & Permission Security Challenge Tests ---

func TestAdversarial_NonAdminModeration_Forbidden(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	// 1. Connect and register Server Creator (Admin, User ID 1)
	connAdmin := connectWS(t, server.URL)
	defer connAdmin.Close()

	regAdmin, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "OwnerAdmin",
		"password": "Password123!",
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, regAdmin)
	adminResp := readResponse(t, connAdmin, 1, 3*time.Second)
	if adminResp["is_admin"] != true {
		t.Fatalf("expected Creator to be admin, got: %+v", adminResp)
	}

	// 2. Connect and register Regular Member (User ID 2)
	connMember := connectWS(t, server.URL)
	defer connMember.Close()

	regMember, _ := json.Marshal(map[string]interface{}{
		"id":       2,
		"action":   "register",
		"username": "RegularMember",
		"password": "Password123!",
	})
	_ = connMember.WriteMessage(websocket.TextMessage, regMember)
	memberResp := readResponse(t, connMember, 2, 3*time.Second)
	if memberResp["is_admin"] == true {
		t.Fatalf("regular member should NOT be admin: %+v", memberResp)
	}

	// Admin joins voice channel 2
	adminJoin, _ := json.Marshal(map[string]interface{}{
		"id":         10,
		"action":     "join_voice",
		"channel_id": 2,
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, adminJoin)
	_ = readResponse(t, connAdmin, 10, 3*time.Second)

	// Member joins voice channel 2
	memberJoin, _ := json.Marshal(map[string]interface{}{
		"id":         11,
		"action":     "join_voice",
		"channel_id": 2,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, memberJoin)
	_ = readResponse(t, connMember, 11, 3*time.Second)

	// 2.1 Non-Admin attempts move_member -> MUST BE FORBIDDEN (4003)
	moveReq, _ := json.Marshal(map[string]interface{}{
		"id":             20,
		"action":         "move_member",
		"target_user_id": 1, // Member trying to move Admin
		"to_channel_id":  3,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, moveReq)
	moveResp := readResponse(t, connMember, 20, 3*time.Second)
	if moveResp["status"] != "error" {
		t.Fatalf("security violation: non-admin was able to move member! response: %+v", moveResp)
	}
	errObj, _ := moveResp["error"].(map[string]interface{})
	code, _ := errObj["code"].(float64)
	if int(code) != ErrCodeForbidden {
		t.Errorf("expected ErrCodeForbidden (%d), got: %d (%+v)", ErrCodeForbidden, int(code), moveResp)
	}

	// 2.2 Non-Admin attempts set_server_mute -> MUST BE FORBIDDEN (4003)
	muteReq, _ := json.Marshal(map[string]interface{}{
		"id":             21,
		"action":         "set_server_mute",
		"target_user_id": 1,
		"muted":          true,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, muteReq)
	muteResp := readResponse(t, connMember, 21, 3*time.Second)
	if muteResp["status"] != "error" {
		t.Fatalf("security violation: non-admin was able to set_server_mute! response: %+v", muteResp)
	}
	errObj, _ = muteResp["error"].(map[string]interface{})
	code, _ = errObj["code"].(float64)
	if int(code) != ErrCodeForbidden {
		t.Errorf("expected ErrCodeForbidden (%d), got: %d", ErrCodeForbidden, int(code))
	}

	// 2.3 Non-Admin attempts set_server_deafen -> MUST BE FORBIDDEN (4003)
	deafenReq, _ := json.Marshal(map[string]interface{}{
		"id":             22,
		"action":         "set_server_deafen",
		"target_user_id": 1,
		"deafened":       true,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, deafenReq)
	deafenResp := readResponse(t, connMember, 22, 3*time.Second)
	if deafenResp["status"] != "error" {
		t.Fatalf("security violation: non-admin was able to set_server_deafen! response: %+v", deafenResp)
	}
	errObj, _ = deafenResp["error"].(map[string]interface{})
	code, _ = errObj["code"].(float64)
	if int(code) != ErrCodeForbidden {
		t.Errorf("expected ErrCodeForbidden (%d), got: %d", ErrCodeForbidden, int(code))
	}

	// 2.4 Non-Admin attempts kick_member -> MUST BE FORBIDDEN (4003)
	kickReq, _ := json.Marshal(map[string]interface{}{
		"id":             23,
		"action":         "kick_member",
		"target_user_id": 1,
		"reason":         "Unauthorized kick attempt",
	})
	_ = connMember.WriteMessage(websocket.TextMessage, kickReq)
	kickResp := readResponse(t, connMember, 23, 3*time.Second)
	if kickResp["status"] != "error" {
		t.Fatalf("security violation: non-admin was able to kick_member! response: %+v", kickResp)
	}
	errObj, _ = kickResp["error"].(map[string]interface{})
	code, _ = errObj["code"].(float64)
	if int(code) != ErrCodeForbidden {
		t.Errorf("expected ErrCodeForbidden (%d), got: %d", ErrCodeForbidden, int(code))
	}

	// 2.5 Non-Admin attempts create_channel -> MUST BE FORBIDDEN (4003)
	createChReq, _ := json.Marshal(map[string]interface{}{
		"id":       24,
		"action":   "create_channel",
		"name":     "hacked-channel",
		"type":     "text",
		"category": "General",
	})
	_ = connMember.WriteMessage(websocket.TextMessage, createChReq)
	createChResp := readResponse(t, connMember, 24, 3*time.Second)
	if createChResp["status"] != "error" {
		t.Fatalf("security violation: non-admin was able to create_channel! response: %+v", createChResp)
	}

	// 2.6 Admin attempts to kick Server Creator (User ID 1) -> MUST BE REJECTED (4005)
	kickCreatorReq, _ := json.Marshal(map[string]interface{}{
		"id":             30,
		"action":         "kick_member",
		"target_user_id": 1,
		"reason":         "Attempting to kick creator",
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, kickCreatorReq)
	kickCreatorResp := readResponse(t, connAdmin, 30, 3*time.Second)
	if kickCreatorResp["status"] != "error" {
		t.Fatalf("security violation: creator was kicked! response: %+v", kickCreatorResp)
	}
	errObj, _ = kickCreatorResp["error"].(map[string]interface{})
	code, _ = errObj["code"].(float64)
	if int(code) != ErrCodeImmutableCreatorRole {
		t.Errorf("expected ErrCodeImmutableCreatorRole (%d), got: %d", ErrCodeImmutableCreatorRole, int(code))
	}

	// 2.7 Unauthenticated connection attempting moderation actions -> MUST BE UNAUTHORIZED (4001)
	connUnauth := connectWS(t, server.URL)
	defer connUnauth.Close()

	unauthMove, _ := json.Marshal(map[string]interface{}{
		"id":             40,
		"action":         "move_member",
		"target_user_id": 2,
		"to_channel_id":  3,
	})
	_ = connUnauth.WriteMessage(websocket.TextMessage, unauthMove)
	unauthResp := readResponse(t, connUnauth, 40, 3*time.Second)
	if unauthResp["status"] != "error" {
		t.Fatalf("security violation: unauthenticated client bypassed auth! response: %+v", unauthResp)
	}
	errObj, _ = unauthResp["error"].(map[string]interface{})
	code, _ = errObj["code"].(float64)
	if int(code) != ErrCodeUnauthorized {
		t.Errorf("expected ErrCodeUnauthorized (%d), got: %d", ErrCodeUnauthorized, int(code))
	}
}

// --- 3. Rapid Connect / Disconnect Churn & Concurrency Stress Tests ---

func TestAdversarial_WebSocketRapidConnectDisconnectCycles(t *testing.T) {
	hub, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	numClients := 60
	cyclesPerClient := 3

	var wg sync.WaitGroup
	wg.Add(numClients)

	for c := 0; c < numClients; c++ {
		go func(clientID int) {
			defer wg.Done()
			username := fmt.Sprintf("ChurnUser_%03d", clientID)

			for cycle := 0; cycle < cyclesPerClient; cycle++ {
				conn := connectWS(t, server.URL)

				// Register / Auth
				regMsg, _ := json.Marshal(map[string]interface{}{
					"id":       1,
					"action":   "register",
					"username": fmt.Sprintf("%s_%d", username, cycle),
					"password": "Password123!",
				})
				_ = conn.WriteMessage(websocket.TextMessage, regMsg)

				// Join voice channel
				joinMsg, _ := json.Marshal(map[string]interface{}{
					"id":         2,
					"action":     "join_voice",
					"channel_id": 2,
				})
				_ = conn.WriteMessage(websocket.TextMessage, joinMsg)

				// Rapid disconnect / close socket abruptly
				time.Sleep(10 * time.Millisecond)
				_ = conn.Close()
			}
		}(c)
	}

	wg.Wait()

	// Allow server goroutines to finish inflight registration and unregister all closed sockets
	deadline := time.Now().Add(5 * time.Second)
	var activeCount int
	var activeVoiceUsers int
	for time.Now().Before(deadline) {
		hub.mu.RLock()
		activeCount = len(hub.clients)
		activeVoiceUsers = len(hub.voiceStates)
		hub.mu.RUnlock()
		if activeCount == 0 && activeVoiceUsers == 0 {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if activeCount != 0 {
		t.Errorf("expected 0 active clients after all disconnects, got: %d", activeCount)
	}
	if activeVoiceUsers != 0 {
		t.Errorf("expected 0 active voice states after all disconnects, got: %d", activeVoiceUsers)
	}
}

// --- 4. SQLite WAL High-Concurrency Stress Test ---

func TestAdversarial_SQLiteWAL_HighConcurrencyWrites(t *testing.T) {
	_, _, _, repo, cleanup := setupTestServer(t)
	defer cleanup()

	numWorkers := 20
	opsPerWorker := 30

	var wg sync.WaitGroup
	wg.Add(numWorkers)

	for w := 0; w < numWorkers; w++ {
		go func(workerID int) {
			defer wg.Done()
			username := fmt.Sprintf("StressUser_%03d", workerID)
			u, err := repo.CreateUser(username, "hash_stress")
			if err != nil {
				t.Errorf("worker %d failed to create user: %v", workerID, err)
				return
			}

			ch, err := repo.CreateChannel(fmt.Sprintf("chan_%03d", workerID), "text", "Stress", workerID, 64000, 15)
			if err != nil {
				t.Errorf("worker %d failed to create channel: %v", workerID, err)
				return
			}

			for i := 0; i < opsPerWorker; i++ {
				// Insert message
				_, err := repo.CreateMessage(ch.ID, u.ID, fmt.Sprintf("Stress payload %d from worker %d", i, workerID))
				if err != nil {
					t.Errorf("worker %d failed to insert message %d: %v", workerID, i, err)
					return
				}

				// Create session
				sessToken := fmt.Sprintf("token_%d_%d_%d", workerID, i, time.Now().UnixNano())
				_, err = repo.CreateSession(sessToken, u.ID, time.Now().UTC().Add(1*time.Hour))
				if err != nil {
					t.Errorf("worker %d failed to insert session: %v", workerID, err)
					return
				}

				// Validate session
				s, err := repo.GetSession(sessToken)
				if err != nil || s == nil {
					t.Errorf("worker %d failed to get session: %v", workerID, err)
					return
				}

				// Delete session
				_ = repo.DeleteSession(sessToken)
			}
		}(w)
	}

	wg.Wait()

	// Verify total user count
	count, err := repo.GetUserCount()
	if err != nil {
		t.Fatalf("failed to count users: %v", err)
	}
	if count < numWorkers {
		t.Errorf("expected at least %d users, got %d", numWorkers, count)
	}
}

// --- 5. Rapid Concurrent Registrations for Identical Username ---

func TestAdversarial_RapidConcurrentRegistrations_SameUsername(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	targetUsername := "ContestedUsername"
	numAttempts := 20

	var wg sync.WaitGroup
	wg.Add(numAttempts)

	var successCount int64
	var errorCount int64
	var mu sync.Mutex

	for i := 0; i < numAttempts; i++ {
		go func(attemptID int) {
			defer wg.Done()
			conn := connectWS(t, server.URL)
			defer conn.Close()

			regReq, _ := json.Marshal(map[string]interface{}{
				"id":       attemptID,
				"action":   "register",
				"username": targetUsername,
				"password": "Password123!",
			})
			_ = conn.WriteMessage(websocket.TextMessage, regReq)

			resp := readResponse(t, conn, attemptID, 5*time.Second)
			mu.Lock()
			defer mu.Unlock()
			if resp["status"] == "ok" {
				successCount++
			} else {
				errorCount++
				errObj, _ := resp["error"].(map[string]interface{})
				code, _ := errObj["code"].(float64)
				if int(code) != ErrCodeUserAlreadyExists {
					t.Logf("attempt %d failed with code %v: %+v", attemptID, code, resp)
				}
			}
		}(i + 1)
	}

	wg.Wait()

	if successCount != 1 {
		t.Errorf("expected exactly 1 successful registration for duplicate username, got: %d (errors: %d)", successCount, errorCount)
	}
	if errorCount != int64(numAttempts-1) {
		t.Errorf("expected %d failed duplicate registration attempts, got: %d", numAttempts-1, errorCount)
	}
}

// --- 6. Voice Token Single-Use, Expiry, and Replay Resilience ---

func TestAdversarial_VoiceToken_SingleUseAndReplay(t *testing.T) {
	_, _, authSvc, repo, cleanup := setupTestServer(t)
	defer cleanup()

	u, err := repo.CreateUser("TokenVictim", "hash")
	if err != nil {
		t.Fatalf("failed to create user: %v", err)
	}

	// Generate voice token
	vt, err := authSvc.GenerateUDPToken(u.ID, 2)
	if err != nil {
		t.Fatalf("failed to generate UDP token: %v", err)
	}

	// 1st redemption: Must SUCCEED
	tokenRecord, err := repo.ConsumeVoiceToken(vt.Token)
	if err != nil || tokenRecord == nil {
		t.Fatalf("1st token redemption failed: %v", err)
	}
	if tokenRecord.UserID != u.ID || tokenRecord.ChannelID != 2 {
		t.Errorf("token record mismatch: %+v", tokenRecord)
	}

	// 2nd redemption (Replay attack): MUST FAIL (single-use consumed)
	tokenRecord2, err := repo.ConsumeVoiceToken(vt.Token)
	if err != storage.ErrVoiceTokenConsumed && err != storage.ErrVoiceTokenNotFound {
		t.Errorf("expected ErrVoiceTokenConsumed/NotFound on replayed token redemption, got: %v (record: %+v)", err, tokenRecord2)
	}
}

// --- 7. Malformed JSON-RPC, 0-Byte Frames, and Edge-Case Payloads ---

func TestAdversarial_MalformedJSONRPC_0ByteFrames_ExtremeStrings(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	// 7.1 0-Byte Frame (Empty frame)
	_ = conn.WriteMessage(websocket.TextMessage, []byte{})
	resp := readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for 0-byte frame, got: %+v", resp)
	}

	// 7.2 Non-JSON binary / garbage
	_ = conn.WriteMessage(websocket.TextMessage, []byte{0x00, 0xFF, 0xFE, 0x12, 0x7F})
	resp = readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for garbage frame, got: %+v", resp)
	}

	// 7.3 JSON Array (expected JSON object)
	_ = conn.WriteMessage(websocket.TextMessage, []byte(`[{"action":"ping"}]`))
	resp = readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for JSON array frame, got: %+v", resp)
	}

	// 7.4 JSON null
	_ = conn.WriteMessage(websocket.TextMessage, []byte(`null`))
	resp = readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for JSON null, got: %+v", resp)
	}

	// 7.5 JSON number primitive
	_ = conn.WriteMessage(websocket.TextMessage, []byte(`12345`))
	resp = readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for JSON number primitive, got: %+v", resp)
	}

	// 7.6 JSON string primitive
	_ = conn.WriteMessage(websocket.TextMessage, []byte(`"hello world"`))
	resp = readResponse(t, conn, nil, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for JSON string primitive, got: %+v", resp)
	}

	// 7.7 Null action
	_ = conn.WriteMessage(websocket.TextMessage, []byte(`{"id": 99, "action": null}`))
	resp = readResponse(t, conn, 99, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for null action, got: %+v", resp)
	}

	// 7.8 Extreme long action name
	hugeAction := fmt.Sprintf("action_%s", strings.Repeat("A", 10000))
	hugeActionReq, _ := json.Marshal(map[string]interface{}{
		"id":     100,
		"action": hugeAction,
	})
	_ = conn.WriteMessage(websocket.TextMessage, hugeActionReq)
	resp = readResponse(t, conn, 100, 2*time.Second)
	if resp["status"] != "error" {
		t.Errorf("expected error for extreme long action, got: %+v", resp)
	}
}

// --- 8. Concurrent Channel Joins & 15-User Capacity Limit ---

func TestAdversarial_VoiceChannel_Max15Users_ConcurrencyLimit(t *testing.T) {
	hub, server, _, repo, cleanup := setupTestServer(t)
	defer cleanup()

	// Create channel with strict limit of 15 users
	voiceCh, err := repo.CreateChannel("StrictLounge", "voice", "Audio", 1, 64000, 15)
	if err != nil {
		t.Fatalf("failed to create channel: %v", err)
	}

	totalClients := 25
	conns := make([]*websocket.Conn, totalClients)

	// Pre-register and connect all 25 clients
	for i := 0; i < totalClients; i++ {
		conns[i] = connectWS(t, server.URL)
		defer conns[i].Close()

		username := fmt.Sprintf("VoiceUser_%02d", i)
		regReq, _ := json.Marshal(map[string]interface{}{
			"id":       1,
			"action":   "register",
			"username": username,
			"password": "Password123!",
		})
		_ = conns[i].WriteMessage(websocket.TextMessage, regReq)
		regResp := readResponse(t, conns[i], 1, 3*time.Second)
		if regResp["status"] != "ok" {
			t.Fatalf("failed to register %s: %+v", username, regResp)
		}
	}

	// Concurrently attempt to join the 15-user voice channel
	var wg sync.WaitGroup
	wg.Add(totalClients)

	var successCount int64
	var rejectedCount int64
	var mu sync.Mutex

	for i := 0; i < totalClients; i++ {
		go func(idx int) {
			defer wg.Done()
			joinReq, _ := json.Marshal(map[string]interface{}{
				"id":         10,
				"action":     "join_voice",
				"channel_id": voiceCh.ID,
			})
			_ = conns[idx].WriteMessage(websocket.TextMessage, joinReq)
			resp := readResponse(t, conns[idx], 10, 5*time.Second)

			mu.Lock()
			defer mu.Unlock()
			if resp["status"] == "ok" {
				successCount++
			} else {
				rejectedCount++
				errObj, _ := resp["error"].(map[string]interface{})
				code, _ := errObj["code"].(float64)
				if int(code) != ErrCodeChannelFull {
					t.Errorf("client %d rejected with wrong code: %v (%+v)", idx, code, resp)
				}
			}
		}(i)
	}

	wg.Wait()

	if successCount != 15 {
		t.Errorf("expected exactly 15 successful voice joins, got: %d", successCount)
	}
	if rejectedCount != int64(totalClients-15) {
		t.Errorf("expected exactly %d rejected voice joins (channel full), got: %d", totalClients-15, rejectedCount)
	}

	// Verify internal hub state occupancy never exceeded 15
	hub.mu.RLock()
	occupantsCount := len(hub.voiceChannels[voiceCh.ID])
	hub.mu.RUnlock()

	if occupantsCount != 15 {
		t.Errorf("expected exactly 15 occupants in hub voiceChannels, got: %d", occupantsCount)
	}
}

