package control

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const (
	// writeWait: Max time allowed to write a message to the peer.
	writeWait = 10 * time.Second

	// pongWait: Max time allowed to read the next pong message from the peer.
	pongWait = 60 * time.Second

	// pingPeriod: Send pings to peer with this period (must be < pongWait).
	pingPeriod = 20 * time.Second

	// maxMessageSize: Max allowed inbound frame size (64 KB).
	maxMessageSize = 64 * 1024

	// sendBufferSize: Capacity of client outbound channel (256 frames).
	sendBufferSize = 256
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 4096,
	CheckOrigin: func(r *http.Request) bool {
		// Allow local, LAN, and Tailscale mesh origins
		return true
	},
	EnableCompression: false,
}

// Client represents a single active WebSocket connection.
type Client struct {
	hub *Hub

	// WebSocket connection handle.
	conn *websocket.Conn

	// Buffered channel of outbound messages.
	send chan []byte

	// Authenticated user state
	userID             uint32
	username           string
	roles              []string
	permissions        uint32
	isAuthenticated    bool
	isAdmin            bool
	activeVoiceChannel uint32
	sessionToken       string

	// Rate limiter (sliding window for chat messages: max 10/sec)
	msgTimestamps []time.Time
	rateMu        sync.Mutex

	// Mutex protecting mutable client fields
	mu sync.RWMutex

	// Close state
	closed bool
}

// NewClient initializes a Client instance.
func NewClient(hub *Hub, conn *websocket.Conn) *Client {
	return &Client{
		hub:           hub,
		conn:          conn,
		send:          make(chan []byte, sendBufferSize),
		msgTimestamps: make([]time.Time, 0, 16),
	}
}

// AllowMessage checks if client is within rate limits (10 req/s).
func (c *Client) AllowMessage() bool {
	c.rateMu.Lock()
	defer c.rateMu.Unlock()

	now := time.Now()
	cutoff := now.Add(-1 * time.Second)

	valid := c.msgTimestamps[:0]
	for _, t := range c.msgTimestamps {
		if t.After(cutoff) {
			valid = append(valid, t)
		}
	}
	c.msgTimestamps = valid

	if len(c.msgTimestamps) >= 10 {
		return false
	}

	c.msgTimestamps = append(c.msgTimestamps, now)
	return true
}

// Send non-blockingly enqueues a message for transmission.
func (c *Client) Send(msg []byte) bool {
	c.mu.RLock()
	if c.closed {
		c.mu.RUnlock()
		return false
	}
	c.mu.RUnlock()

	select {
	case c.send <- msg:
		return true
	default:
		log.Printf("[Client] Buffer full (256 frames) for user %d (%s), scheduling disconnect", c.userID, c.username)
		select {
		case c.hub.unregister <- c:
		default:
		}
		return false
	}
}

// SendJSON marshals and sends a JSON payload to this client.
func (c *Client) SendJSON(v interface{}) error {
	bytes, err := json.Marshal(v)
	if err != nil {
		return err
	}
	c.Send(bytes)
	return nil
}

// readPump pumps messages from the websocket connection to the Hub.
func (c *Client) readPump() {
	defer func() {
		c.hub.UnregisterClient(c)
	}()

	c.conn.SetReadLimit(maxMessageSize)
	_ = c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		_ = c.conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure, websocket.CloseNormalClosure, 4001, 4002, 4003, 4004) {
				log.Printf("[Client] WebSocket read error from %s: %v", c.conn.RemoteAddr(), err)
			}
			break
		}

		c.hub.HandleMessage(c, message)
	}
}

// writePump pumps messages from the send channel to the websocket connection.
func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		_ = c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				// Hub closed the channel
				_ = c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			w, err := c.conn.NextWriter(websocket.TextMessage)
			if err != nil {
				return
			}
			_, _ = w.Write(message)
			if err := w.Close(); err != nil {
				return
			}

		case <-ticker.C:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// Close closes the client send channel and marks closed.
func (c *Client) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.closed {
		c.closed = true
		close(c.send)
		_ = c.conn.Close()
	}
}

// ServeWs handles incoming WebSocket upgrade requests.
func ServeWs(hub *Hub, w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("[ServeWs] Failed to upgrade connection: %v", err)
		return
	}

	client := NewClient(hub, conn)
	hub.RegisterClient(client)

	go client.writePump()
	go client.readPump()
}
