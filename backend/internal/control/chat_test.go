package control

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestChat_EmptyMessageRejection(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "ChatTester1",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Empty content
	chat, _ := json.Marshal(map[string]interface{}{
		"id":         10,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    "    ",
	})
	_ = conn.WriteMessage(websocket.TextMessage, chat)

	resp := readResponse(t, conn, 10, 2*time.Second)
	errMap, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error response, got: %+v", resp)
	}
	code, _ := errMap["code"].(float64)
	if int(code) != ErrCodeMessageEmpty {
		t.Errorf("expected ErrCodeMessageEmpty (%d), got %d (%+v)", ErrCodeMessageEmpty, int(code), resp)
	}
}

func TestChat_4000CharsAndLimit(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "ChatTester2",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// 1. Exactly 4000 characters
	long4000 := strings.Repeat("A", 4000)
	chat4000, _ := json.Marshal(map[string]interface{}{
		"id":         20,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    long4000,
	})
	_ = conn.WriteMessage(websocket.TextMessage, chat4000)

	resp4000 := readResponse(t, conn, 20, 3*time.Second)
	if resp4000["status"] != "ok" {
		t.Errorf("expected ok for 4000 chars, got: %+v", resp4000)
	}

	// 2. 4001 characters
	long4001 := strings.Repeat("B", 4001)
	chat4001, _ := json.Marshal(map[string]interface{}{
		"id":         21,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    long4001,
	})
	_ = conn.WriteMessage(websocket.TextMessage, chat4001)

	resp4001 := readResponse(t, conn, 21, 2*time.Second)
	errMap, ok := resp4001["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected error response for 4001 chars, got: %+v", resp4001)
	}
	code, _ := errMap["code"].(float64)
	if int(code) != ErrCodeMessageTooLong {
		t.Errorf("expected ErrCodeMessageTooLong (%d), got %d", ErrCodeMessageTooLong, int(code))
	}
}

func TestChat_UTF8Emojis(t *testing.T) {
	_, server, _, repo, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "EmojiUser",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	emojiContent := "Hello 🚀🎉🔥 UTF-8 and German ÄÖÜäöüß"
	chat, _ := json.Marshal(map[string]interface{}{
		"id":         30,
		"action":     "send_chat",
		"channel_id": 1,
		"content":    emojiContent,
	})
	_ = conn.WriteMessage(websocket.TextMessage, chat)

	sendResp := readResponse(t, conn, 30, 3*time.Second)
	if sendResp["status"] != "ok" {
		t.Fatalf("expected ok response, got: %+v", sendResp)
	}

	// Verify in DB directly
	messages, _, err := repo.GetMessages(1, 0, 10)
	if err != nil {
		t.Fatalf("get messages error: %v", err)
	}
	if len(messages) == 0 || messages[len(messages)-1].Content != emojiContent {
		t.Errorf("emoji message content mismatch in DB: %+v", messages)
	}
}

func TestChat_RateLimiter(t *testing.T) {
	_, server, _, _, cleanup := setupTestServer(t)
	defer cleanup()

	conn := connectWS(t, server.URL)
	defer conn.Close()

	reg, _ := json.Marshal(map[string]interface{}{
		"id":       1,
		"action":   "register",
		"username": "SpammerTester",
		"password": "Password123!",
	})
	_ = conn.WriteMessage(websocket.TextMessage, reg)
	_ = readResponse(t, conn, 1, 3*time.Second)

	// Send 12 messages in burst
	rateLimitedSeen := false
	for i := 1; i <= 12; i++ {
		chat, _ := json.Marshal(map[string]interface{}{
			"id":         100 + i,
			"action":     "send_chat",
			"channel_id": 1,
			"content":    fmt.Sprintf("Burst message %d", i),
		})
		_ = conn.WriteMessage(websocket.TextMessage, chat)
		resp := readResponse(t, conn, 100+i, 2*time.Second)
		if resp["status"] == "error" {
			if errMap, ok := resp["error"].(map[string]interface{}); ok {
				if code, ok := errMap["code"].(float64); ok && int(code) == ErrCodeRateLimitExceeded {
					rateLimitedSeen = true
				}
			}
		}
	}

	if !rateLimitedSeen {
		t.Errorf("expected at least one rate limit error response when sending 12 messages in burst")
	}
}
