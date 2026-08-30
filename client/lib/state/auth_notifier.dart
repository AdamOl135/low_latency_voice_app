import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/user.dart';
import '../services/websocket_service.dart';

class AuthState {
  final bool isAuthenticated;
  final bool isLoading;
  final User? user;
  final String? errorMessage;
  final bool isKicked;
  final String? kickReason;

  const AuthState({
    this.isAuthenticated = false,
    this.isLoading = false,
    this.user,
    this.errorMessage,
    this.isKicked = false,
    this.kickReason,
  });

  AuthState copyWith({
    bool? isAuthenticated,
    bool? isLoading,
    User? user,
    String? errorMessage,
    bool? isKicked,
    String? kickReason,
  }) {
    return AuthState(
      isAuthenticated: isAuthenticated ?? this.isAuthenticated,
      isLoading: isLoading ?? this.isLoading,
      user: user ?? this.user,
      errorMessage: errorMessage,
      isKicked: isKicked ?? this.isKicked,
      kickReason: kickReason ?? this.kickReason,
    );
  }
}

final webSocketServiceProvider = Provider<WebSocketService>((ref) {
  final service = WebSocketService();
  ref.onDispose(() => service.dispose());
  return service;
});

class AuthNotifier extends StateNotifier<AuthState> {
  final WebSocketService _ws;

  AuthNotifier(this._ws) : super(const AuthState()) {
    _listenToEvents();
  }

  void _listenToEvents() {
    _ws.eventStream.listen((event) {
      final eventType = event['event']?.toString();
      if (eventType == 'member_kicked') {
        final kickedUserId = event['data']?['user_id'] ?? event['user_id'];
        final reason = event['data']?['reason'] ?? event['reason'] ?? 'Kicked by administrator';
        if (state.user != null && state.user!.id == kickedUserId) {
          handleKicked(reason.toString());
        }
      } else if (eventType == 'kick_disconnect') {
        final reason = event['reason']?.toString() ?? 'Kicked by administrator';
        handleKicked(reason);
      }
    });
  }

  void handleKicked([String reason = 'Kicked by administrator']) {
    _ws.disconnect();
    state = state.copyWith(
      isAuthenticated: false,
      isLoading: false,
      isKicked: true,
      kickReason: reason,
      errorMessage: 'Kicked by administrator: $reason',
    );
  }

  Future<void> checkSavedSession() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString('auth_token');
      if (token != null && token.isNotEmpty) {
        state = state.copyWith(isLoading: true, errorMessage: null);
        await _ws.connect();
        final res = await _ws.authenticate(token);
        final userData = (res['data'] is Map) ? res['data'] : (res['result'] is Map ? res['result'] : res);
        final user = User.fromJson(Map<String, dynamic>.from(userData as Map)).copyWith(token: token);
        state = state.copyWith(isAuthenticated: true, isLoading: false, user: user);
      }
    } catch (_) {
      state = state.copyWith(isLoading: false);
    }
  }

  Future<bool> login(String username, String password) async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      await _ws.connect();
      final res = await _ws.login(username, password);
      final userData = (res['data'] is Map) ? res['data'] : (res['result'] is Map ? res['result'] : res);
      final user = User.fromJson(Map<String, dynamic>.from(userData as Map));

      if (user.token != null) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('auth_token', user.token!);
      }

      state = state.copyWith(isAuthenticated: true, isLoading: false, user: user);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString().replaceAll('Exception: ', ''));
      return false;
    }
  }

  Future<bool> register(String username, String password) async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      await _ws.connect();
      final res = await _ws.register(username, password);
      final userData = (res['data'] is Map) ? res['data'] : (res['result'] is Map ? res['result'] : res);
      final user = User.fromJson(Map<String, dynamic>.from(userData as Map));

      if (user.token != null) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('auth_token', user.token!);
      }

      state = state.copyWith(isAuthenticated: true, isLoading: false, user: user);
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString().replaceAll('Exception: ', ''));
      return false;
    }
  }

  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    _ws.disconnect();
    state = const AuthState();
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  final ws = ref.watch(webSocketServiceProvider);
  return AuthNotifier(ws);
});
