import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../core/constants.dart';

enum WsConnectionStatus { disconnected, connecting, connected, authenticated }

/// High-throughput JSON-RPC 2.0 WebSocket client for the control plane.
class WebSocketService {
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;
  Timer? _heartbeatTimer;
  Timer? _reconnectTimer;

  String _host = AppConstants.defaultHost;
  int _port = AppConstants.defaultWsPort;
  String get host => _host;
  int get port => _port;
  String? _sessionToken;
  bool _isDisposed = false;
  int _requestIdCounter = 0;
  Completer<void>? _connectingCompleter;

  WsConnectionStatus _status = WsConnectionStatus.disconnected;
  WsConnectionStatus get status => _status;

  final Map<String, Completer<Map<String, dynamic>>> _pendingRequests = {};

  final StreamController<WsConnectionStatus> _statusController =
      StreamController<WsConnectionStatus>.broadcast();
  Stream<WsConnectionStatus> get statusStream => _statusController.stream;

  final StreamController<Map<String, dynamic>> _eventController =
      StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get eventStream => _eventController.stream;

  /// Sanitizes and parses host and port inputs (supporting schemes, trailing paths, and host:port strings).
  static ({String host, int port}) parseEndpoint(String rawHost, int defaultPort) {
    var cleaned = rawHost.trim();
    if (cleaned.startsWith('ws://')) {
      cleaned = cleaned.substring(5);
    } else if (cleaned.startsWith('wss://')) {
      cleaned = cleaned.substring(6);
    } else if (cleaned.startsWith('http://')) {
      cleaned = cleaned.substring(7);
    } else if (cleaned.startsWith('https://')) {
      cleaned = cleaned.substring(8);
    }

    // Strip trailing paths e.g. /ws or /
    final slashIdx = cleaned.indexOf('/');
    if (slashIdx != -1) {
      cleaned = cleaned.substring(0, slashIdx);
    }

    var port = defaultPort;
    final colonIdx = cleaned.lastIndexOf(':');
    if (colonIdx != -1 && !cleaned.contains(']')) {
      final portPart = cleaned.substring(colonIdx + 1);
      final parsedPort = int.tryParse(portPart);
      if (parsedPort != null) {
        port = parsedPort;
        cleaned = cleaned.substring(0, colonIdx);
      }
    } else if (cleaned.startsWith('[') && cleaned.contains(']:')) {
      final closeBracket = cleaned.indexOf(']:');
      final portPart = cleaned.substring(closeBracket + 2);
      final parsedPort = int.tryParse(portPart);
      if (parsedPort != null) {
        port = parsedPort;
        cleaned = cleaned.substring(0, closeBracket + 1);
      }
    }

    if (cleaned.isEmpty) {
      cleaned = AppConstants.defaultHost;
    }

    return (host: cleaned, port: port);
  }

  void configure({String? host, int? port, String? token}) {
    if (token != null) _sessionToken = token;
    if (host != null || port != null) {
      final parsed = parseEndpoint(host ?? _host, port ?? _port);
      final changed = (parsed.host != _host || parsed.port != _port);
      _host = parsed.host;
      _port = parsed.port;
      if (changed) {
        disconnect();
      }
    }
  }

  /// Connects to the backend WebSocket server.
  /// If [force] is true, closes existing connections and starts a fresh handshake.
  Future<void> connect({String? host, int? port, bool force = false}) async {
    if (host != null || port != null) {
      final parsed = parseEndpoint(host ?? _host, port ?? _port);
      final changed = (parsed.host != _host || parsed.port != _port);
      _host = parsed.host;
      _port = parsed.port;
      if (changed) {
        force = true;
      }
    }

    if (force) {
      disconnect();
    } else {
      if (_status == WsConnectionStatus.connected ||
          _status == WsConnectionStatus.authenticated) {
        return;
      }

      if (_status == WsConnectionStatus.connecting) {
        // Await the active in-flight connection attempt
        if (_connectingCompleter != null) {
          try {
            await _connectingCompleter!.future;
            return;
          } catch (_) {
            // If the in-flight connection failed, continue below to retry
          }
        } else {
          return;
        }
      }
    }

    final completer = Completer<void>();
    _connectingCompleter = completer;
    _updateStatus(WsConnectionStatus.connecting);

    try {
      final uri = Uri.parse('ws://$_host:$_port/ws');
      final channel = WebSocketChannel.connect(uri);
      await channel.ready.timeout(const Duration(seconds: 4));
      _channel = channel;

      _updateStatus(WsConnectionStatus.connected);
      _startHeartbeat();

      _subscription = _channel!.stream.listen(
        _onMessageReceived,
        onError: _onError,
        onDone: _onDisconnected,
        cancelOnError: true,
      );

      if (!completer.isCompleted) {
        completer.complete();
      }

      // Auto-authenticate if session token exists
      if (_sessionToken != null && _sessionToken!.isNotEmpty) {
        await authenticate(_sessionToken!);
      }
    } catch (e) {
      if (!completer.isCompleted) {
        completer.completeError(e);
      }
      _onError(e);
      throw Exception('Could not connect to WebSocket at ws://$_host:$_port/ws. Please verify the server is running.');
    } finally {
      if (_connectingCompleter == completer) {
        _connectingCompleter = null;
      }
    }
  }

