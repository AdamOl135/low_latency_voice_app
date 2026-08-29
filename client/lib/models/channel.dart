/// Channel model representing text or voice rooms.
class Channel {
  final int id;
  final String name;
  final String type; // "text" or "voice"
  final String category;
  final int position;
  final int bitrate;
  final int userLimit;

  const Channel({
    required this.id,
    required this.name,
    required this.type,
    this.category = 'General',
    this.position = 0,
    this.bitrate = 48000,
    this.userLimit = 15,
  });

  bool get isVoice => type.toLowerCase() == 'voice';
  bool get isText => type.toLowerCase() == 'text';

  factory Channel.fromJson(Map<String, dynamic> json) {
    return Channel(
      id: json['id'] is int ? json['id'] as int : 0,
      name: (json['name'] as String?) ?? '',
      type: (json['type'] as String?) ?? 'text',
      category: (json['category'] as String?) ?? 'General',
      position: (json['position'] is int) ? json['position'] as int : 0,
      bitrate: (json['bitrate'] is int) ? json['bitrate'] as int : 48000,
      userLimit: (json['user_limit'] is int) ? json['user_limit'] as int : 15,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'type': type,
      'category': category,
      'position': position,
      'bitrate': bitrate,
      'user_limit': userLimit,
    };
  }

  Channel copyWith({
    int? id,
    String? name,
    String? type,
    String? category,
    int? position,
    int? bitrate,
    int? userLimit,
  }) {
    return Channel(
      id: id ?? this.id,
      name: name ?? this.name,
      type: type ?? this.type,
      category: category ?? this.category,
      position: position ?? this.position,
      bitrate: bitrate ?? this.bitrate,
      userLimit: userLimit ?? this.userLimit,
    );
  }
}
