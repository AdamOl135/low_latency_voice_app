import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/constants.dart';
import '../services/audio_engine.dart';
import '../services/voice_client.dart';
import '../services/websocket_service.dart';
import 'auth_notifier.dart';
import 'channels_notifier.dart';
import 'settings_notifier.dart';

enum VoiceConnectionStatus { disconnected, connecting, connected }

class VoiceStateModel {
  final VoiceConnectionStatus status;
  final int? connectedChannelId;
  final String? connectedChannelName;
  final bool selfMuted;
  final bool selfDeafened;
  final bool serverMuted;
  final bool serverDeafened;
  final double pingMs;
  final double localInputLevelDb;
  final bool isLocalSpeaking;
  final Map<int, bool> speakingUsers; // userId -> isSpeaking
  final Map<int, int> userEnergyLevels; // userId -> energyLevel (0..15)
  final Map<int, double> userVolumes; // userId -> volumeMultiplier (0.0..2.0)
  final String? errorMessage;

  const VoiceStateModel({
    this.status = VoiceConnectionStatus.disconnected,
    this.connectedChannelId,
    this.connectedChannelName,
    this.selfMuted = false,
    this.selfDeafened = false,
    this.serverMuted = false,
    this.serverDeafened = false,
    this.pingMs = 0.0,
    this.localInputLevelDb = -90.0,
    this.isLocalSpeaking = false,
    this.speakingUsers = const {},
    this.userEnergyLevels = const {},
    this.userVolumes = const {},
    this.errorMessage,
  });

  bool get isConnected => status == VoiceConnectionStatus.connected;
  bool get isMuted => selfMuted || serverMuted || isDeafened;
  bool get isDeafened => selfDeafened || serverDeafened;

  VoiceStateModel copyWith({
    VoiceConnectionStatus? status,
    int? connectedChannelId,
    String? connectedChannelName,
    bool? selfMuted,
    bool? selfDeafened,
    bool? serverMuted,
    bool? serverDeafened,
    double? pingMs,
    double? localInputLevelDb,
    bool? isLocalSpeaking,
    Map<int, bool>? speakingUsers,
    Map<int, int>? userEnergyLevels,
    Map<int, double>? userVolumes,
    String? errorMessage,
  }) {
    return VoiceStateModel(
      status: status ?? this.status,
      connectedChannelId: connectedChannelId ?? this.connectedChannelId,
      connectedChannelName: connectedChannelName ?? this.connectedChannelName,
      selfMuted: selfMuted ?? this.selfMuted,
      selfDeafened: selfDeafened ?? this.selfDeafened,
      serverMuted: serverMuted ?? this.serverMuted,
      serverDeafened: serverDeafened ?? this.serverDeafened,
      pingMs: pingMs ?? this.pingMs,
      localInputLevelDb: localInputLevelDb ?? this.localInputLevelDb,
      isLocalSpeaking: isLocalSpeaking ?? this.isLocalSpeaking,
      speakingUsers: speakingUsers ?? this.speakingUsers,
      userEnergyLevels: userEnergyLevels ?? this.userEnergyLevels,
      userVolumes: userVolumes ?? this.userVolumes,
      errorMessage: errorMessage,
    );
  }
}

final voiceClientProvider = Provider<VoiceClient>((ref) {
  final client = VoiceClient();
  ref.onDispose(() => client.dispose());
  return client;
});

final audioEngineProvider = Provider<AudioEngineService>((ref) {
  final engine = AudioEngineService();
  engine.initialize();
  ref.onDispose(() => engine.destroy());
  return engine;
});

class VoiceNotifier extends StateNotifier<VoiceStateModel> {
  final WebSocketService _ws;
  final VoiceClient _voiceClient;
  final AudioEngineService _audioEngine;
  final Ref _ref;

  StreamSubscription? _wsEventsSub;
  StreamSubscription? _speakingSub;
  StreamSubscription? _rttSub;
  StreamSubscription? _captureSub;
  StreamSubscription? _inboundPacketSub;

  VoiceNotifier(this._ws, this._voiceClient, this._audioEngine, this._ref)
      : super(const VoiceStateModel()) {
    _initSubscriptions();
  }

