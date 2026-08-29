package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"low_latency_voice_app/backend/internal/auth"
	"low_latency_voice_app/backend/internal/control"
	"low_latency_voice_app/backend/internal/storage"
)

func setupTestHTTPServer(t *testing.T) (*httptest.Server, func()) {
	t.Helper()
	db, err := storage.OpenDB(fmt.Sprintf("file:memrest_%d?mode=memory&cache=shared", time.Now().UnixNano()))
	if err != nil {
		t.Fatalf("failed to open test db: %v", err)
	}

	repo := storage.NewSQLiteRepository(db)
	authSvc := auth.NewAuthService(repo, 7878)
	hub := control.NewHub(repo, authSvc)
	go hub.Run()

	mux := http.NewServeMux()

	// Mount endpoints matching main.go
	healthHandler := func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]interface{}{
			"status": "ok",
			"version": "1.0.0",
			"db": "connected",
		})
	}
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/healthz", healthHandler)

	mux.HandleFunc("/api/auth/register", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		res, err := authSvc.Register(req.Username, req.Password, "1.0.0")
		if err != nil {
			w.WriteHeader(http.StatusBadRequest)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{"status": "error", "error": err.Error()})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"status": "ok", "result": res})
	})

	mux.HandleFunc("/api/auth/login", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		res, err := authSvc.Login(req.Username, req.Password, "1.0.0")
		if err != nil {
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]interface{}{"status": "error", "error": err.Error()})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]interface{}{"status": "ok", "result": res})
	})

	server := httptest.NewServer(mux)

	cleanup := func() {
		hub.Close()
		server.Close()
		_ = db.Close()
	}

	return server, cleanup
}

func TestREST_HealthCheck(t *testing.T) {
	server, cleanup := setupTestHTTPServer(t)
	defer cleanup()

	resp, err := http.Get(server.URL + "/health")
	if err != nil {
		t.Fatalf("failed GET /health: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200 OK, got %d", resp.StatusCode)
	}

	var data map[string]interface{}
	_ = json.NewDecoder(resp.Body).Decode(&data)
	if data["status"] != "ok" || data["db"] != "connected" {
		t.Errorf("unexpected health payload: %+v", data)
	}
}

func TestREST_AuthRegisterAndLogin(t *testing.T) {
	server, cleanup := setupTestHTTPServer(t)
	defer cleanup()

	// 1. Register
	body, _ := json.Marshal(map[string]string{
		"username": "RestUser",
		"password": "Password123!",
	})
	resp, err := http.Post(server.URL+"/api/auth/register", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("failed POST /api/auth/register: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Errorf("expected 200 OK for register, got %d", resp.StatusCode)
	}

	// 2. Login
	respLogin, err := http.Post(server.URL+"/api/auth/login", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("failed POST /api/auth/login: %v", err)
	}
	defer respLogin.Body.Close()

	if respLogin.StatusCode != http.StatusOK {
		t.Errorf("expected 200 OK for login, got %d", respLogin.StatusCode)
	}
}
