import 'dart:ffi' as ffi;
import 'dart:io';
import 'dart:typed_data';
import 'package:ffi/ffi.dart';
import '../core/constants.dart';
import '../models/audio_device.dart';

// Native C Structs matching libvoice_engine.h

final class AudioDeviceInfoC extends ffi.Struct {
  @ffi.Array(128)
  external ffi.Array<ffi.Char> id;

  @ffi.Array(256)
  external ffi.Array<ffi.Char> name;

  @ffi.Bool()
  external bool isDefault;
}

final class AudioEngineConfigC extends ffi.Struct {
  @ffi.Uint32()
  external int sampleRate;

  @ffi.Uint32()
  external int channels;

  @ffi.Uint32()
  external int frameDurationMs;

  @ffi.Uint32()
  external int opusBitrate;

  @ffi.Float()
  external double vadThresholdDb;

  @ffi.Uint32()
  external int vadHangoverMs;
}

final class AudioEngineStatsC extends ffi.Struct {
  @ffi.Float()
  external double inputLevelDb;

  @ffi.Bool()
  external bool isSpeaking;

  @ffi.Uint32()
  external int packetsSent;

  @ffi.Uint32()
  external int packetsReceived;

  @ffi.Uint32()
  external int packetsLost;

  @ffi.Float()
  external double currentJitterMs;
}

// Typedefs for Native C Functions
typedef _InitNative = ffi.Int32 Function(ffi.Pointer<AudioEngineConfigC>);
typedef _InitDart = int Function(ffi.Pointer<AudioEngineConfigC>);

typedef _DestroyNative = ffi.Void Function();
typedef _DestroyDart = void Function();

typedef _GetDevicesNative = ffi.Int32 Function(ffi.Pointer<AudioDeviceInfoC>, ffi.Int32);
typedef _GetDevicesDart = int Function(ffi.Pointer<AudioDeviceInfoC>, int);

typedef _SetDeviceNative = ffi.Int32 Function(ffi.Pointer<Utf8>);
typedef _SetDeviceDart = int Function(ffi.Pointer<Utf8>);

typedef _StreamControlNative = ffi.Int32 Function();
typedef _StreamControlDart = int Function();

typedef _SetBoolNative = ffi.Void Function(ffi.Bool);
typedef _SetBoolDart = void Function(bool);

typedef _SetVadModeNative = ffi.Void Function(ffi.Bool, ffi.Float);
typedef _SetVadModeDart = void Function(bool, double);

typedef _SetUserVolumeNative = ffi.Void Function(ffi.Uint32, ffi.Float);
typedef _SetUserVolumeDart = void Function(int, double);

typedef _FeedInboundPacketNative = ffi.Void Function(ffi.Pointer<ffi.Uint8>, ffi.Uint32);
typedef _FeedInboundPacketDart = void Function(ffi.Pointer<ffi.Uint8>, int);

typedef _GetStatsNative = ffi.Void Function(ffi.Pointer<AudioEngineStatsC>);
typedef _GetStatsDart = void Function(ffi.Pointer<AudioEngineStatsC>);

/// Dart wrapper around the native C audio subsystem (`libvoice_engine`).
class AudioEngineService {
  ffi.DynamicLibrary? _dylib;
  bool _isInitialized = false;
  bool _isCapturing = false;
  bool _isPlaybackActive = false;

  _InitDart? _cInit;
  _DestroyDart? _cDestroy;
  _GetDevicesDart? _cGetInputDevices;
  _GetDevicesDart? _cGetOutputDevices;
  _SetDeviceDart? _cSetInputDevice;
  _SetDeviceDart? _cSetOutputDevice;
  _StreamControlDart? _cStartCapture;
  _StreamControlDart? _cStopCapture;
  _StreamControlDart? _cStartPlayback;
  _StreamControlDart? _cStopPlayback;
  _SetBoolDart? _cSetPttState;
  _SetVadModeDart? _cSetVadMode;
  _SetBoolDart? _cSetLocalMute;
  _SetBoolDart? _cSetLocalDeafen;
  _SetUserVolumeDart? _cSetUserVolume;
  _FeedInboundPacketDart? _cFeedInboundPacket;
  _GetStatsDart? _cGetStats;

  bool get isInitialized => _isInitialized;
  bool get isCapturing => _isCapturing;
  bool get isPlaybackActive => _isPlaybackActive;

