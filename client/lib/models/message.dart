/// Message model representing chat entries in text channels.
class Message {
  final int id;
  final int channelId;
  final int senderId;
  final String senderName;
  final String content;
  final int timestamp;
  final bool isPending;
  final bool hasFailed;

  const Message({
    required this.id,
    required this.channelId,
    required this.senderId,
    required this.senderName,
    required this.content,
    required this.timestamp,
    this.isPending = false,
    this.hasFailed = false,
  });

  factory Message.fromJson(Map<String, dynamic> json) {
    return Message(
      id: json['id'] is int ? json['id'] as int : (json['message_id'] is int ? json['message_id'] as int : 0),
      channelId: json['channel_id'] is int ? json['channel_id'] as int : 0,
      senderId: json['sender_id'] is int ? json['sender_id'] as int : 0,
      senderName: (json['sender_name'] as String?) ?? 'Unknown',
      content: (json['content'] as String?) ?? '',
      timestamp: json['timestamp'] is int
          ? json['timestamp'] as int
          : (DateTime.now().millisecondsSinceEpoch ~/ 1000),
      isPending: false,
      hasFailed: false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'channel_id': channelId,
      'sender_id': senderId,
      'sender_name': senderName,
      'content': content,
      'timestamp': timestamp,
    };
  }

  Message copyWith({
    int? id,
    int? channelId,
    int? senderId,
    String? senderName,
    String? content,
    int? timestamp,
    bool? isPending,
    bool? hasFailed,
  }) {
    return Message(
      id: id ?? this.id,
      channelId: channelId ?? this.channelId,
      senderId: senderId ?? this.senderId,
      senderName: senderName ?? this.senderName,
      content: content ?? this.content,
      timestamp: timestamp ?? this.timestamp,
      isPending: isPending ?? this.isPending,
      hasFailed: hasFailed ?? this.hasFailed,
    );
  }
}
