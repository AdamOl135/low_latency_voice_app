package control

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"low_latency_voice_app/backend/internal/auth"
	"low_latency_voice_app/backend/internal/storage"
)

func setupTestServer(t *testing.T) (*Hub, *httptest.Server, *auth.AuthService, *storage.SQLiteRepository, func()) {
	t.Helper()
	db, err := storage.OpenDB(fmt.Sprintf("file:memctrl_%d?mode=memory&cache=shared", time.Now().UnixNano()))
	if err != nil {
		t.Fatalf("failed to open test db: %v", err)
	}

	repo := storage.NewSQLiteRepository(db)
	authSvc := auth.NewAuthService(repo, 7878)
	hub := NewHub(repo, authSvc)
	go hub.Run()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ServeWs(hub, w, r)
	}))

	cleanup := func() {
		hub.Close()
		server.Close()
		_ = db.Close()
	}

	return hub, server, authSvc, repo, cleanup
}

func connectWS(t *testing.T, serverURL string) *websocket.Conn {
	t.Helper()
	wsURL := "ws" + strings.TrimPrefix(serverURL, "http")
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial error: %v", err)
	}
	return conn
}

func matchID(actual, expected interface{}) bool {
	if actual == nil && expected == nil {
		return true
	}
	if actual == nil || expected == nil {
		return false
	}
	var a, e string
	switch v := actual.(type) {
	case float64:
		a = fmt.Sprintf("%.0f", v)
	default:
		a = fmt.Sprintf("%v", v)
	}
	switch v := expected.(type) {
	case float64:
		e = fmt.Sprintf("%.0f", v)
	default:
		e = fmt.Sprintf("%v", v)
	}
	return a == e
}

func readResponse(t *testing.T, conn *websocket.Conn, expectedID interface{}, timeout time.Duration) map[string]interface{} {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		_ = conn.SetReadDeadline(deadline)
		_, msg, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("error reading response message: %v", err)
		}
		var res map[string]interface{}
		if err := json.Unmarshal(msg, &res); err != nil {
			continue
		}
		// Skip broadcast events without matching ID
		if _, isEvent := res["event"]; isEvent && res["id"] == nil {
			continue
		}
		if expectedID != nil {
			if matchID(res["id"], expectedID) {
				return res
			}
			continue
		}
		return res
	}
	t.Fatalf("timed out waiting for response with id %v", expectedID)
	return nil
}

func readEvent(t *testing.T, conn *websocket.Conn, eventName string, timeout time.Duration) map[string]interface{} {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		_ = conn.SetReadDeadline(deadline)
		_, msg, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("error reading event message: %v", err)
		}
		var res map[string]interface{}
		if err := json.Unmarshal(msg, &res); err != nil {
			continue
		}
		if ev, ok := res["event"].(string); ok && ev == eventName {
			return res
		}
	}
	t.Fatalf("timed out waiting for event %s", eventName)
	return nil
}

func TestWS_MalformedJSONAndUnknownAction(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	// 1. Malformed JSON
	_ = conn.WriteMessage(websocket.TextMessage, []byte("{invalid json"))
	resp := readResponse(t, conn, nil, 2*time.Second)

	errMap, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error object in response: %+v", resp)
	}
	code, _ := errMap["code"].(float64)
	if int(code) != ErrCodeParseError {
		t.Errorf("expected ParseError (%d), got %d", ErrCodeParseError, int(code))
	}

	// 2. Unknown action
	req := map[string]interface{}{
		"id":     101,
		"action": "nonexistent_action",
	}
	bytes, _ := json.Marshal(req)
	_ = conn.WriteMessage(websocket.TextMessage, bytes)

	resp = readResponse(t, conn, 101, 2*time.Second)
	errMap, _ = resp["error"].(map[string]interface{})
	code, _ = errMap["code"].(float64)
	if int(code) != ErrCodeUnauthorized && int(code) != ErrCodeMethodNotFound {
		t.Errorf("unexpected error code: %d", int(code))
	}
}

