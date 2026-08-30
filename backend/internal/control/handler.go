package control

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	"low_latency_voice_app/backend/internal/auth"
	"low_latency_voice_app/backend/internal/model"
	"low_latency_voice_app/backend/internal/storage"
)

// HandleMessage parses and routes raw client WebSocket frames.
func (h *Hub) HandleMessage(c *Client, raw []byte) {
	var env RequestEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		c.SendJSON(NewErrorResponse(nil, "", ErrCodeParseError, "Parse error"))
		return
	}

	// Also parse top-level raw map for flexible parameter extraction
	var rawMap map[string]interface{}
	_ = json.Unmarshal(raw, &rawMap)

	action := strings.ToLower(strings.TrimSpace(env.Action))
	reqID := env.ID
	if reqID == nil && env.RequestID != "" {
		reqID = env.RequestID
	}

	if action == "" {
		c.SendJSON(NewErrorResponse(reqID, "", ErrCodeInvalidRequest, "Invalid Request: missing action"))
		return
	}

	// Extract helper parameters from params map or top-level fields
	params := env.Params
	if params == nil {
		params = rawMap
	}

	// Enforce authentication gate on protected actions
	if !c.isAuthenticated && action != "auth" && action != "login" && action != "register" && action != "ping" {
		c.SendJSON(NewErrorResponse(reqID, action, ErrCodeUnauthorized, "Authentication required"))
		return
	}

	switch action {
	case "register":
		h.handleRegister(c, reqID, params)
	case "login":
		h.handleLogin(c, reqID, params)
	case "auth":
		h.handleAuth(c, reqID, params)
	case "get_channels", "list_channels":
		h.handleGetChannels(c, reqID)
	case "create_channel":
		h.handleCreateChannel(c, reqID, params)
	case "delete_channel":
		h.handleDeleteChannel(c, reqID, params)
	case "send_chat":
		h.handleSendChat(c, reqID, params)
	case "get_chat_history":
		h.handleGetChatHistory(c, reqID, params)
	case "join_voice":
		h.handleJoinVoice(c, reqID, params)
	case "leave_voice":
		h.handleLeaveVoice(c, reqID, params)
	case "set_voice_state":
		h.handleSetVoiceState(c, reqID, params)
	case "get_roster":
		h.handleGetRoster(c, reqID)
	case "move_member":
		h.handleMoveMember(c, reqID, params)
	case "set_server_mute":
		h.handleSetServerMute(c, reqID, params)
	case "set_server_deafen":
		h.handleSetServerDeafen(c, reqID, params)
	case "kick_member":
		h.handleKickMember(c, reqID, params)
	case "ping":
		c.SendJSON(NewSuccessResponse(reqID, "pong", map[string]interface{}{
			"action":      "pong",
			"server_time": time.Now().UTC().Unix(),
		}))
	default:
		c.SendJSON(NewErrorResponse(reqID, action, ErrCodeMethodNotFound, fmt.Sprintf("Method not found: %s", action)))
	}
}

// --- Action Handlers ---

