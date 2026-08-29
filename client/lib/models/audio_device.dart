/// Represents a physical audio input (microphone) or output (speakers/headphones) device.
class AudioDevice {
  final String id;
  final String name;
  final bool isInput;
  final bool isDefault;

  const AudioDevice({
    required this.id,
    required this.name,
    required this.isInput,
    this.isDefault = false,
  });

  factory AudioDevice.fromJson(Map<String, dynamic> json) {
    return AudioDevice(
      id: (json['id'] as String?) ?? '',
      name: (json['name'] as String?) ?? 'Default Device',
      isInput: json['is_input'] == true,
      isDefault: json['is_default'] == true,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'is_input': isInput,
      'is_default': isDefault,
    };
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is AudioDevice &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;
}

/// Audio diagnostics and network telemetry stats.
class AudioStats {
  final double inputLevelDb;
  final bool isSpeaking;
  final int packetsSent;
  final int packetsReceived;
  final int packetsLost;
  final double rttMs;
  final double jitterMs;

  const AudioStats({
    this.inputLevelDb = -90.0,
    this.isSpeaking = false,
    this.packetsSent = 0,
    this.packetsReceived = 0,
    this.packetsLost = 0,
    this.rttMs = 0.0,
    this.jitterMs = 0.0,
  });

  AudioStats copyWith({
    double? inputLevelDb,
    bool? isSpeaking,
    int? packetsSent,
    int? packetsReceived,
    int? packetsLost,
    double? rttMs,
    double? jitterMs,
  }) {
    return AudioStats(
      inputLevelDb: inputLevelDb ?? this.inputLevelDb,
      isSpeaking: isSpeaking ?? this.isSpeaking,
      packetsSent: packetsSent ?? this.packetsSent,
      packetsReceived: packetsReceived ?? this.packetsReceived,
      packetsLost: packetsLost ?? this.packetsLost,
      rttMs: rttMs ?? this.rttMs,
      jitterMs: jitterMs ?? this.jitterMs,
    );
  }
}