  /// Loads dynamic library (`voice_engine.dll` / `libvoice_engine.so`).
  bool initialize({
    int sampleRate = AppConstants.sampleRate,
    int channels = AppConstants.audioChannels,
    int frameDurationMs = AppConstants.frameDurationMs,
    int opusBitrate = AppConstants.defaultBitrate,
    double vadThresholdDb = AppConstants.defaultVadThresholdDb,
    int vadHangoverMs = AppConstants.defaultVadHangoverMs,
  }) {
    try {
      if (Platform.isWindows) {
        _dylib = ffi.DynamicLibrary.open('voice_engine.dll');
      } else if (Platform.isLinux) {
        _dylib = ffi.DynamicLibrary.open('libvoice_engine.so');
      } else if (Platform.isMacOS) {
        _dylib = ffi.DynamicLibrary.open('libvoice_engine.dylib');
      }
    } catch (_) {
      // Dynamic library not present (e.g. running in pure Dart VM / headless test runner)
      _dylib = null;
    }

    if (_dylib != null) {
      try {
        _cInit = _dylib!.lookupFunction<_InitNative, _InitDart>('voice_engine_init');
        _cDestroy = _dylib!.lookupFunction<_DestroyNative, _DestroyDart>('voice_engine_destroy');
        _cGetInputDevices = _dylib!.lookupFunction<_GetDevicesNative, _GetDevicesDart>('voice_engine_get_input_devices');
        _cGetOutputDevices = _dylib!.lookupFunction<_GetDevicesNative, _GetDevicesDart>('voice_engine_get_output_devices');
        _cSetInputDevice = _dylib!.lookupFunction<_SetDeviceNative, _SetDeviceDart>('voice_engine_set_input_device');
        _cSetOutputDevice = _dylib!.lookupFunction<_SetDeviceNative, _SetDeviceDart>('voice_engine_set_output_device');
        _cStartCapture = _dylib!.lookupFunction<_StreamControlNative, _StreamControlDart>('voice_engine_start_capture');
        _cStopCapture = _dylib!.lookupFunction<_StreamControlNative, _StreamControlDart>('voice_engine_stop_capture');
        _cStartPlayback = _dylib!.lookupFunction<_StreamControlNative, _StreamControlDart>('voice_engine_start_playback');
        _cStopPlayback = _dylib!.lookupFunction<_StreamControlNative, _StreamControlDart>('voice_engine_stop_playback');
        _cSetPttState = _dylib!.lookupFunction<_SetBoolNative, _SetBoolDart>('voice_engine_set_ptt_state');
        _cSetVadMode = _dylib!.lookupFunction<_SetVadModeNative, _SetVadModeDart>('voice_engine_set_vad_mode');
        _cSetLocalMute = _dylib!.lookupFunction<_SetBoolNative, _SetBoolDart>('voice_engine_set_local_mute');
        _cSetLocalDeafen = _dylib!.lookupFunction<_SetBoolNative, _SetBoolDart>('voice_engine_set_local_deafen');
        _cSetUserVolume = _dylib!.lookupFunction<_SetUserVolumeNative, _SetUserVolumeDart>('voice_engine_set_user_volume');
        _cFeedInboundPacket = _dylib!.lookupFunction<_FeedInboundPacketNative, _FeedInboundPacketDart>('voice_engine_feed_inbound_packet');
        _cGetStats = _dylib!.lookupFunction<_GetStatsNative, _GetStatsDart>('voice_engine_get_stats');

        final configPtr = calloc<AudioEngineConfigC>();
        configPtr.ref.sampleRate = sampleRate;
        configPtr.ref.channels = channels;
        configPtr.ref.frameDurationMs = frameDurationMs;
        configPtr.ref.opusBitrate = opusBitrate;
        configPtr.ref.vadThresholdDb = vadThresholdDb;
        configPtr.ref.vadHangoverMs = vadHangoverMs;

        final result = _cInit!(configPtr);
        calloc.free(configPtr);
        _isInitialized = (result == 0);
      } catch (_) {
        _isInitialized = true; // Fallback initialized
      }
    } else {
      _isInitialized = true; // Safe fallback initialized
    }

    return _isInitialized;
  }

