import 'dart:async';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../core/constants.dart';
import '../models/audio_device.dart';
import '../services/audio_engine.dart';
import '../services/ptt_service.dart';
import '../services/vad_service.dart';
import '../services/websocket_service.dart';
import 'auth_notifier.dart';
import 'voice_notifier.dart';

class SettingsState {
  final List<AudioDevice> inputDevices;
  final List<AudioDevice> outputDevices;
  final AudioDevice? selectedInputDevice;
  final AudioDevice? selectedOutputDevice;
  final InputActivationMode activationMode;
  final double vadThresholdDb;
  final LogicalKeyboardKey pttHotkey;
  final String serverHost;
  final int serverWsPort;
  final int serverUdpPort;
  final bool isTestingMic;
  final double micTestInputLevelDb;
  final bool isMicSpeaking;

  const SettingsState({
    this.inputDevices = const [],
    this.outputDevices = const [],
    this.selectedInputDevice,
    this.selectedOutputDevice,
    this.activationMode = InputActivationMode.voiceActivity,
    this.vadThresholdDb = AppConstants.defaultVadThresholdDb,
    this.pttHotkey = LogicalKeyboardKey.capsLock,
    this.serverHost = AppConstants.defaultHost,
    this.serverWsPort = AppConstants.defaultWsPort,
    this.serverUdpPort = AppConstants.defaultUdpPort,
    this.isTestingMic = false,
    this.micTestInputLevelDb = -90.0,
    this.isMicSpeaking = false,
  });

  SettingsState copyWith({
    List<AudioDevice>? inputDevices,
    List<AudioDevice>? outputDevices,
    AudioDevice? selectedInputDevice,
    AudioDevice? selectedOutputDevice,
    InputActivationMode? activationMode,
    double? vadThresholdDb,
    LogicalKeyboardKey? pttHotkey,
    String? serverHost,
    int? serverWsPort,
    int? serverUdpPort,
    bool? isTestingMic,
    double? micTestInputLevelDb,
    bool? isMicSpeaking,
  }) {
    return SettingsState(
      inputDevices: inputDevices ?? this.inputDevices,
      outputDevices: outputDevices ?? this.outputDevices,
      selectedInputDevice: selectedInputDevice ?? this.selectedInputDevice,
      selectedOutputDevice: selectedOutputDevice ?? this.selectedOutputDevice,
      activationMode: activationMode ?? this.activationMode,
      vadThresholdDb: vadThresholdDb ?? this.vadThresholdDb,
      pttHotkey: pttHotkey ?? this.pttHotkey,
      serverHost: serverHost ?? this.serverHost,
      serverWsPort: serverWsPort ?? this.serverWsPort,
      serverUdpPort: serverUdpPort ?? this.serverUdpPort,
      isTestingMic: isTestingMic ?? this.isTestingMic,
      micTestInputLevelDb: micTestInputLevelDb ?? this.micTestInputLevelDb,
      isMicSpeaking: isMicSpeaking ?? this.isMicSpeaking,
    );
  }
}

final vadServiceProvider = Provider<VadService>((ref) {
  final service = VadService();
  ref.onDispose(() => service.dispose());
  return service;
});

final pttServiceProvider = Provider<PttService>((ref) {
  final service = PttService();
  ref.onDispose(() => service.dispose());
  return service;
});

class SettingsNotifier extends StateNotifier<SettingsState> {
  final AudioEngineService _audioEngine;
  final VadService _vadService;
  final PttService _pttService;
  final WebSocketService? _ws;
  StreamSubscription? _micTestSub;

  SettingsNotifier(this._audioEngine, this._vadService, this._pttService, {WebSocketService? ws})
      : _ws = ws,
        super(const SettingsState()) {
    refreshDevices();
    loadPersistedSettings();
  }

  void refreshDevices() {
    final inputs = _audioEngine.getInputDevices();
    final outputs = _audioEngine.getOutputDevices();

    final defInput = inputs.isNotEmpty ? (inputs.firstWhere((d) => d.isDefault, orElse: () => inputs.first)) : null;
    final defOutput = outputs.isNotEmpty ? (outputs.firstWhere((d) => d.isDefault, orElse: () => outputs.first)) : null;

    state = state.copyWith(
      inputDevices: inputs,
      outputDevices: outputs,
      selectedInputDevice: state.selectedInputDevice ?? defInput,
      selectedOutputDevice: state.selectedOutputDevice ?? defOutput,
    );
  }