func (h *Hub) handleRegister(c *Client, reqID interface{}, params map[string]interface{}) {
	username := getString(params, "username")
	password := getString(params, "password")
	clientVersion := getString(params, "client_version")

	res, err := h.authService.Register(username, password, clientVersion)
	if err != nil {
		if errors.Is(err, storage.ErrDuplicateUser) {
			c.SendJSON(NewErrorResponse(reqID, "register", ErrCodeUserAlreadyExists, "Username already exists"))
			return
		}
		if errors.Is(err, auth.ErrInvalidUsernameFormat) {
			c.SendJSON(NewErrorResponse(reqID, "register", ErrCodeInvalidParams, err.Error()))
			return
		}
		if errors.Is(err, auth.ErrPasswordTooShort) || errors.Is(err, auth.ErrPasswordTooLong) {
			c.SendJSON(NewErrorResponse(reqID, "register", ErrCodeInvalidParams, err.Error()))
			return
		}
		c.SendJSON(NewErrorResponse(reqID, "register", ErrCodeInternalError, err.Error()))
		return
	}

	// Update client state
	c.mu.Lock()
	c.userID = res.UserID
	c.username = res.Username
	c.roles = res.Roles
	c.permissions = res.Permissions
	c.isAdmin = res.IsAdmin
	c.isAuthenticated = true
	c.sessionToken = res.Token
	c.mu.Unlock()

	// Register in hub user map
	h.mu.Lock()
	if _, exists := h.userClients[res.UserID]; !exists {
		h.userClients[res.UserID] = make(map[*Client]bool)
	}
	h.userClients[res.UserID][c] = true
	h.mu.Unlock()

	// Respond with success
	c.SendJSON(NewSuccessResponse(reqID, "register", map[string]interface{}{
		"user_id":     res.UserID,
		"username":    res.Username,
		"token":       res.Token,
		"is_admin":    res.IsAdmin,
		"roles":       res.Roles,
		"permissions": res.Permissions,
		"udp_port":    res.UDPPort,
	}))

	// Broadcast member_joined
	h.BroadcastEvent("member_joined", map[string]interface{}{
		"user_id":    res.UserID,
		"username":   res.Username,
		"roles":      res.Roles,
		"is_admin":   res.IsAdmin,
		"created_at": time.Now().UTC().Unix(),
	})

	// Broadcast presence_update
	h.BroadcastEvent("presence_update", map[string]interface{}{
		"user_id":   res.UserID,
		"username":  res.Username,
		"roles":     res.Roles,
		"online":    true,
		"status":    "online",
		"last_seen": time.Now().UTC().Unix(),
	})
}

func (h *Hub) handleLogin(c *Client, reqID interface{}, params map[string]interface{}) {
	username := getString(params, "username")
	password := getString(params, "password")
	clientVersion := getString(params, "client_version")

	res, err := h.authService.Login(username, password, clientVersion)
	if err != nil {
		if errors.Is(err, auth.ErrInvalidCredentials) {
			c.SendJSON(NewErrorResponse(reqID, "login", ErrCodeInvalidCredentials, "Invalid username or password"))
			return
		}
		if errors.Is(err, auth.ErrUserDisabled) {
			c.SendJSON(NewErrorResponse(reqID, "login", ErrCodeUnauthorized, "User account is disabled"))
			return
		}
		c.SendJSON(NewErrorResponse(reqID, "login", ErrCodeInternalError, err.Error()))
		return
	}

	c.mu.Lock()
	c.userID = res.UserID
	c.username = res.Username
	c.roles = res.Roles
	c.permissions = res.Permissions
	c.isAdmin = res.IsAdmin
	c.isAuthenticated = true
	c.sessionToken = res.Token
	c.mu.Unlock()

	h.mu.Lock()
	if _, exists := h.userClients[res.UserID]; !exists {
		h.userClients[res.UserID] = make(map[*Client]bool)
	}
	h.userClients[res.UserID][c] = true
	h.mu.Unlock()

	c.SendJSON(NewSuccessResponse(reqID, "login", map[string]interface{}{
		"user_id":     res.UserID,
		"username":    res.Username,
		"token":       res.Token,
		"is_admin":    res.IsAdmin,
		"roles":       res.Roles,
		"permissions": res.Permissions,
		"udp_port":    res.UDPPort,
	}))

	h.BroadcastEvent("presence_update", map[string]interface{}{
		"user_id":   res.UserID,
		"username":  res.Username,
		"roles":     res.Roles,
		"online":    true,
		"status":    "online",
		"last_seen": time.Now().UTC().Unix(),
	})
}