  void _onMessageReceived(dynamic data) {
    try {
      final text = data is String ? data : utf8.decode(data as List<int>);
      final decoded = json.decode(text) as Map<String, dynamic>;

      // Check if message is a response to a pending request
      final reqId = decoded['request_id']?.toString() ?? decoded['id']?.toString();
      if (reqId != null && _pendingRequests.containsKey(reqId)) {
        final completer = _pendingRequests.remove(reqId)!;
        if (decoded.containsKey('error') && decoded['error'] != null) {
          final err = decoded['error'];
          final errMsg = (err is Map) ? (err['message'] ?? 'RPC Error') : err.toString();
          completer.completeError(Exception(errMsg));
        } else {
          completer.complete(decoded);
        }
        return;
      }

      // Check if message is a broadcast event
      if (decoded.containsKey('event')) {
        _eventController.add(decoded);
      }
    } catch (e) {
      // Ignored malformed frame
    }
  }

  void _onError(dynamic error) {
    final closeCode = _channel?.closeCode;
    final closeReason = _channel?.closeReason ?? 'Kicked by administrator';
    _cleanupConnection();

    if (closeCode == 4001) {
      _reconnectTimer?.cancel();
      _eventController.add({
        'event': 'kick_disconnect',
        'close_code': 4001,
        'reason': closeReason,
      });
      return;
    }

    _scheduleReconnect();
  }

  void _onDisconnected() {
    final closeCode = _channel?.closeCode;
    final closeReason = _channel?.closeReason ?? 'Kicked by administrator';
    _cleanupConnection();

    if (closeCode == 4001) {
      _reconnectTimer?.cancel();
      _eventController.add({
        'event': 'kick_disconnect',
        'close_code': 4001,
        'reason': closeReason,
      });
      return;
    }

    _scheduleReconnect();
  }

  void _cleanupConnection() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _subscription?.cancel();
    _subscription = null;
    _channel?.sink.close();
    _channel = null;
    _updateStatus(WsConnectionStatus.disconnected);

    if (_connectingCompleter != null && !_connectingCompleter!.isCompleted) {
      _connectingCompleter!.completeError(Exception('WebSocket connection closed'));
    }
    _connectingCompleter = null;