func TestWS_AuthFlowAndPresenceSync(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn1 := connectWS(t, server.URL)
	defer conn1.Close()

	// 1. Unauthenticated request rejected
	chatReq := map[string]interface{}{
		"id":         1,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    "Hello",
	}
	chatBytes, _ := json.Marshal(chatReq)
	_ = conn1.WriteMessage(websocket.TextMessage, chatBytes)

	resp := readResponse(t, conn1, 1, 2*time.Second)
	errMap, _ := resp["error"].(map[string]interface{})
	code, _ := errMap["code"].(float64)
	if int(code) != ErrCodeUnauthorized {
		t.Errorf("expected Unauthorized (%d), got %d", ErrCodeUnauthorized, int(code))
	}

	// 2. Register first user (Creator Admin)
	regReq := map[string]interface{}{
		"id":       2,
		"action":   "register",
		"username": "AdminUser",
		"password": "Password123!",
	}
	regBytes, _ := json.Marshal(regReq)
	_ = conn1.WriteMessage(websocket.TextMessage, regBytes)

	regResp := readResponse(t, conn1, 2, 3*time.Second)
	if regResp["status"] != "ok" {
		t.Fatalf("expected ok registration for AdminUser, got: %+v", regResp)
	}
	token, ok := regResp["token"].(string)
	if !ok || token == "" {
		t.Fatalf("missing token in register response: %+v", regResp)
	}

	// 3. Connect second client and authenticate with new registration
	conn2 := connectWS(t, server.URL)
	defer conn2.Close()

	reg2Req := map[string]interface{}{
		"id":       3,
		"action":   "register",
		"username": "BobMember",
		"password": "Password123!",
	}
	reg2Bytes, _ := json.Marshal(reg2Req)
	_ = conn2.WriteMessage(websocket.TextMessage, reg2Bytes)

	reg2Resp := readResponse(t, conn2, 3, 3*time.Second)
	if reg2Resp["status"] != "ok" {
		t.Fatalf("expected ok registration for BobMember, got: %+v", reg2Resp)
	}
}

func TestWS_ChatSendAndBroadcast(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	// Client 1 (Alice)
	conn1 := connectWS(t, server.URL)
	defer conn1.Close()

	reg1, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "AliceChatter",
		"password": "Password123!",
	})
	_ = conn1.WriteMessage(websocket.TextMessage, reg1)
	_ = readResponse(t, conn1, 1, 3*time.Second)

	// Client 2 (Bob)
	conn2 := connectWS(t, server.URL)
	defer conn2.Close()

	reg2, _ := json.Marshal(map[string]interface{}{
		"id":       2,
		"action":   "register",
		"username": "BobReceiver",
		"password": "Password123!",
	})
	_ = conn2.WriteMessage(websocket.TextMessage, reg2)
	_ = readResponse(t, conn2, 2, 3*time.Second)

	// Alice sends chat message
	chatMsg, _ := json.Marshal(map[string]interface{}{
		"id":         10,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    "Hello from Alice!",
	})
	_ = conn1.WriteMessage(websocket.TextMessage, chatMsg)

	// Alice gets success response
	sendResp := readResponse(t, conn1, 10, 3*time.Second)
	if sendResp["status"] != "ok" {
		t.Errorf("expected ok status for send_chat, got: %+v", sendResp)
	}

	// Bob receives chat_message event
	chatEvent := readEvent(t, conn2, "chat_message", 3*time.Second)
	if chatEvent["event"] != "chat_message" {
		t.Errorf("expected chat_message event, got: %+v", chatEvent)
	}
}

func TestWS_VoiceJoinAndLeave(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "VoiceTester",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Join voice channel 2 ("lounge")
	joinReq, _ := json.Marshal(map[string]interface{}{
		"id":         10,
		"action":     "join_voice",
		"channel_id": 2,
		"self_muted": false,
	})
	_ = conn.WriteMessage(websocket.TextMessage, joinReq)

	joinResp := readResponse(t, conn, 10, 3*time.Second)
	if joinResp["status"] != "ok" {
		t.Fatalf("expected ok join_voice, got: %+v", joinResp)
	}
	if joinResp["udp_token"] == "" || joinResp["udp_port"] == nil {
		t.Errorf("missing UDP token or port: %+v", joinResp)
	}

	// Leave voice
	leaveReq, _ := json.Marshal(map[string]interface{}{
		"id":         11,
		"action":     "leave_voice",
		"channel_id": 2,
	})
	_ = conn.WriteMessage(websocket.TextMessage, leaveReq)

	leaveResp := readResponse(t, conn, 11, 3*time.Second)
	if leaveResp["status"] != "ok" {
		t.Errorf("expected ok leave_voice, got: %+v", leaveResp)
	}
}

func TestWS_GetChannelsAndRoster(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "Inspector",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Get Channels
	chReq, _ := json.Marshal(map[string]interface{}{
		"id":     2,
		"action": "get_channels",
	})
	_ = conn.WriteMessage(websocket.TextMessage, chReq)

	chResp := readResponse(t, conn, 2, 3*time.Second)
	if chResp["status"] != "ok" {
		t.Errorf("expected ok get_channels, got: %+v", chResp)
	}

	// Get Roster
	rosterReq, _ := json.Marshal(map[string]interface{}{
		"id":     3,
		"action": "get_roster",
	})
	_ = conn.WriteMessage(websocket.TextMessage, rosterReq)

	rosterResp := readResponse(t, conn, 3, 3*time.Second)
	if rosterResp["status"] != "ok" {
		t.Errorf("expected ok get_roster, got: %+v", rosterResp)
	}
}