  Future<void> loadPersistedSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final host = prefs.getString('server_host') ?? AppConstants.defaultHost;
      final wsPort = prefs.getInt('server_ws_port') ?? AppConstants.defaultWsPort;
      final vadDb = prefs.getDouble('vad_threshold_db') ?? AppConstants.defaultVadThresholdDb;
      final modeStr = prefs.getString('activation_mode') ?? 'vad';

      final parsed = WebSocketService.parseEndpoint(host, wsPort);

      final mode = modeStr == 'ptt' ? InputActivationMode.pushToTalk : InputActivationMode.voiceActivity;
      _vadService.setThreshold(vadDb);
      _pttService.setMode(mode);
      _ws?.configure(host: parsed.host, port: parsed.port);

      state = state.copyWith(
        serverHost: parsed.host,
        serverWsPort: parsed.port,
        vadThresholdDb: vadDb,
        activationMode: mode,
      );
    } catch (_) {}
  }

  Future<void> setServerEndpoint(String host, int wsPort) async {
    final parsed = WebSocketService.parseEndpoint(host, wsPort);
    state = state.copyWith(serverHost: parsed.host, serverWsPort: parsed.port);
    _ws?.configure(host: parsed.host, port: parsed.port);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('server_host', parsed.host);
      await prefs.setInt('server_ws_port', parsed.port);
    } catch (_) {}
  }

  void setInputDevice(AudioDevice device) {
    state = state.copyWith(selectedInputDevice: device);
    _audioEngine.setInputDevice(device.id);
  }

  void setOutputDevice(AudioDevice device) {
    state = state.copyWith(selectedOutputDevice: device);
    _audioEngine.setOutputDevice(device.id);
  }

  void setActivationMode(InputActivationMode mode) async {
    state = state.copyWith(activationMode: mode);
    _pttService.setMode(mode);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('activation_mode', mode == InputActivationMode.pushToTalk ? 'ptt' : 'vad');
  }

  void setVadThreshold(double thresholdDb) async {
    state = state.copyWith(vadThresholdDb: thresholdDb);
    _vadService.setThreshold(thresholdDb);
    _audioEngine.setVadMode(state.activationMode == InputActivationMode.voiceActivity, thresholdDb);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble('vad_threshold_db', thresholdDb);
  }

  void setPttHotkey(LogicalKeyboardKey key) {
    state = state.copyWith(pttHotkey: key);
    _pttService.setHotkey(key);
  }

  void startMicTest() {
    if (state.isTestingMic) return;

    state = state.copyWith(
      isTestingMic: true,
      micTestInputLevelDb: -90.0,
      isMicSpeaking: false,
    );

    _micTestSub?.cancel();
    _micTestSub = _audioEngine.micTestStream.listen((data) {
      if (state.isTestingMic) {
        state = state.copyWith(
          micTestInputLevelDb: data.dbfs,
          isMicSpeaking: data.isSpeaking,
        );
      }
    });

    _audioEngine.startMicTest();
  }

  void stopMicTest() {
    _micTestSub?.cancel();
    _micTestSub = null;
    _audioEngine.stopMicTest();
    _vadService.reset();

    if (mounted && state.isTestingMic) {
      state = state.copyWith(
        isTestingMic: false,
        micTestInputLevelDb: -90.0,
        isMicSpeaking: false,
      );
    }
  }

  void toggleMicTest() {
    if (state.isTestingMic) {
      stopMicTest();
    } else {
      startMicTest();
    }
  }

  @override
  void dispose() {
    stopMicTest();
    super.dispose();
  }
}

final settingsProvider = StateNotifierProvider<SettingsNotifier, SettingsState>((ref) {
  final engine = ref.watch(audioEngineProvider);
  final vad = ref.watch(vadServiceProvider);
  final ptt = ref.watch(pttServiceProvider);
  final ws = ref.watch(webSocketServiceProvider);
  return SettingsNotifier(engine, vad, ptt, ws: ws);
});
