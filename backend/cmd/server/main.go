package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"low_latency_voice_app/backend/internal/audio"
	"low_latency_voice_app/backend/internal/auth"
	"low_latency_voice_app/backend/internal/control"
	"low_latency_voice_app/backend/internal/storage"
)

var (
	startTime = time.Now()
	version   = "1.0.0"
)

func main() {
	defaultPort := 8080
	if envP := os.Getenv("PORT"); envP != "" {
		if p, err := strconv.Atoi(envP); err == nil {
			defaultPort = p
		}
	}

	defaultUDPPort := 7878
	if envUDP := os.Getenv("UDP_PORT"); envUDP != "" {
		if p, err := strconv.Atoi(envUDP); err == nil {
			defaultUDPPort = p
		}
	}

	defaultDBPath := "data/voiceapp.db"
	if envDB := os.Getenv("DB_PATH"); envDB != "" {
		defaultDBPath = envDB
	} else if envDB := os.Getenv("DATABASE_PATH"); envDB != "" {
		defaultDBPath = envDB
	}

	port := flag.Int("port", defaultPort, "HTTP/WebSocket control plane server port")
	dbPath := flag.String("db", defaultDBPath, "SQLite database file path")
	udpPort := flag.Int("udp-port", defaultUDPPort, "UDP audio plane port")
	flag.Parse()

	log.Printf("Starting Low-Latency Voice App Backend Server v%s", version)
	log.Printf("Database path: %s | TCP Port: %d | UDP Port: %d", *dbPath, *port, *udpPort)

	// 1. Initialize SQLite Database with WAL mode
	db, err := storage.OpenDB(*dbPath)
	if err != nil {
		log.Fatalf("Fatal: failed to initialize database at %s: %v", *dbPath, err)
	}
	defer db.Close()
	log.Printf("Database initialized successfully in WAL mode")

	// 2. Initialize Repositories and Services
	repo := storage.NewSQLiteRepository(db)
	authSvc := auth.NewAuthService(repo, *udpPort)

	// 3. Initialize WebSocket Hub
	hub := control.NewHub(repo, authSvc)
	go hub.Run()
	defer hub.Close()
	log.Printf("WebSocket JSON-RPC Hub started")

	// 4. Initialize UDP Audio Server & SFU Router
	audioSM := audio.NewSessionManager()
	audioRouter := audio.NewRouter(audioSM, repo, hub, nil)
	hub.SetAudioRouter(audioRouter)

	audioServer := audio.NewServer(fmt.Sprintf("0.0.0.0:%d", *udpPort), audioRouter)
	if err := audioServer.Start(); err != nil {
		log.Fatalf("Fatal: failed to start UDP audio server on port %d: %v", *udpPort, err)
	}
	defer audioServer.Close()
	log.Printf("UDP Audio Plane listening on port %d", *udpPort)

	// 4. Configure HTTP Routes
	mux := http.NewServeMux()

	// Health check endpoints
	healthHandler := func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		uptime := time.Since(startTime).Seconds()
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status":         "ok",
			"version":        version,
			"uptime_seconds": int(uptime),
			"db":             "connected",
			"time":           time.Now().UTC().Format(time.RFC3339),
		})
	}
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/healthz", healthHandler)

	// REST Auth Endpoints
	mux.HandleFunc("/api/auth/register", func(w http.ResponseWriter, r *http.Request) {
		enableCORS(w)
		if r.Method == http.MethodOptions {
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			Username      string `json:"username"`
			Password      string `json:"password"`
			ClientVersion string `json:"client_version"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		res, err := authSvc.Register(req.Username, req.Password, req.ClientVersion)
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadRequest)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"status": "error",
				"error":  err.Error(),
			})
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "ok",
			"result": res,
		})
	})

	mux.HandleFunc("/api/auth/login", func(w http.ResponseWriter, r *http.Request) {
		enableCORS(w)
		if r.Method == http.MethodOptions {
			return
		}
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			Username      string `json:"username"`
			Password      string `json:"password"`
			ClientVersion string `json:"client_version"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "Invalid JSON payload", http.StatusBadRequest)
			return
		}

		res, err := authSvc.Login(req.Username, req.Password, req.ClientVersion)
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{
				"status": "error",
				"error":  err.Error(),
			})
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "ok",
			"result": res,
		})
	})

	mux.HandleFunc("/api/auth/me", func(w http.ResponseWriter, r *http.Request) {
		enableCORS(w)
		if r.Method == http.MethodOptions {
			return
		}
		authHeader := r.Header.Get("Authorization")
		token := strings.TrimPrefix(authHeader, "Bearer ")
		token = strings.TrimSpace(token)

		session, err := authSvc.ValidateSession(token)
		if err != nil {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			return
		}

		user, roles, perms, err := repo.GetUserWithRoles(session.UserID)
		if err != nil {
			http.Error(w, "Internal server error", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status":      "ok",
			"user":        user,
			"roles":       roles,
			"permissions": perms,
		})
	})

	// WebSocket Endpoint
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		control.ServeWs(hub, w, r)
	})

	// 5. Start HTTP Server
	serverAddr := fmt.Sprintf("0.0.0.0:%d", *port)
	srv := &http.Server{
		Addr:         serverAddr,
		Handler:      mux,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		log.Printf("Server listening on http://%s", serverAddr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server listen error: %v", err)
		}
	}()

	// 6. Graceful Shutdown on SIGINT/SIGTERM
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Printf("Shutting down server gracefully...")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("Server forced shutdown: %v", err)
	}

	if err := audioServer.Close(); err != nil {
		log.Printf("Audio server forced shutdown: %v", err)
	}

	log.Printf("Server exited successfully")
}

func enableCORS(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
}