func (h *Hub) handleAuth(c *Client, reqID interface{}, params map[string]interface{}) {
	token := getString(params, "token")
	if token == "" {
		c.SendJSON(NewErrorResponse(reqID, "auth", ErrCodeUnauthorized, "Missing session token"))
		return
	}

	session, err := h.authService.ValidateSession(token)
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "auth", ErrCodeUnauthorized, "Invalid or expired session token"))
		return
	}

	user, roles, perms, err := h.storage.GetUserWithRoles(session.UserID)
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "auth", ErrCodeInternalError, "Failed to load user profile"))
		return
	}

	isAdmin := model.HasPermission(perms, model.PermAdmin)

	c.mu.Lock()
	c.userID = user.ID
	c.username = user.Username
	c.roles = roles
	c.permissions = perms
	c.isAdmin = isAdmin
	c.isAuthenticated = true
	c.sessionToken = token
	c.mu.Unlock()

	h.mu.Lock()
	if _, exists := h.userClients[user.ID]; !exists {
		h.userClients[user.ID] = make(map[*Client]bool)
	}
	h.userClients[user.ID][c] = true
	h.mu.Unlock()

	c.SendJSON(NewSuccessResponse(reqID, "auth", map[string]interface{}{
		"user_id":     user.ID,
		"username":    user.Username,
		"is_admin":    isAdmin,
		"roles":       roles,
		"permissions": perms,
		"udp_port":    7878,
	}))

	h.BroadcastEvent("presence_update", map[string]interface{}{
		"user_id":   user.ID,
		"username":  user.Username,
		"roles":     roles,
		"online":    true,
		"status":    "online",
		"last_seen": time.Now().UTC().Unix(),
	})
}

func (h *Hub) handleGetChannels(c *Client, reqID interface{}) {
	channels, err := h.storage.GetChannels()
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "get_channels", ErrCodeInternalError, "Failed to fetch channels"))
		return
	}

	c.SendJSON(NewSuccessResponse(reqID, "get_channels", map[string]interface{}{
		"channels": channels,
	}))
}

func (h *Hub) handleCreateChannel(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermManageChannels) {
		c.SendJSON(NewErrorResponse(reqID, "create_channel", ErrCodeForbidden, "Permission denied: ManageChannels required"))
		return
	}

	name := strings.TrimSpace(getString(params, "name"))
	channelType := strings.ToLower(strings.TrimSpace(getString(params, "type")))
	category := strings.TrimSpace(getString(params, "category"))
	position := getInt(params, "position")
	bitrate := getInt(params, "bitrate")
	userLimit := getInt(params, "user_limit")

	if name == "" || (channelType != "text" && channelType != "voice") {
		c.SendJSON(NewErrorResponse(reqID, "create_channel", ErrCodeInvalidParams, "Invalid channel name or type ('text' or 'voice' required)"))
		return
	}

	if category == "" {
		if channelType == "voice" {
			category = "Voice Channels"
		} else {
			category = "Text Channels"
		}
	}
	if bitrate == 0 {
		bitrate = 64000
	}
	if userLimit == 0 && channelType == "voice" {
		userLimit = 15
	}

	ch, err := h.storage.CreateChannel(name, channelType, category, position, bitrate, userLimit)
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "create_channel", ErrCodeInternalError, err.Error()))
		return
	}

	c.SendJSON(NewSuccessResponse(reqID, "create_channel", map[string]interface{}{
		"channel": ch,
	}))

	h.BroadcastEvent("channel_created", map[string]interface{}{
		"channel": ch,
	})
}

func (h *Hub) handleDeleteChannel(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermManageChannels) {
		c.SendJSON(NewErrorResponse(reqID, "delete_channel", ErrCodeForbidden, "Permission denied: ManageChannels required"))
		return
	}

	channelID := uint32(getInt(params, "channel_id"))
	if channelID == 0 {
		c.SendJSON(NewErrorResponse(reqID, "delete_channel", ErrCodeInvalidParams, "channel_id is required"))
		return
	}

	err := h.storage.DeleteChannel(channelID)
	if err != nil {
		if errors.Is(err, storage.ErrChannelNotFound) {
			c.SendJSON(NewErrorResponse(reqID, "delete_channel", ErrCodeChannelNotFound, "Channel not found"))
			return
		}
		c.SendJSON(NewErrorResponse(reqID, "delete_channel", ErrCodeInternalError, err.Error()))
		return
	}

	c.SendJSON(NewSuccessResponse(reqID, "delete_channel", map[string]interface{}{
		"channel_id": channelID,
	}))

	h.BroadcastEvent("channel_deleted", map[string]interface{}{
		"channel_id": channelID,
	})
}

