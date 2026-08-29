/// Model representing an authenticated user account and session.
class User {
  final int id;
  final String username;
  final String? token;
  final List<String> roles;
  final int permissions;
  final bool isAdmin;
  final int udpPort;

  const User({
    required this.id,
    required this.username,
    this.token,
    this.roles = const [],
    this.permissions = 0,
    this.isAdmin = false,
    this.udpPort = 7878,
  });

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['user_id'] is int
          ? json['user_id'] as int
          : (json['id'] is int ? json['id'] as int : 0),
      username: (json['username'] as String?) ?? '',
      token: json['token'] as String?,
      roles: (json['roles'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          const [],
      permissions: (json['permissions'] is int)
          ? json['permissions'] as int
          : 0,
      isAdmin: json['is_admin'] == true,
      udpPort: (json['udp_port'] is int) ? json['udp_port'] as int : 7878,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'user_id': id,
      'username': username,
      if (token != null) 'token': token,
      'roles': roles,
      'permissions': permissions,
      'is_admin': isAdmin,
      'udp_port': udpPort,
    };
  }

  User copyWith({
    int? id,
    String? username,
    String? token,
    List<String>? roles,
    int? permissions,
    bool? isAdmin,
    int? udpPort,
  }) {
    return User(
      id: id ?? this.id,
      username: username ?? this.username,
      token: token ?? this.token,
      roles: roles ?? this.roles,
      permissions: permissions ?? this.permissions,
      isAdmin: isAdmin ?? this.isAdmin,
      udpPort: udpPort ?? this.udpPort,
    );
  }
}

/// User profile used in roster listings.
class UserProfile {
  final int userId;
  final String username;
  final List<String> roles;
  final bool isAdmin;
  final bool online;
  final String status;
  final int? voiceChannelId;
  final int lastSeen;

  const UserProfile({
    required this.userId,
    required this.username,
    this.roles = const [],
    this.isAdmin = false,
    this.online = false,
    this.status = 'offline',
    this.voiceChannelId,
    this.lastSeen = 0,
  });

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    int? vChanId;
    if (json['voice_channel_id'] is int) {
      vChanId = json['voice_channel_id'] as int;
    } else if (json['channel_id'] is int) {
      vChanId = json['channel_id'] as int;
    }

    return UserProfile(
      userId: json['user_id'] is int
          ? json['user_id'] as int
          : (json['id'] is int ? json['id'] as int : 0),
      username: (json['username'] as String?) ?? '',
      roles: (json['roles'] as List<dynamic>?)
              ?.map((e) => e.toString())
              .toList() ??
          const [],
      isAdmin: json['is_admin'] == true,
      online: json['online'] == true,
      status: (json['status'] as String?) ?? (json['online'] == true ? 'online' : 'offline'),
      voiceChannelId: vChanId,
      lastSeen: (json['last_seen'] is int) ? json['last_seen'] as int : 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'user_id': userId,
      'username': username,
      'roles': roles,
      'is_admin': isAdmin,
      'online': online,
      'status': status,
      'voice_channel_id': voiceChannelId,
      'last_seen': lastSeen,
    };
  }

  UserProfile copyWith({
    int? userId,
    String? username,
    List<String>? roles,
    bool? isAdmin,
    bool? online,
    String? status,
    int? voiceChannelId,
    int? lastSeen,
  }) {
    return UserProfile(
      userId: userId ?? this.userId,
      username: username ?? this.username,
      roles: roles ?? this.roles,
      isAdmin: isAdmin ?? this.isAdmin,
      online: online ?? this.online,
      status: status ?? this.status,
      voiceChannelId: voiceChannelId ?? this.voiceChannelId,
      lastSeen: lastSeen ?? this.lastSeen,
    );
  }
}
