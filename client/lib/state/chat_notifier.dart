import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/message.dart';
import '../services/websocket_service.dart';
import 'auth_notifier.dart';

class ChatState {
  final Map<int, List<Message>> messagesByChannel;
  final Map<int, bool> hasMoreByChannel;
  final bool isLoadingHistory;
  final String? errorMessage;

  const ChatState({
    this.messagesByChannel = const {},
    this.hasMoreByChannel = const {},
    this.isLoadingHistory = false,
    this.errorMessage,
  });

  List<Message> getMessagesFor(int? channelId) {
    if (channelId == null) return const [];
    return messagesByChannel[channelId] ?? const [];
  }

  bool hasMoreFor(int? channelId) {
    if (channelId == null) return false;
    return hasMoreByChannel[channelId] ?? true;
  }

  ChatState copyWith({
    Map<int, List<Message>>? messagesByChannel,
    Map<int, bool>? hasMoreByChannel,
    bool? isLoadingHistory,
    String? errorMessage,
  }) {
    return ChatState(
      messagesByChannel: messagesByChannel ?? this.messagesByChannel,
      hasMoreByChannel: hasMoreByChannel ?? this.hasMoreByChannel,
      isLoadingHistory: isLoadingHistory ?? this.isLoadingHistory,
      errorMessage: errorMessage,
    );
  }
}

class ChatNotifier extends StateNotifier<ChatState> {
  final WebSocketService _ws;

  ChatNotifier(this._ws) : super(const ChatState()) {
    _listenToEvents();
  }

  void _listenToEvents() {
    _ws.eventStream.listen((event) {
      final eventType = event['event']?.toString();
      final data = (event['data'] is Map) ? event['data'] as Map<String, dynamic> : event;

      if (eventType == 'chat_message') {
        final message = Message.fromJson(Map<String, dynamic>.from(data as Map));
        _appendIncomingMessage(message);
      }
    });
  }

  void _appendIncomingMessage(Message message) {
    final updated = Map<int, List<Message>>.from(state.messagesByChannel);
    final currentList = updated[message.channelId] ?? [];

    // Avoid duplicate message if already exists
    if (!currentList.any((m) => m.id == message.id && message.id != 0)) {
      updated[message.channelId] = [...currentList, message];
      state = state.copyWith(messagesByChannel: updated);
    }
  }

  Future<void> loadMessages(int channelId, {bool loadMore = false}) async {
    if (state.isLoadingHistory) return;

    final currentMessages = state.messagesByChannel[channelId] ?? [];
    var beforeId = 0;
    if (loadMore && currentMessages.isNotEmpty) {
      beforeId = currentMessages.first.id;
    }

    state = state.copyWith(isLoadingHistory: true, errorMessage: null);

    try {
      final res = await _ws.getChatHistory(channelId, beforeId: beforeId, limit: 50);
      final data = (res['data'] is Map) ? res['data'] as Map<String, dynamic> : res;
      final rawList = data['messages'] is List ? data['messages'] as List : [];
      final hasMore = data['has_more'] == true;

      final fetchedMessages = rawList
          .map((e) => Message.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();

      final updatedMessages = Map<int, List<Message>>.from(state.messagesByChannel);
      final updatedHasMore = Map<int, bool>.from(state.hasMoreByChannel);

      if (loadMore) {
        updatedMessages[channelId] = [...fetchedMessages, ...currentMessages];
      } else {
        updatedMessages[channelId] = fetchedMessages;
      }
      updatedHasMore[channelId] = hasMore;

      state = state.copyWith(
        messagesByChannel: updatedMessages,
        hasMoreByChannel: updatedHasMore,
        isLoadingHistory: false,
      );
    } catch (e) {
      state = state.copyWith(isLoadingHistory: false, errorMessage: e.toString());
    }
  }

  Future<bool> sendMessage(int channelId, String content, String senderName, int senderId) async {
    final trimmed = content.trim();
    if (trimmed.isEmpty) return false;

    // Optimistic pending message
    final tempId = -DateTime.now().millisecondsSinceEpoch;
    final optimisticMsg = Message(
      id: tempId,
      channelId: channelId,
      senderId: senderId,
      senderName: senderName,
      content: trimmed,
      timestamp: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      isPending: true,
    );

    final updated = Map<int, List<Message>>.from(state.messagesByChannel);
    final currentList = updated[channelId] ?? [];
    updated[channelId] = [...currentList, optimisticMsg];
    state = state.copyWith(messagesByChannel: updated);

    try {
      final res = await _ws.sendChat(channelId, trimmed);
      final data = (res['data'] is Map) ? res['data'] as Map<String, dynamic> : res;
      final confirmedMsg = Message.fromJson(Map<String, dynamic>.from(data as Map));

      // Replace optimistic message
      final fresh = Map<int, List<Message>>.from(state.messagesByChannel);
      fresh[channelId] = (fresh[channelId] ?? []).map((m) {
        if (m.id == tempId) {
          return confirmedMsg;
        }
        return m;
      }).toList();

      state = state.copyWith(messagesByChannel: fresh);
      return true;
    } catch (e) {
      // Mark as failed
      final fresh = Map<int, List<Message>>.from(state.messagesByChannel);
      fresh[channelId] = (fresh[channelId] ?? []).map((m) {
        if (m.id == tempId) {
          return m.copyWith(isPending: false, hasFailed: true);
        }
        return m;
      }).toList();

      state = state.copyWith(messagesByChannel: fresh, errorMessage: e.toString());
      return false;
    }
  }
}

final chatProvider = StateNotifierProvider<ChatNotifier, ChatState>((ref) {
  final ws = ref.watch(webSocketServiceProvider);
  return ChatNotifier(ws);
});