func (h *Hub) handleSendChat(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermSendMessages) {
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeForbidden, "Permission denied: SendMessages required"))
		return
	}

	channelID := uint32(getInt(params, "channel_id"))
	content := getString(params, "content")

	if channelID == 0 {
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeInvalidParams, "channel_id is required"))
		return
	}

	trimmedContent := strings.TrimSpace(content)
	if trimmedContent == "" {
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeMessageEmpty, "Message content cannot be empty"))
		return
	}

	if len([]rune(content)) > 4000 {
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeMessageTooLong, "Message exceeds maximum length of 4000 characters"))
		return
	}

	if !c.AllowMessage() {
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeRateLimitExceeded, "Rate limit exceeded (max 10 messages/sec)"))
		return
	}

	msg, err := h.storage.CreateMessage(channelID, c.userID, content)
	if err != nil {
		if errors.Is(err, storage.ErrChannelNotFound) {
			c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeChannelNotFound, "Channel not found"))
			return
		}
		c.SendJSON(NewErrorResponse(reqID, "send_chat", ErrCodeInternalError, err.Error()))
		return
	}

	c.SendJSON(NewSuccessResponse(reqID, "send_chat", map[string]interface{}{
		"message_id":  msg.ID,
		"channel_id":  msg.ChannelID,
		"sender_id":   msg.SenderID,
		"sender_name": msg.SenderName,
		"content":     msg.Content,
		"timestamp":   msg.Timestamp,
	}))

	h.BroadcastEvent("chat_message", map[string]interface{}{
		"id":          msg.ID,
		"channel_id":  msg.ChannelID,
		"sender_id":   msg.SenderID,
		"sender_name": msg.SenderName,
		"content":     msg.Content,
		"timestamp":   msg.Timestamp,
	})
}

func (h *Hub) handleGetChatHistory(c *Client, reqID interface{}, params map[string]interface{}) {
	channelID := uint32(getInt(params, "channel_id"))
	beforeID := uint64(getInt64(params, "before_id"))
	limit := getInt(params, "limit")

	if channelID == 0 {
		c.SendJSON(NewErrorResponse(reqID, "get_chat_history", ErrCodeInvalidParams, "channel_id is required"))
		return
	}

	messages, hasMore, err := h.storage.GetMessages(channelID, beforeID, limit)
	if err != nil {
		if errors.Is(err, storage.ErrChannelNotFound) {
			c.SendJSON(NewErrorResponse(reqID, "get_chat_history", ErrCodeChannelNotFound, "Channel not found"))
			return
		}
		c.SendJSON(NewErrorResponse(reqID, "get_chat_history", ErrCodeInternalError, err.Error()))
		return
	}

	c.SendJSON(NewSuccessResponse(reqID, "get_chat_history", map[string]interface{}{
		"channel_id": channelID,
		"messages":   messages,
		"has_more":   hasMore,
	}))
}

func (h *Hub) handleJoinVoice(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermConnectVoice) {
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeForbidden, "Permission denied: ConnectVoice required"))
		return
	}

	channelID := uint32(getInt(params, "channel_id"))
	selfMuted := getBool(params, "self_muted")
	selfDeafened := getBool(params, "self_deafened")

	if channelID == 0 {
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeInvalidParams, "channel_id is required"))
		return
	}

	ch, err := h.storage.GetChannelByID(channelID)
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeChannelNotFound, "Voice channel not found"))
		return
	}
	if ch.Type != "voice" {
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeInvalidChannelType, "Channel is not a voice channel"))
		return
	}

	h.mu.Lock()
	if !h.clients[c] || c.closed {
		h.mu.Unlock()
		return
	}

	occupants := h.voiceChannels[channelID]
	limit := ch.UserLimit
	if limit == 0 {
		limit = 15
	}
	if len(occupants) >= limit && !occupants[c] {
		h.mu.Unlock()
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeChannelFull, "Voice channel is full (max 15 users)"))
		return
	}

	// Remove from old channel if switching
	if c.activeVoiceChannel > 0 && c.activeVoiceChannel != channelID {
		oldCh := c.activeVoiceChannel
		if oldMap, exists := h.voiceChannels[oldCh]; exists {
			delete(oldMap, c)
		}
	}

	c.activeVoiceChannel = channelID
	if _, exists := h.voiceChannels[channelID]; !exists {
		h.voiceChannels[channelID] = make(map[*Client]bool)
	}
	h.voiceChannels[channelID][c] = true

	// Record in-memory voice state
	vState := &model.VoiceState{
		UserID:       c.userID,
		Username:     c.username,
		ChannelID:    channelID,
		IsSpeaking:   false,
		SelfMuted:    selfMuted,
		SelfDeafened: selfDeafened,
		UpdatedAt:    time.Now().UTC(),
	}
	h.voiceStates[c.userID] = vState
	h.mu.Unlock()

	// Generate single-use UDP token
	vt, err := h.authService.GenerateUDPToken(c.userID, channelID)
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "join_voice", ErrCodeInternalError, "Failed to issue voice token"))
		return
	}

	if h.audioRouter != nil {
		h.audioRouter.Sessions().RegisterPending(vt.Token, c.userID, channelID, vt.SSRC, vt.ExpiresAt)
	}

	c.SendJSON(NewSuccessResponse(reqID, "join_voice", map[string]interface{}{
		"channel_id": channelID,
		"udp_token":  vt.Token,
		"udp_port":   7878,
		"ssrc":       vt.SSRC,
	}))

	h.BroadcastEvent("voice_state_update", map[string]interface{}{
		"user_id":         c.userID,
		"username":        c.username,
		"channel_id":      channelID,
		"self_muted":      selfMuted,
		"self_deafened":   selfDeafened,
		"server_muted":    false,
		"server_deafened": false,
	})
}