  void _initSubscriptions() {
    // Fast-path in-band VAD indicators from peers (<30ms)
    _speakingSub = _voiceClient.speakingStateStream.listen((event) {
      final currentUserId = _ref.read(authProvider).user?.id;
      if (event.userId == currentUserId || event.userId == 0) return;

      final speakingMap = Map<int, bool>.from(state.speakingUsers);
      final energyMap = Map<int, int>.from(state.userEnergyLevels);

      speakingMap[event.userId] = event.isSpeaking;
      energyMap[event.userId] = event.energyLevel;

      state = state.copyWith(
        speakingUsers: speakingMap,
        userEnergyLevels: energyMap,
      );
    });

    // Inbound peer audio packet feeding directly to audio engine mixer
    _inboundPacketSub = _voiceClient.inboundPacketStream.listen((packet) {
      final currentUserId = _ref.read(authProvider).user?.id;
      if (packet.senderId == currentUserId || packet.senderId == 0) return;

      if (!state.isDeafened) {
        _audioEngine.feedInboundPacket(packet.rawBytes ?? Uint8List(0));
      }
    });

    // RTT latency telemetry
    _rttSub = _voiceClient.rttStream.listen((rtt) {
      state = state.copyWith(pingMs: rtt);
    });

    // Control-plane WebSocket events
    _wsEventsSub = _ws.eventStream.listen((event) {
      final eventType = event['event']?.toString();
      final data = (event['data'] is Map) ? event['data'] as Map<String, dynamic> : event;

      final currentUserId = _ref.read(authProvider).user?.id;

      if (eventType == 'voice_state_update') {
        final userId = data['user_id'] as int?;
        if (userId != null) {
          if (userId == currentUserId) {
            final serverMuted = data['server_muted'] == true;
            final serverDeafened = data['server_deafened'] == true;
            final channelId = data['channel_id'] as int?;

            state = state.copyWith(
              serverMuted: serverMuted,
              serverDeafened: serverDeafened,
            );

            if (channelId == null && state.isConnected) {
              disconnect();
            }
          } else {
            // Control plane fallback for peer speaking state
            final channelId = data['channel_id'];
            if (channelId == null || channelId == 0) {
              // User left voice channel
              final speakingMap = Map<int, bool>.from(state.speakingUsers)..remove(userId);
              final energyMap = Map<int, int>.from(state.userEnergyLevels)..remove(userId);
              state = state.copyWith(
                speakingUsers: speakingMap,
                userEnergyLevels: energyMap,
              );
            } else if (data.containsKey('is_speaking') || data.containsKey('speaking')) {
              final isSpk = data['is_speaking'] == true || data['speaking'] == true;
              final energy = (data['energy'] is int)
                  ? data['energy'] as int
                  : ((data['energy_level'] is int) ? data['energy_level'] as int : (isSpk ? 10 : 0));
              final speakingMap = Map<int, bool>.from(state.speakingUsers);
              final energyMap = Map<int, int>.from(state.userEnergyLevels);
              speakingMap[userId] = isSpk;
              energyMap[userId] = energy;
              state = state.copyWith(
                speakingUsers: speakingMap,
                userEnergyLevels: energyMap,
              );
            }
          }
        }
      } else if (eventType == 'member_moved') {
        final userId = data['user_id'] as int?;
        final toChannelId = data['to_channel_id'] as int?;
        if (userId == currentUserId && toChannelId != null) {
          // Seamless admin channel move
          _voiceClient.updateChannel(toChannelId);
          _ref.read(channelsProvider.notifier).setConnectedVoiceChannel(toChannelId);
          state = state.copyWith(connectedChannelId: toChannelId);
        }
      } else if (eventType == 'member_kicked') {
        final kickedId = (data['user_id'] is int) ? data['user_id'] as int : null;
        if (kickedId != null) {
          if (kickedId == currentUserId) {
            disconnect();
          } else {
            final speakingMap = Map<int, bool>.from(state.speakingUsers)..remove(kickedId);
            final energyMap = Map<int, int>.from(state.userEnergyLevels)..remove(kickedId);
            final volumeMap = Map<int, double>.from(state.userVolumes)..remove(kickedId);
            state = state.copyWith(
              speakingUsers: speakingMap,
              userEnergyLevels: energyMap,
              userVolumes: volumeMap,
            );
          }
        }
      }
    });
  }

