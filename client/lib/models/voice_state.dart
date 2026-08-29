/// Voice state representation of a user participating in a voice channel.
class VoiceState {
  final int userId;
  final String username;
  final int? channelId;
  final bool isSpeaking;
  final bool selfMuted;
  final bool selfDeafened;
  final bool serverMuted;
  final bool serverDeafened;
  final int energyLevel; // 0..15

  const VoiceState({
    required this.userId,
    this.username = '',
    this.channelId,
    this.isSpeaking = false,
    this.selfMuted = false,
    this.selfDeafened = false,
    this.serverMuted = false,
    this.serverDeafened = false,
    this.energyLevel = 0,
  });

  /// Effective mute status (local or server-enforced).
  bool get isMuted => selfMuted || serverMuted || isDeafened;

  /// Effective deafen status (local or server-enforced).
  bool get isDeafened => selfDeafened || serverDeafened;

  /// Whether the user can transmit audio.
  bool get canSpeak => !isMuted;

  factory VoiceState.fromJson(Map<String, dynamic> json) {
    int? chId;
    if (json['channel_id'] is int) {
      chId = json['channel_id'] as int;
    }

    return VoiceState(
      userId: json['user_id'] is int
          ? json['user_id'] as int
          : (json['id'] is int ? json['id'] as int : 0),
      username: (json['username'] as String?) ?? '',
      channelId: chId,
      isSpeaking: json['is_speaking'] == true,
      selfMuted: json['self_muted'] == true,
      selfDeafened: json['self_deafened'] == true,
      serverMuted: json['server_muted'] == true,
      serverDeafened: json['server_deafened'] == true,
      energyLevel: (json['energy_level'] is int) ? json['energy_level'] as int : 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'user_id': userId,
      'username': username,
      'channel_id': channelId,
      'is_speaking': isSpeaking,
      'self_muted': selfMuted,
      'self_deafened': selfDeafened,
      'server_muted': serverMuted,
      'server_deafened': serverDeafened,
      'energy_level': energyLevel,
    };
  }

  VoiceState copyWith({
    int? userId,
    String? username,
    int? channelId,
    bool? isSpeaking,
    bool? selfMuted,
    bool? selfDeafened,
    bool? serverMuted,
    bool? serverDeafened,
    int? energyLevel,
  }) {
    return VoiceState(
      userId: userId ?? this.userId,
      username: username ?? this.username,
      channelId: channelId ?? this.channelId,
      isSpeaking: isSpeaking ?? this.isSpeaking,
      selfMuted: selfMuted ?? this.selfMuted,
      selfDeafened: selfDeafened ?? this.selfDeafened,
      serverMuted: serverMuted ?? this.serverMuted,
      serverDeafened: serverDeafened ?? this.serverDeafened,
      energyLevel: energyLevel ?? this.energyLevel,
    );
  }
}