func (h *Hub) handleLeaveVoice(c *Client, reqID interface{}, params map[string]interface{}) {
	h.mu.Lock()
	chID := c.activeVoiceChannel
	if chID > 0 {
		if vMap, exists := h.voiceChannels[chID]; exists {
			delete(vMap, c)
		}
		c.activeVoiceChannel = 0
		delete(h.voiceStates, c.userID)
	}
	h.mu.Unlock()

	if h.audioRouter != nil {
		h.audioRouter.Sessions().RemoveSession(c.userID)
	}

	c.SendJSON(NewSuccessResponse(reqID, "leave_voice", map[string]interface{}{
		"channel_id": chID,
	}))

	if chID > 0 {
		h.BroadcastEvent("voice_state_update", map[string]interface{}{
			"user_id":         c.userID,
			"username":        c.username,
			"channel_id":      nil,
			"is_speaking":     false,
			"self_muted":      false,
			"self_deafened":   false,
			"server_muted":    false,
			"server_deafened": false,
		})
	}
}

func (h *Hub) handleSetVoiceState(c *Client, reqID interface{}, params map[string]interface{}) {
	selfMuted := getBool(params, "self_muted")
	selfDeafened := getBool(params, "self_deafened")
	isSpeaking := getBool(params, "is_speaking")

	h.mu.Lock()
	if vs, exists := h.voiceStates[c.userID]; exists {
		vs.SelfMuted = selfMuted
		vs.SelfDeafened = selfDeafened
		vs.IsSpeaking = isSpeaking
		vs.UpdatedAt = time.Now().UTC()
	}
	chID := c.activeVoiceChannel
	h.mu.Unlock()

	c.SendJSON(NewSuccessResponse(reqID, "set_voice_state", map[string]interface{}{
		"self_muted":    selfMuted,
		"self_deafened": selfDeafened,
		"is_speaking":   isSpeaking,
	}))

	var chPtr *uint32
	if chID > 0 {
		chPtr = &chID
	}

	h.BroadcastEvent("voice_state_update", map[string]interface{}{
		"user_id":         c.userID,
		"username":        c.username,
		"channel_id":      chPtr,
		"is_speaking":     isSpeaking,
		"self_muted":      selfMuted,
		"self_deafened":   selfDeafened,
		"server_muted":    false,
		"server_deafened": false,
	})
}

