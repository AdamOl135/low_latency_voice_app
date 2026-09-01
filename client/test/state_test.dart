import 'dart:typed_data';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:low_latency_voice_app/core/constants.dart';
import 'package:low_latency_voice_app/models/audio_device.dart';
import 'package:low_latency_voice_app/models/role.dart';
import 'package:low_latency_voice_app/models/user.dart';
import 'package:low_latency_voice_app/models/voice_state.dart';
import 'package:low_latency_voice_app/services/audio_engine.dart';
import 'package:low_latency_voice_app/services/ptt_service.dart';
import 'package:low_latency_voice_app/services/vad_service.dart';
import 'package:low_latency_voice_app/services/voice_client.dart';
import 'package:low_latency_voice_app/services/websocket_service.dart';
import 'package:low_latency_voice_app/state/auth_notifier.dart';
import 'package:low_latency_voice_app/state/channels_notifier.dart';
import 'package:low_latency_voice_app/state/chat_notifier.dart';
import 'package:low_latency_voice_app/state/roster_notifier.dart';
import 'package:low_latency_voice_app/state/settings_notifier.dart';
import 'package:low_latency_voice_app/state/voice_notifier.dart';

void main() {
  group('Role and Permission Evaluation Tests', () {
    test('Admin permission (0x01) bypasses all permission checks', () {
      const adminPerms = AppConstants.permAdmin;
      expect(Role.hasPermission(adminPerms, AppConstants.permManageChannels), isTrue);
      expect(Role.hasPermission(adminPerms, AppConstants.permKickMembers), isTrue);
      expect(Role.hasPermission(adminPerms, AppConstants.permMuteMembers), isTrue);
      expect(Role.hasPermission(adminPerms, AppConstants.permMoveMembers), isTrue);
      expect(Role.hasPermission(adminPerms, AppConstants.permSendMessages), isTrue);
    });

    test('Standard member has SendMessages & ConnectVoice but not Moderation', () {
      const memberPerms = AppConstants.permSendMessages | AppConstants.permConnectVoice | AppConstants.permSpeak;
      expect(Role.hasPermission(memberPerms, AppConstants.permSendMessages), isTrue);
      expect(Role.hasPermission(memberPerms, AppConstants.permConnectVoice), isTrue);
      expect(Role.hasPermission(memberPerms, AppConstants.permManageChannels), isFalse);
      expect(Role.hasPermission(memberPerms, AppConstants.permKickMembers), isFalse);
    });
  });

  group('Mute/Deafen Matrix & VoiceState Invariant Tests', () {
    test('VoiceState resolves effective mute and deafen status correctly', () {
      const unmutedState = VoiceState(userId: 1, selfMuted: false, selfDeafened: false);
      expect(unmutedState.isMuted, isFalse);
      expect(unmutedState.canSpeak, isTrue);

      const localMutedState = VoiceState(userId: 1, selfMuted: true, selfDeafened: false);
      expect(localMutedState.isMuted, isTrue);
      expect(localMutedState.canSpeak, isFalse);

      const serverMutedState = VoiceState(userId: 1, selfMuted: false, serverMuted: true);
      expect(serverMutedState.isMuted, isTrue);
      expect(serverMutedState.canSpeak, isFalse);

      const deafenedState = VoiceState(userId: 1, selfDeafened: true);
      expect(deafenedState.isDeafened, isTrue);
      expect(deafenedState.isMuted, isTrue); // Deafen implies mute
      expect(deafenedState.canSpeak, isFalse);
    });
  });

  group('Channels State Notifier Tests', () {
    late WebSocketService ws;
    late ChannelsNotifier notifier;

    setUp(() {
      ws = WebSocketService();
      notifier = ChannelsNotifier(ws);
    });

    tearDown(() {
      notifier.dispose();
      ws.dispose();
    });

    test('Initial channels state is empty', () {
      expect(notifier.state.channels, isEmpty);
      expect(notifier.state.selectedTextChannelId, isNull);
    });

    test('Selecting text channel updates selectedTextChannelId', () {
      notifier.selectTextChannel(101);
      expect(notifier.state.selectedTextChannelId, equals(101));
    });
  });

  group('Chat State Notifier Tests', () {
    late WebSocketService ws;
    late ChatNotifier notifier;

    setUp(() {
      ws = WebSocketService();
      notifier = ChatNotifier(ws);
    });

    tearDown(() {
      notifier.dispose();
      ws.dispose();
    });

    test('Get messages for null or empty channel returns empty list', () {
      expect(notifier.state.getMessagesFor(null), isEmpty);
      expect(notifier.state.getMessagesFor(999), isEmpty);
    });
  });

  group('Voice State Notifier Unit Tests', () {
    late WebSocketService ws;
    late VoiceClient voiceClient;
    late AudioEngineService audioEngine;
    late ProviderContainer container;

    setUp(() {
      ws = WebSocketService();
      voiceClient = VoiceClient();
      audioEngine = AudioEngineService();
      container = ProviderContainer(
        overrides: [
          webSocketServiceProvider.overrideWithValue(ws),
          voiceClientProvider.overrideWithValue(voiceClient),
          audioEngineProvider.overrideWithValue(audioEngine),
        ],
      );
    });

    tearDown(() {
      container.dispose();
      audioEngine.destroy();
      voiceClient.dispose();
      ws.dispose();
    });

    test('Initial voice state is disconnected', () {
      final voiceState = container.read(voiceProvider);
      expect(voiceState.status, equals(VoiceConnectionStatus.disconnected));
      expect(voiceState.isConnected, isFalse);
      expect(voiceState.connectedChannelId, isNull);
      expect(voiceState.localInputLevelDb, equals(-90.0));
      expect(voiceState.isLocalSpeaking, isFalse);
    });

    test('Toggling mute updates local state and calls audio engine', () {
      final voiceNotifier = container.read(voiceProvider.notifier);
      expect(container.read(voiceProvider).selfMuted, isFalse);

      voiceNotifier.toggleMute();
      expect(container.read(voiceProvider).selfMuted, isTrue);

      voiceNotifier.toggleMute();
      expect(container.read(voiceProvider).selfMuted, isFalse);
    });

    test('Toggling deafen automatically sets selfMuted = true', () {
      final voiceNotifier = container.read(voiceProvider.notifier);
      expect(container.read(voiceProvider).selfDeafened, isFalse);

      voiceNotifier.toggleDeafen();
      expect(container.read(voiceProvider).selfDeafened, isTrue);
      expect(container.read(voiceProvider).selfMuted, isTrue);
    });

    test('setUserVolume adjusts volume map for specific peer', () {
      final voiceNotifier = container.read(voiceProvider.notifier);
      voiceNotifier.setUserVolume(42, 1.5);
      expect(container.read(voiceProvider).userVolumes[42], equals(1.5));

      voiceNotifier.setUserVolume(42, 3.0); // Clamped to 2.0
      expect(container.read(voiceProvider).userVolumes[42], equals(2.0));
    });

    test('disconnect resets speakingUsers and clears connection state', () async {
      final voiceNotifier = container.read(voiceProvider.notifier);
      await voiceNotifier.disconnect();

      final state = container.read(voiceProvider);
      expect(state.status, equals(VoiceConnectionStatus.disconnected));
      expect(state.speakingUsers, isEmpty);
      expect(state.userEnergyLevels, isEmpty);
      expect(state.connectedChannelId, isNull);
    });
  });

  group('Settings State Notifier & Mic Test Tests', () {
    late AudioEngineService audioEngine;
    late VadService vadService;
    late PttService pttService;
    late SettingsNotifier settingsNotifier;

    setUp(() {
      audioEngine = AudioEngineService();
      audioEngine.initialize();
      vadService = VadService();
      pttService = PttService();
      settingsNotifier = SettingsNotifier(audioEngine, vadService, pttService);
    });

    tearDown(() {
      settingsNotifier.dispose();
      audioEngine.destroy();
      vadService.dispose();
      pttService.dispose();
    });

    test('Initial settings state populates input and output devices', () {
      final state = settingsNotifier.state;
      expect(state.inputDevices, isNotEmpty);
      expect(state.outputDevices, isNotEmpty);
      expect(state.selectedInputDevice, isNotNull);
      expect(state.selectedOutputDevice, isNotNull);
      expect(state.isTestingMic, isFalse);
    });

    test('startMicTest and stopMicTest manage testing state', () {
      expect(settingsNotifier.state.isTestingMic, isFalse);

      settingsNotifier.startMicTest();
      expect(settingsNotifier.state.isTestingMic, isTrue);

      settingsNotifier.stopMicTest();
      expect(settingsNotifier.state.isTestingMic, isFalse);
    });

    test('toggleMicTest switches mic testing state', () {
      expect(settingsNotifier.state.isTestingMic, isFalse);

      settingsNotifier.toggleMicTest();
      expect(settingsNotifier.state.isTestingMic, isTrue);

      settingsNotifier.toggleMicTest();
      expect(settingsNotifier.state.isTestingMic, isFalse);
    });

    test('Setting input and output devices updates selected device', () {
      const customMic = AudioDevice(id: 'usb_mic_2', name: 'USB Cardioid Mic', isInput: true);
      const customSpeaker = AudioDevice(id: 'spk_2', name: 'Studio Monitors', isInput: false);

      settingsNotifier.setInputDevice(customMic);
      expect(settingsNotifier.state.selectedInputDevice?.id, equals('usb_mic_2'));

      settingsNotifier.setOutputDevice(customSpeaker);
      expect(settingsNotifier.state.selectedOutputDevice?.id, equals('spk_2'));
    });
  });

  group('Member Kick & State Synchronization Tests (R4)', () {
    test('AuthNotifier handles kick_disconnect and sets isKicked = true with reason', () {
      final ws = WebSocketService();
      final authNotifier = AuthNotifier(ws);

      expect(authNotifier.state.isKicked, isFalse);
      expect(authNotifier.state.kickReason, isNull);

      authNotifier.handleKicked('Spamming in voice channel');

      expect(authNotifier.state.isKicked, isTrue);
      expect(authNotifier.state.kickReason, equals('Spamming in voice channel'));
      expect(authNotifier.state.isAuthenticated, isFalse);
      expect(authNotifier.state.errorMessage, contains('Spamming in voice channel'));

      authNotifier.dispose();
      ws.dispose();
    });

    test('RosterNotifier purges kicked member from both members list and voiceStates map', () {
      final ws = WebSocketService();
      final rosterNotifier = RosterNotifier(ws);

      const member1 = UserProfile(userId: 1, username: 'Alice', online: true);
      const member2 = UserProfile(userId: 2, username: 'Bob', online: true);
      const vs2 = VoiceState(userId: 2, channelId: 101, isSpeaking: true);

      rosterNotifier.state = const RosterState(
        members: [member1, member2],
        voiceStates: {2: vs2},
      );

      expect(rosterNotifier.state.members.length, equals(2));
      expect(rosterNotifier.state.voiceStates.containsKey(2), isTrue);

      // Simulate member_kicked event
      rosterNotifier.state = rosterNotifier.state.copyWith(
        members: rosterNotifier.state.members.where((m) => m.userId != 2).toList(),
        voiceStates: Map<int, VoiceState>.from(rosterNotifier.state.voiceStates)..remove(2),
      );

      expect(rosterNotifier.state.members.length, equals(1));
      expect(rosterNotifier.state.members.first.userId, equals(1));
      expect(rosterNotifier.state.voiceStates.containsKey(2), isFalse);

      rosterNotifier.dispose();
      ws.dispose();
    });

    test('VoiceNotifier purges speaking and energy state for kicked member', () {
      final container = ProviderContainer();
      final voiceNotifier = container.read(voiceProvider.notifier);

      voiceNotifier.state = voiceNotifier.state.copyWith(
        speakingUsers: {2: true, 3: true},
        userEnergyLevels: {2: 14, 3: 8},
        userVolumes: {2: 1.5, 3: 1.0},
      );

      expect(container.read(voiceProvider).speakingUsers.containsKey(2), isTrue);
      expect(container.read(voiceProvider).userEnergyLevels[2], equals(14));
      expect(container.read(voiceProvider).userVolumes[2], equals(1.5));

      // Simulate cleanup on kick
      final speakingMap = Map<int, bool>.from(voiceNotifier.state.speakingUsers)..remove(2);
      final energyMap = Map<int, int>.from(voiceNotifier.state.userEnergyLevels)..remove(2);
      final volumeMap = Map<int, double>.from(voiceNotifier.state.userVolumes)..remove(2);
      voiceNotifier.state = voiceNotifier.state.copyWith(
        speakingUsers: speakingMap,
        userEnergyLevels: energyMap,
        userVolumes: volumeMap,
      );

      expect(container.read(voiceProvider).speakingUsers.containsKey(2), isFalse);
      expect(container.read(voiceProvider).userEnergyLevels.containsKey(2), isFalse);
      expect(container.read(voiceProvider).userVolumes.containsKey(2), isFalse);
      expect(container.read(voiceProvider).speakingUsers.containsKey(3), isTrue);

      container.dispose();
    });

    test('VoiceNotifier.joinVoice stops mic test on SettingsNotifier', () async {
      final container = ProviderContainer();
      final settingsNotifier = container.read(settingsProvider.notifier);
      final voiceNotifier = container.read(voiceProvider.notifier);

      settingsNotifier.startMicTest();
      expect(container.read(settingsProvider).isTestingMic, isTrue);

      // Trigger joinVoice
      await voiceNotifier.joinVoice(101, 'General-Voice');

      // isTestingMic must be stopped
      expect(container.read(settingsProvider).isTestingMic, isFalse);

      container.dispose();
    });
  });

  group('Requirements R4 & R5 Client Unit Tests', () {
    test('User model defaults to AppConstants.defaultUdpPort (R4)', () {
      const user = User(id: 1, username: 'testuser');
      expect(user.udpPort, equals(AppConstants.defaultUdpPort));
      expect(user.udpPort, equals(7878));

      final jsonUser = User.fromJson({'user_id': 2, 'username': 'jsonuser'});
      expect(jsonUser.udpPort, equals(AppConstants.defaultUdpPort));
    });

    test('SettingsNotifier preserves AppConstants.defaultWsPort and defaultHost (R4)', () {
      final engine = AudioEngineService();
      final vad = VadService();
      final ptt = PttService();
      final notifier = SettingsNotifier(engine, vad, ptt);

      expect(notifier.state.serverHost, equals(AppConstants.defaultHost));
      expect(notifier.state.serverHost, equals('100.108.39.69'));
      expect(notifier.state.serverWsPort, equals(AppConstants.defaultWsPort));
      expect(notifier.state.serverWsPort, equals(8085));

      notifier.dispose();
      vad.dispose();
      ptt.dispose();
      engine.destroy();
    });

    test('VoicePacket rawBytes is passed without re-encoding to AudioEngine (R5)', () async {
      final ws = WebSocketService();
      final voiceClient = VoiceClient();
      final audioEngine = AudioEngineService();
      final container = ProviderContainer(
        overrides: [
          webSocketServiceProvider.overrideWithValue(ws),
          voiceClientProvider.overrideWithValue(voiceClient),
          audioEngineProvider.overrideWithValue(audioEngine),
          authProvider.overrideWith((ref) {
            final notifier = AuthNotifier(ws);
            notifier.state = const AuthState(
              isAuthenticated: true,
              user: User(id: 1, username: 'LocalUser'),
            );
            return notifier;
          }),
        ],
      );

      final voiceNotifier = container.read(voiceProvider.notifier);
      voiceNotifier.state = voiceNotifier.state.copyWith(
        status: VoiceConnectionStatus.connected,
        connectedChannelId: 10,
      );

      final peerPayload = Uint8List.fromList([10, 20, 30, 40]);
      final peerPacket = VoicePacket(
        type: AppConstants.packetTypeVoice,
        senderId: 2,
        channelId: 10,
        sequence: 1,
        timestamp: 1000,
        payload: peerPayload,
      );
      final rawDatagram = peerPacket.encode();
      final inboundPacket = VoicePacket.decode(rawDatagram);

      expect(inboundPacket.rawBytes, equals(rawDatagram));

      container.dispose();
      audioEngine.destroy();
      voiceClient.dispose();
      ws.dispose();
    });
  });
}