func TestWS_ChannelCreationAndDeletion(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	// Register Creator Admin
	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "ChannelAdmin",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Create Channel
	createReq, _ := json.Marshal(map[string]interface{}{
		"id":         2,
		"action":     "create_channel",
		"name":       "announcements",
		"type":       "text",
		"category":   "Information",
		"position":   1,
	})
	_ = conn.WriteMessage(websocket.TextMessage, createReq)

	createResp := readResponse(t, conn, 2, 3*time.Second)
	if createResp["status"] != "ok" {
		t.Fatalf("expected ok create_channel, got: %+v", createResp)
	}

	chObj, _ := createResp["channel"].(map[string]interface{})
	chID := chObj["id"]

	// Delete Channel
	delReq, _ := json.Marshal(map[string]interface{}{
		"id":         3,
		"action":     "delete_channel",
		"channel_id": chID,
	})
	_ = conn.WriteMessage(websocket.TextMessage, delReq)

	delResp := readResponse(t, conn, 3, 3*time.Second)
	if delResp["status"] != "ok" {
		t.Errorf("expected ok delete_channel, got: %+v", delResp)
	}
}

func TestWS_ModerationActions(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	// Admin connection
	connAdmin := connectWS(t, server.URL)
	defer connAdmin.Close()

	regAdmin, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "SuperAdmin",
		"password": "Password123!",
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, regAdmin)
	_ = readResponse(t, connAdmin, 1, 3*time.Second)

	// Member connection
	connMember := connectWS(t, server.URL)
	defer connMember.Close()

	regMember, _ := json.Marshal(map[string]interface{}{
		"id":       2,
		"action":   "register",
		"username": "BadMember",
		"password": "Password123!",
	})
	_ = connMember.WriteMessage(websocket.TextMessage, regMember)
	_ = readResponse(t, connMember, 2, 3*time.Second)

	// Member joins voice channel 2
	joinReq, _ := json.Marshal(map[string]interface{}{
		"id":         10,
		"action":     "join_voice",
		"channel_id": 2,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, joinReq)
	_ = readResponse(t, connMember, 10, 3*time.Second)

	// 1. Admin moves member to voice channel 3
	moveReq, _ := json.Marshal(map[string]interface{}{
		"id":             20,
		"action":         "move_member",
		"target_user_id": 2,
		"to_channel_id":  3,
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, moveReq)
	moveResp := readResponse(t, connAdmin, 20, 3*time.Second)
	if moveResp["status"] != "ok" {
		t.Errorf("expected ok move_member, got: %+v", moveResp)
	}

	// 2. Admin server-mutes member
	muteReq, _ := json.Marshal(map[string]interface{}{
		"id":             21,
		"action":         "set_server_mute",
		"target_user_id": 2,
		"muted":          true,
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, muteReq)
	muteResp := readResponse(t, connAdmin, 21, 3*time.Second)
	if muteResp["status"] != "ok" {
		t.Errorf("expected ok set_server_mute, got: %+v", muteResp)
	}

	// 3. Admin server-deafens member
	deafenReq, _ := json.Marshal(map[string]interface{}{
		"id":             22,
		"action":         "set_server_deafen",
		"target_user_id": 2,
		"deafened":       true,
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, deafenReq)
	deafenResp := readResponse(t, connAdmin, 22, 3*time.Second)
	if deafenResp["status"] != "ok" {
		t.Errorf("expected ok set_server_deafen, got: %+v", deafenResp)
	}

	// 4. Non-admin member attempts moderation action (should fail with permission error)
	unauthMoveReq, _ := json.Marshal(map[string]interface{}{
		"id":             30,
		"action":         "move_member",
		"target_user_id": 1,
		"to_channel_id":  2,
	})
	_ = connMember.WriteMessage(websocket.TextMessage, unauthMoveReq)
	unauthResp := readResponse(t, connMember, 30, 3*time.Second)
	if unauthResp["status"] != "error" {
		t.Errorf("expected error for unauthorized move_member, got: %+v", unauthResp)
	}

	// 5. Admin cannot kick server creator (user ID 1)
	kickCreatorReq, _ := json.Marshal(map[string]interface{}{
		"id":             31,
		"action":         "kick_member",
		"target_user_id": 1,
		"reason":         "Attempt to kick creator",
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, kickCreatorReq)
	kickCreatorResp := readResponse(t, connAdmin, 31, 3*time.Second)
	if kickCreatorResp["status"] != "error" {
		t.Errorf("expected error when trying to kick server creator, got: %+v", kickCreatorResp)
	}

	// 6. Admin kicks member
	kickReq, _ := json.Marshal(map[string]interface{}{
		"id":             32,
		"action":         "kick_member",
		"target_user_id": 2,
		"reason":         "Testing kick",
	})
	_ = connAdmin.WriteMessage(websocket.TextMessage, kickReq)
	kickResp := readResponse(t, connAdmin, 32, 3*time.Second)
	if kickResp["status"] != "ok" {
		t.Errorf("expected ok kick_member, got: %+v", kickResp)
	}
}