func (h *Hub) handleGetRoster(c *Client, reqID interface{}) {
	users, err := h.storage.GetAllUsersWithRoles()
	if err != nil {
		c.SendJSON(NewErrorResponse(reqID, "get_roster", ErrCodeInternalError, "Failed to load roster"))
		return
	}

	type RosterMember struct {
		UserID         uint32            `json:"user_id"`
		Username       string            `json:"username"`
		Roles          []string          `json:"roles"`
		IsAdmin        bool              `json:"is_admin"`
		Online         bool              `json:"online"`
		VoiceChannelID *uint32           `json:"voice_channel_id"`
		VoiceState     *model.VoiceState `json:"voice_state,omitempty"`
	}

	h.mu.RLock()
	members := make([]RosterMember, 0, len(users))
	for _, u := range users {
		isOnline := len(h.userClients[u.ID]) > 0
		var vChan *uint32
		var vState *model.VoiceState

		if state, exists := h.voiceStates[u.ID]; exists && state.ChannelID > 0 {
			vChan = &state.ChannelID
			vState = state
		}

		members = append(members, RosterMember{
			UserID:         u.ID,
			Username:       u.Username,
			Roles:          u.Roles,
			IsAdmin:        u.IsAdmin,
			Online:         isOnline,
			VoiceChannelID: vChan,
			VoiceState:     vState,
		})
	}
	h.mu.RUnlock()

	c.SendJSON(NewSuccessResponse(reqID, "get_roster", map[string]interface{}{
		"members": members,
	}))
}

// --- Moderation Handlers ---

func (h *Hub) handleMoveMember(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermMoveMembers) {
		c.SendJSON(NewErrorResponse(reqID, "move_member", ErrCodeForbidden, "Permission denied: MoveMembers required"))
		return
	}

	targetUserID := uint32(getInt(params, "target_user_id"))
	toChannelID := uint32(getInt(params, "to_channel_id"))

	h.mu.Lock()
	state, exists := h.voiceStates[targetUserID]
	if !exists || state.ChannelID == 0 {
		h.mu.Unlock()
		c.SendJSON(NewErrorResponse(reqID, "move_member", ErrCodeInvalidParams, "Target user is not currently in a voice channel"))
		return
	}

	fromChannelID := state.ChannelID
	state.ChannelID = toChannelID

	// Move client connections
	if clientMap, ok := h.userClients[targetUserID]; ok {
		for client := range clientMap {
			if oldMap, ok := h.voiceChannels[fromChannelID]; ok {
				delete(oldMap, client)
			}
			if _, ok := h.voiceChannels[toChannelID]; !ok {
				h.voiceChannels[toChannelID] = make(map[*Client]bool)
			}
			h.voiceChannels[toChannelID][client] = true
			client.activeVoiceChannel = toChannelID
		}
	}
	h.mu.Unlock()

	if h.audioRouter != nil {
		h.audioRouter.Sessions().MoveMember(targetUserID, toChannelID)
	}

	c.SendJSON(NewSuccessResponse(reqID, "move_member", map[string]interface{}{
		"user_id":         targetUserID,
		"from_channel_id": fromChannelID,
		"to_channel_id":   toChannelID,
	}))

	h.BroadcastEvent("member_moved", map[string]interface{}{
		"user_id":         targetUserID,
		"from_channel_id": fromChannelID,
		"to_channel_id":   toChannelID,
	})

	h.BroadcastEvent("voice_state_update", map[string]interface{}{
		"user_id":    targetUserID,
		"channel_id": toChannelID,
	})
}

func (h *Hub) handleSetServerMute(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermMuteMembers) {
		c.SendJSON(NewErrorResponse(reqID, "set_server_mute", ErrCodeForbidden, "Permission denied: MuteMembers required"))
		return
	}

	targetUserID := uint32(getInt(params, "target_user_id"))
	muted := getBool(params, "muted")

	h.mu.Lock()
	if state, exists := h.voiceStates[targetUserID]; exists {
		state.ServerMuted = muted
	}
	h.mu.Unlock()

	if h.audioRouter != nil {
		h.audioRouter.Sessions().SetServerMute(targetUserID, muted)
	}

	c.SendJSON(NewSuccessResponse(reqID, "set_server_mute", map[string]interface{}{
		"user_id":      targetUserID,
		"server_muted": muted,
	}))

	h.BroadcastEvent("voice_state_update", map[string]interface{}{
		"user_id":      targetUserID,
		"server_muted": muted,
	})
}