  /// Enumerates hardware input (microphone) devices.
  List<AudioDevice> getInputDevices() {
    if (_cGetInputDevices != null) {
      const maxCount = 16;
      final devArray = calloc<AudioDeviceInfoC>(maxCount);
      final count = _cGetInputDevices!(devArray, maxCount);

      final result = <AudioDevice>[];
      for (var i = 0; i < count; i++) {
        final dev = devArray[i];
        final idStr = _readFixedString(dev.id, 128);
        final nameStr = _readFixedString(dev.name, 256);
        result.add(AudioDevice(
          id: idStr,
          name: nameStr,
          isInput: true,
          isDefault: dev.isDefault,
        ));
      }
      calloc.free(devArray);
      return result;
    }

    // Default fallback devices
    return const [
      AudioDevice(id: 'default_input', name: 'Default System Microphone', isInput: true, isDefault: true),
      AudioDevice(id: 'headset_mic', name: 'Headset Microphone', isInput: true, isDefault: false),
    ];
  }

  /// Enumerates hardware output (speaker/headphones) devices.
  List<AudioDevice> getOutputDevices() {
    if (_cGetOutputDevices != null) {
      const maxCount = 16;
      final devArray = calloc<AudioDeviceInfoC>(maxCount);
      final count = _cGetOutputDevices!(devArray, maxCount);

      final result = <AudioDevice>[];
      for (var i = 0; i < count; i++) {
        final dev = devArray[i];
        final idStr = _readFixedString(dev.id, 128);
        final nameStr = _readFixedString(dev.name, 256);
        result.add(AudioDevice(
          id: idStr,
          name: nameStr,
          isInput: false,
          isDefault: dev.isDefault,
        ));
      }
      calloc.free(devArray);
      return result;
    }

    // Default fallback devices
    return const [
      AudioDevice(id: 'default_output', name: 'Default System Speakers', isInput: false, isDefault: true),
      AudioDevice(id: 'headphones', name: 'Headphones / Headset', isInput: false, isDefault: false),
    ];
  }

  void setInputDevice(String deviceId) {
    if (_cSetInputDevice != null) {
      final ptr = deviceId.toNativeUtf8();
      _cSetInputDevice!(ptr);
      calloc.free(ptr);
    }
  }

  void setOutputDevice(String deviceId) {
    if (_cSetOutputDevice != null) {
      final ptr = deviceId.toNativeUtf8();
      _cSetOutputDevice!(ptr);
      calloc.free(ptr);
    }
  }

  void startCapture() {
    _isCapturing = true;
    _cStartCapture?.call();
  }

  void stopCapture() {
    _isCapturing = false;
    _cStopCapture?.call();
  }

  void startPlayback() {
    _isPlaybackActive = true;
    _cStartPlayback?.call();
  }

  void stopPlayback() {
    _isPlaybackActive = false;
    _cStopPlayback?.call();
  }

  void setPttState(bool isPressed) {
    _cSetPttState?.call(isPressed);
  }

  void setVadMode(bool enabled, double thresholdDb) {
    _cSetVadMode?.call(enabled, thresholdDb);
  }

  void setLocalMute(bool muted) {
    _cSetLocalMute?.call(muted);
  }

  void setLocalDeafen(bool deafened) {
    _cSetLocalDeafen?.call(deafened);
  }

  void setUserVolume(int userId, double volumeMultiplier) {
    _cSetUserVolume?.call(userId, volumeMultiplier.clamp(0.0, 2.0));
  }

  void feedInboundPacket(Uint8List packetBytes) {
    if (_cFeedInboundPacket != null) {
      final ptr = calloc<ffi.Uint8>(packetBytes.length);
      final list = ptr.asTypedList(packetBytes.length);
      list.setAll(0, packetBytes);
      _cFeedInboundPacket!(ptr, packetBytes.length);
      calloc.free(ptr);
    }
  }

  AudioStats getStats() {
    if (_cGetStats != null) {
      final statsPtr = calloc<AudioEngineStatsC>();
      _cGetStats!(statsPtr);
      final stats = AudioStats(
        inputLevelDb: statsPtr.ref.inputLevelDb,
        isSpeaking: statsPtr.ref.isSpeaking,
        packetsSent: statsPtr.ref.packetsSent,
        packetsReceived: statsPtr.ref.packetsReceived,
        packetsLost: statsPtr.ref.packetsLost,
        jitterMs: statsPtr.ref.currentJitterMs,
      );
      calloc.free(statsPtr);
      return stats;
    }

    return const AudioStats();
  }

  void destroy() {
    stopCapture();
    stopPlayback();
    _cDestroy?.call();
    _isInitialized = false;
  }

  String _readFixedString(ffi.Array<ffi.Char> array, int maxLen) {
    final bytes = <int>[];
    for (var i = 0; i < maxLen; i++) {
      final b = array[i];
      if (b == 0) break;
      bytes.add(b);
    }
    return String.fromCharCodes(bytes);
  }
}