  Future<void> joinVoice(int channelId, String channelName, {String? host}) async {
    if (state.connectedChannelId == channelId && state.isConnected) return;

    final targetHost = (host != null && host.isNotEmpty)
        ? host
        : _ref.read(settingsProvider).serverHost;

    // Ensure mic test is stopped and peer streams are clean
    _ref.read(settingsProvider.notifier).stopMicTest();
    _audioEngine.stopMicTest();
    _audioEngine.clearPeers();

    state = state.copyWith(
      status: VoiceConnectionStatus.connecting,
      connectedChannelId: channelId,
      connectedChannelName: channelName,
      speakingUsers: {},
      userEnergyLevels: {},
      errorMessage: null,
    );

    try {
      final res = await _ws.joinVoice(
        channelId,
        selfMuted: state.selfMuted,
        selfDeafened: state.selfDeafened,
      );

      final data = (res['data'] is Map) ? res['data'] as Map<String, dynamic> : res;
      final udpToken = data['udp_token']?.toString() ?? '';
      final udpPort = data['udp_port'] is int ? data['udp_port'] as int : AppConstants.defaultUdpPort;
      final user = _ref.read(authProvider).user;

      if (user != null) {
        await _voiceClient.connect(
          host: targetHost,
          port: udpPort,
          userId: user.id,
          channelId: channelId,
          udpToken: udpToken,
        );

        _audioEngine.startCapture();
        _audioEngine.startPlayback();

        // Subscribe to captured audio frames and stream over UDP
        _captureSub?.cancel();
        _captureSub = _audioEngine.onAudioCaptured.listen((frame) {
          final isMutedNow = state.isMuted;
          if (!isMutedNow) {
            _voiceClient.sendVoiceFrame(
              opusData: frame.data,
              isSpeaking: frame.isSpeaking,
              energyLevel: frame.energyLevel,
            );
          }

          // Immediately reflect local speaking state and level in UI
          final curUserId = _ref.read(authProvider).user?.id;
          if (curUserId != null) {
            final speakingMap = Map<int, bool>.from(state.speakingUsers);
            final energyMap = Map<int, int>.from(state.userEnergyLevels);
            final activeSpeaking = !isMutedNow && frame.isSpeaking;

            speakingMap[curUserId] = activeSpeaking;
            energyMap[curUserId] = isMutedNow ? 0 : frame.energyLevel;

            state = state.copyWith(
              localInputLevelDb: isMutedNow ? -90.0 : frame.inputLevelDb,
              isLocalSpeaking: activeSpeaking,
              speakingUsers: speakingMap,
              userEnergyLevels: energyMap,
            );
          }
        });

        _ref.read(channelsProvider.notifier).setConnectedVoiceChannel(channelId);

        state = state.copyWith(
          status: VoiceConnectionStatus.connected,
          connectedChannelId: channelId,
          connectedChannelName: channelName,
        );
      }
    } catch (e) {
      state = state.copyWith(
        status: VoiceConnectionStatus.disconnected,
        connectedChannelId: null,
        errorMessage: e.toString(),
      );
    }
  }

  Future<void> disconnect() async {
    try {
      await _ws.leaveVoice();
    } catch (_) {}

    _captureSub?.cancel();
    _captureSub = null;

    await _voiceClient.disconnect();
    _audioEngine.stopCapture();
    _audioEngine.stopPlayback();
    _audioEngine.clearPeers();

    _ref.read(channelsProvider.notifier).setConnectedVoiceChannel(null);

    state = state.copyWith(
      status: VoiceConnectionStatus.disconnected,
      connectedChannelId: null,
      connectedChannelName: null,
      speakingUsers: {},
      userEnergyLevels: {},
      localInputLevelDb: -90.0,
      isLocalSpeaking: false,
      pingMs: 0.0,
    );
  }

  void toggleMute() {
    final nextMuted = !state.selfMuted;
    state = state.copyWith(selfMuted: nextMuted);
    _audioEngine.setLocalMute(nextMuted);

    if (state.isConnected) {
      _ws.setVoiceState(
        selfMuted: nextMuted,
        selfDeafened: state.selfDeafened,
        isSpeaking: false,
      );
    }
  }

  void toggleDeafen() {
    final nextDeafened = !state.selfDeafened;
    final nextMuted = nextDeafened ? true : state.selfMuted; // Deafen auto-mutes

    state = state.copyWith(
      selfDeafened: nextDeafened,
      selfMuted: nextMuted,
    );
    _audioEngine.setLocalDeafen(nextDeafened);
    _audioEngine.setLocalMute(nextMuted);

    if (state.isConnected) {
      _ws.setVoiceState(
        selfMuted: nextMuted,
        selfDeafened: nextDeafened,
        isSpeaking: false,
      );
    }
  }

  void setUserVolume(int userId, double volumeMultiplier) {
    final updated = Map<int, double>.from(state.userVolumes);
    updated[userId] = volumeMultiplier.clamp(0.0, 2.0);
    state = state.copyWith(userVolumes: updated);
    _audioEngine.setUserVolume(userId, volumeMultiplier);
  }

  @override
  void dispose() {
    _captureSub?.cancel();
    _inboundPacketSub?.cancel();
    _wsEventsSub?.cancel();
    _speakingSub?.cancel();
    _rttSub?.cancel();
    super.dispose();
  }
}

final voiceProvider = StateNotifierProvider<VoiceNotifier, VoiceStateModel>((ref) {
  final ws = ref.watch(webSocketServiceProvider);
  final voiceClient = ref.watch(voiceClientProvider);
  final audioEngine = ref.watch(audioEngineProvider);
  return VoiceNotifier(ws, voiceClient, audioEngine, ref);
});