func (h *Hub) handleSetServerDeafen(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermDeafenMembers) {
		c.SendJSON(NewErrorResponse(reqID, "set_server_deafen", ErrCodeForbidden, "Permission denied: DeafenMembers required"))
		return
	}

	targetUserID := uint32(getInt(params, "target_user_id"))
	deafened := getBool(params, "deafened")

	h.mu.Lock()
	if state, exists := h.voiceStates[targetUserID]; exists {
		state.ServerDeafened = deafened
	}
	h.mu.Unlock()

	if h.audioRouter != nil {
		h.audioRouter.Sessions().SetServerDeafen(targetUserID, deafened)
	}

	c.SendJSON(NewSuccessResponse(reqID, "set_server_deafen", map[string]interface{}{
		"user_id":         targetUserID,
		"server_deafened": deafened,
	}))

	h.BroadcastEvent("voice_state_update", map[string]interface{}{
		"user_id":         targetUserID,
		"server_deafened": deafened,
	})
}

func (h *Hub) handleKickMember(c *Client, reqID interface{}, params map[string]interface{}) {
	if !model.HasPermission(c.permissions, model.PermKickMembers) {
		c.SendJSON(NewErrorResponse(reqID, "kick_member", ErrCodeForbidden, "Permission denied: KickMembers required"))
		return
	}

	targetUserID := uint32(getInt(params, "target_user_id"))
	reason := getString(params, "reason")
	if reason == "" {
		reason = "Kicked by moderator"
	}

	if targetUserID == 1 {
		c.SendJSON(NewErrorResponse(reqID, "kick_member", ErrCodeImmutableCreatorRole, "Cannot kick server creator"))
		return
	}

	_ = h.storage.DeleteUserSessions(targetUserID)
	_ = h.storage.RevokeVoiceTokens(targetUserID)

	h.mu.Lock()
	var clientsToClose []*Client
	if clientMap, ok := h.userClients[targetUserID]; ok {
		for client := range clientMap {
			clientsToClose = append(clientsToClose, client)
		}
	}
	var hadVoiceChannel uint32
	if vs, ok := h.voiceStates[targetUserID]; ok {
		chID := vs.ChannelID
		hadVoiceChannel = chID
		if oldMap, ok := h.voiceChannels[chID]; ok {
			for _, client := range clientsToClose {
				delete(oldMap, client)
			}
		}
		delete(h.voiceStates, targetUserID)
	}
	h.mu.Unlock()

	if h.audioRouter != nil {
		h.audioRouter.Sessions().RemoveSession(targetUserID)
	}

	for _, client := range clientsToClose {
		closeMsg := websocket.FormatCloseMessage(4001, reason)
		_ = client.conn.WriteControl(websocket.CloseMessage, closeMsg, time.Now().Add(writeWait))
		h.UnregisterClient(client)
	}

	c.SendJSON(NewSuccessResponse(reqID, "kick_member", map[string]interface{}{
		"user_id": targetUserID,
		"reason":  reason,
	}))

	h.BroadcastEvent("member_kicked", map[string]interface{}{
		"user_id": targetUserID,
		"reason":  reason,
	})

	if hadVoiceChannel > 0 {
		h.BroadcastEvent("voice_state_update", map[string]interface{}{
			"user_id":         targetUserID,
			"channel_id":      nil,
			"is_speaking":     false,
			"self_muted":      false,
			"self_deafened":   false,
			"server_muted":    false,
			"server_deafened": false,
		})
	}
}

// --- Parameter Extraction Helpers ---

func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key]; ok {
		if s, ok := v.(string); ok {
			return strings.TrimSpace(s)
		}
	}
	return ""
}

func getInt(m map[string]interface{}, key string) int {
	if v, ok := m[key]; ok {
		switch n := v.(type) {
		case float64:
			return int(n)
		case int:
			return n
		case int64:
			return int(n)
		case uint32:
			return int(n)
		}
	}
	return 0
}

func getInt64(m map[string]interface{}, key string) int64 {
	if v, ok := m[key]; ok {
		switch n := v.(type) {
		case float64:
			return int64(n)
		case int64:
			return n
		case int:
			return int64(n)
		case uint64:
			return int64(n)
		}
	}
	return 0
}

func getBool(m map[string]interface{}, key string) bool {
	if v, ok := m[key]; ok {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	return false
}