    // Reject all pending requests
    for (final completer in _pendingRequests.values) {
      if (!completer.isCompleted) {
        completer.completeError(Exception('WebSocket connection closed'));
      }
    }
    _pendingRequests.clear();
  }

  void _scheduleReconnect() {
    if (_isDisposed) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 3), () {
      if (_status == WsConnectionStatus.disconnected) {
        connect();
      }
    });
  }

  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 25), (_) {
      if (_status == WsConnectionStatus.connected ||
          _status == WsConnectionStatus.authenticated) {
        sendRequest('ping', {}).catchError((_) => <String, dynamic>{});
      }
    });
  }

  void _updateStatus(WsConnectionStatus newStatus) {
    if (_status != newStatus) {
      _status = newStatus;
      if (!_statusController.isClosed) {
        _statusController.add(_status);
      }
    }
  }

  /// Sends a generic JSON-RPC request and awaits the matched response.
  Future<Map<String, dynamic>> sendRequest(
    String action,
    Map<String, dynamic> params,
  ) {
    if (_channel == null) {
      return Future.error(Exception('WebSocket is not connected'));
    }

    final id = 'req_${++_requestIdCounter}_${DateTime.now().millisecondsSinceEpoch}';
    final completer = Completer<Map<String, dynamic>>();
    _pendingRequests[id] = completer;

    final envelope = <String, dynamic>{
      'id': id,
      'action': action,
      'params': params,
      ...params, // Include top-level fields for backend flexibility
    };

    try {
      _channel!.sink.add(json.encode(envelope));
    } catch (e) {
      _pendingRequests.remove(id);
      return Future.error(e);
    }

    // 10 second timeout for responses
    return completer.future.timeout(
      const Duration(seconds: 10),
      onTimeout: () {
        _pendingRequests.remove(id);
        throw TimeoutException('Request $action timed out');
      },
    );
  }

  // --- RPC Methods ---

  Future<Map<String, dynamic>> login(
    String username,
    String password, {
    String clientVersion = '1.0.0',
  }) async {
    final res = await sendRequest('login', {
      'username': username,
      'password': password,
      'client_version': clientVersion,
    });
    _sessionToken = res['token']?.toString() ??
        (res['data'] is Map ? res['data']['token']?.toString() : null) ??
        (res['result'] is Map ? res['result']['token']?.toString() : null);
    _updateStatus(WsConnectionStatus.authenticated);
    return res;
  }

  Future<Map<String, dynamic>> register(
    String username,
    String password, {
    String clientVersion = '1.0.0',
  }) async {
    final res = await sendRequest('register', {
      'username': username,
      'password': password,
      'client_version': clientVersion,
    });
    _sessionToken = res['token']?.toString() ??
        (res['data'] is Map ? res['data']['token']?.toString() : null) ??
        (res['result'] is Map ? res['result']['token']?.toString() : null);
    _updateStatus(WsConnectionStatus.authenticated);
    return res;
  }

  Future<Map<String, dynamic>> authenticate(String token) async {
    final res = await sendRequest('auth', {
      'token': token,
      'client_version': '1.0.0',
    });
    _sessionToken = token;
    _updateStatus(WsConnectionStatus.authenticated);
    return res;
  }

  Future<Map<String, dynamic>> getChannels() {
    return sendRequest('get_channels', {});
  }

  Future<Map<String, dynamic>> createChannel({
    required String name,
    required String type,
    String category = 'General',
    int position = 0,
    int bitrate = 48000,
    int userLimit = 15,
  }) {
    return sendRequest('create_channel', {
      'name': name,
      'type': type,
      'category': category,
      'position': position,
      'bitrate': bitrate,
      'user_limit': userLimit,
    });
  }

  Future<Map<String, dynamic>> deleteChannel(int channelId) {
    return sendRequest('delete_channel', {'channel_id': channelId});
  }

  Future<Map<String, dynamic>> sendChat(int channelId, String content) {
    return sendRequest('send_chat', {
      'channel_id': channelId,
      'content': content,
    });
  }

  Future<Map<String, dynamic>> getChatHistory(
    int channelId, {
    int beforeId = 0,
    int limit = 50,
  }) {
    return sendRequest('get_chat_history', {
      'channel_id': channelId,
      'before_id': beforeId,
      'limit': limit,
    });
  }

  Future<Map<String, dynamic>> joinVoice(
    int channelId, {
    bool selfMuted = false,
    bool selfDeafened = false,
  }) {
    return sendRequest('join_voice', {
      'channel_id': channelId,
      'self_muted': selfMuted,
      'self_deafened': selfDeafened,
    });
  }

  Future<Map<String, dynamic>> leaveVoice() {
    return sendRequest('leave_voice', {});
  }

  Future<Map<String, dynamic>> setVoiceState({
    required bool selfMuted,
    required bool selfDeafened,
    required bool isSpeaking,
  }) {
    return sendRequest('set_voice_state', {
      'self_muted': selfMuted,
      'self_deafened': selfDeafened,
      'is_speaking': isSpeaking,
    });
  }

  Future<Map<String, dynamic>> getRoster() {
    return sendRequest('get_roster', {});
  }

  Future<Map<String, dynamic>> moveMember(int targetUserId, int toChannelId) {
    return sendRequest('move_member', {
      'target_user_id': targetUserId,
      'to_channel_id': toChannelId,
    });
  }

  Future<Map<String, dynamic>> setServerMute(int targetUserId, bool muted) {
    return sendRequest('set_server_mute', {
      'target_user_id': targetUserId,
      'muted': muted,
    });
  }

  Future<Map<String, dynamic>> setServerDeafen(int targetUserId, bool deafened) {
    return sendRequest('set_server_deafen', {
      'target_user_id': targetUserId,
      'deafened': deafened,
    });
  }

  Future<Map<String, dynamic>> kickMember(int targetUserId, {String reason = ''}) {
    return sendRequest('kick_member', {
      'target_user_id': targetUserId,
      'reason': reason,
    });
  }

  void disconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _cleanupConnection();
  }

  void dispose() {
    _isDisposed = true;
    disconnect();
    _statusController.close();
    _eventController.close();
  }
}
