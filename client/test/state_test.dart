import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:low_latency_voice_app/core/constants.dart';
import 'package:low_latency_voice_app/models/audio_device.dart';
import 'package:low_latency_voice_app/models/role.dart';
import 'package:low_latency_voice_app/models/voice_state.dart';
import 'package:low_latency_voice_app/services/audio_engine.dart';
import 'package:low_latency_voice_app/services/ptt_service.dart';
import 'package:low_latency_voice_app/services/vad_service.dart';
import 'package:low_latency_voice_app/services/voice_client.dart';
import 'package:low_latency_voice_app/services/websocket_service.dart';
import 'package:low_latency_voice_app/state/auth_notifier.dart';
import 'package:low_latency_voice_app/state/channels_notifier.dart';
import 'package:low_latency_voice_app/state/chat_notifier.dart';
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
}
