import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';
import '../core/constants.dart';

/// Voice Activity Detection service calculating RMS dBFS with 200ms hangover release timer.
class VadService {
  double _thresholdDb = AppConstants.defaultVadThresholdDb;
  int _hangoverMs = AppConstants.defaultVadHangoverMs;

  bool _isSpeaking = false;
  Timer? _hangoverTimer;
  double _lastEnergyDb = -90.0;
  int _lastEnergyLevel = 0;

  final StreamController<({bool isSpeaking, double energyDb, int energyLevel})> _vadStreamController =
      StreamController<({bool isSpeaking, double energyDb, int energyLevel})>.broadcast();

  Stream<({bool isSpeaking, double energyDb, int energyLevel})> get vadStream =>
      _vadStreamController.stream;

  bool get isSpeaking => _isSpeaking;
  double get thresholdDb => _thresholdDb;
  double get lastEnergyDb => _lastEnergyDb;
  int get lastEnergyLevel => _lastEnergyLevel;

  void setThreshold(double thresholdDb) {
    _thresholdDb = thresholdDb;
  }

  void setHangoverMs(int hangoverMs) {
    _hangoverMs = hangoverMs;
  }

  /// Processes a 16-bit PCM mono audio buffer and updates speaking state.
  bool processPcmFrame(Int16List pcmSamples) {
    if (pcmSamples.isEmpty) return _isSpeaking;

    // 1. Calculate RMS energy
    var sumSquares = 0.0;
    for (var i = 0; i < pcmSamples.length; i++) {
      final sample = pcmSamples[i].toDouble();
      sumSquares += sample * sample;
    }
    final rms = math.sqrt(sumSquares / pcmSamples.length);

    // 2. Convert to dBFS
    if (rms > 0) {
      _lastEnergyDb = 20.0 * (math.log(rms / 32768.0) / math.ln10);
    } else {
      _lastEnergyDb = -90.0;
    }
    if (_lastEnergyDb < -90.0) _lastEnergyDb = -90.0;
    if (_lastEnergyDb > 0.0) _lastEnergyDb = 0.0;

    // 3. Quantize energy level to 0..15
    // Range from -60 dBFS (level 0) to 0 dBFS (level 15)
    final normalized = ((_lastEnergyDb + 60.0) / 60.0).clamp(0.0, 1.0);
    _lastEnergyLevel = (normalized * 15.0).round();

    // 4. Attack and Hangover Hysteresis
    final aboveThreshold = _lastEnergyDb >= _thresholdDb;

    if (aboveThreshold) {
      _hangoverTimer?.cancel();
      _hangoverTimer = null;
      if (!_isSpeaking) {
        _isSpeaking = true;
        _vadStreamController.add((
          isSpeaking: true,
          energyDb: _lastEnergyDb,
          energyLevel: _lastEnergyLevel,
        ));
      }
    } else if (_isSpeaking && _hangoverTimer == null) {
      // Start hangover release timer
      _hangoverTimer = Timer(Duration(milliseconds: _hangoverMs), () {
        _isSpeaking = false;
        _hangoverTimer = null;
        _vadStreamController.add((
          isSpeaking: false,
          energyDb: _lastEnergyDb,
          energyLevel: _lastEnergyLevel,
        ));
      });
    }

    return _isSpeaking;
  }

  /// Utility to compute energy level directly from RMS dBFS value
  static int quantizeEnergyLevel(double dbfs) {
    final clamped = dbfs.clamp(-60.0, 0.0);
    final normalized = (clamped + 60.0) / 60.0;
    return (normalized * 15.0).round();
  }

  void reset() {
    _hangoverTimer?.cancel();
    _hangoverTimer = null;
    _isSpeaking = false;
    _lastEnergyDb = -90.0;
    _lastEnergyLevel = 0;
  }

  void dispose() {
    reset();
    _vadStreamController.close();
  }
}
