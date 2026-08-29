import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/channel.dart';
import '../services/websocket_service.dart';
import 'auth_notifier.dart';

class ChannelsState {
  final List<Channel> channels;
  final int? selectedTextChannelId;
  final int? selectedVoiceChannelId;
  final Map<int, List<int>> voiceOccupants; // channelId -> List of userIds
  final bool isLoading;
  final String? errorMessage;

  const ChannelsState({
    this.channels = const [],
    this.selectedTextChannelId,
    this.selectedVoiceChannelId,
    this.voiceOccupants = const {},
    this.isLoading = false,
    this.errorMessage,
  });

  List<Channel> get textChannels =>
      channels.where((c) => c.isText).toList()..sort((a, b) => a.position.compareTo(b.position));

  List<Channel> get voiceChannels =>
      channels.where((c) => c.isVoice).toList()..sort((a, b) => a.position.compareTo(b.position));

  Channel? get selectedTextChannel {
    if (selectedTextChannelId == null) return null;
    try {
      return channels.firstWhere((c) => c.id == selectedTextChannelId);
    } catch (_) {
      return null;
    }
  }

  Channel? get selectedVoiceChannel {
    if (selectedVoiceChannelId == null) return null;
    try {
      return channels.firstWhere((c) => c.id == selectedVoiceChannelId);
    } catch (_) {
      return null;
    }
  }

  ChannelsState copyWith({
    List<Channel>? channels,
    int? selectedTextChannelId,
    int? selectedVoiceChannelId,
    Map<int, List<int>>? voiceOccupants,
    bool? isLoading,
    String? errorMessage,
  }) {
    return ChannelsState(
      channels: channels ?? this.channels,
      selectedTextChannelId: selectedTextChannelId ?? this.selectedTextChannelId,
      selectedVoiceChannelId: selectedVoiceChannelId ?? this.selectedVoiceChannelId,
      voiceOccupants: voiceOccupants ?? this.voiceOccupants,
      isLoading: isLoading ?? this.isLoading,
      errorMessage: errorMessage,
    );
  }
}

class ChannelsNotifier extends StateNotifier<ChannelsState> {
  final WebSocketService _ws;

  ChannelsNotifier(this._ws) : super(const ChannelsState()) {
    _listenToEvents();
  }

  void _listenToEvents() {
    _ws.eventStream.listen((event) {
      final eventType = event['event']?.toString();
      final data = (event['data'] is Map) ? event['data'] as Map<String, dynamic> : event;

      if (eventType == 'channel_created') {
        final chData = data['channel'] ?? data;
        final newChannel = Channel.fromJson(Map<String, dynamic>.from(chData as Map));
        state = state.copyWith(
          channels: [...state.channels.where((c) => c.id != newChannel.id), newChannel],
        );
      } else if (eventType == 'channel_deleted') {
        final channelId = data['channel_id'] as int?;
        if (channelId != null) {
          state = state.copyWith(
            channels: state.channels.where((c) => c.id != channelId).toList(),
            selectedTextChannelId: state.selectedTextChannelId == channelId ? null : state.selectedTextChannelId,
            selectedVoiceChannelId: state.selectedVoiceChannelId == channelId ? null : state.selectedVoiceChannelId,
          );
        }
      } else if (eventType == 'voice_state_update') {
        final userId = data['user_id'] as int?;
        final channelId = data['channel_id'] as int?;
        if (userId != null) {
          _updateVoiceOccupant(userId, channelId);
        }
      } else if (eventType == 'member_moved') {
        final userId = data['user_id'] as int?;
        final toChannelId = data['to_channel_id'] as int?;
        if (userId != null) {
          _updateVoiceOccupant(userId, toChannelId);
        }
      }
    });
  }

  void _updateVoiceOccupant(int userId, int? channelId) {
    final updated = Map<int, List<int>>.from(state.voiceOccupants);

    // Remove user from all channels first
    for (final chId in updated.keys) {
      updated[chId] = updated[chId]!.where((id) => id != userId).toList();
    }

    // Add to new channel if present
    if (channelId != null && channelId > 0) {
      if (!updated.containsKey(channelId)) {
        updated[channelId] = [];
      }
      if (!updated[channelId]!.contains(userId)) {
        updated[channelId] = [...updated[channelId]!, userId];
      }
    }

    state = state.copyWith(voiceOccupants: updated);
  }

  Future<void> fetchChannels() async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      final res = await _ws.getChannels();
      final listData = (res['data'] is Map && res['data']['channels'] is List)
          ? res['data']['channels'] as List
          : (res['result'] is Map && res['result']['channels'] is List
              ? res['result']['channels'] as List
              : (res['channels'] is List ? res['channels'] as List : []));

      final channels = listData.map((e) => Channel.fromJson(Map<String, dynamic>.from(e as Map))).toList();

      int? firstTextId = state.selectedTextChannelId;
      if (firstTextId == null && channels.any((c) => c.isText)) {
        firstTextId = channels.firstWhere((c) => c.isText).id;
      }

      state = state.copyWith(
        channels: channels,
        selectedTextChannelId: firstTextId,
        isLoading: false,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
    }
  }

  void selectTextChannel(int channelId) {
    state = state.copyWith(selectedTextChannelId: channelId);
  }

  void setConnectedVoiceChannel(int? channelId) {
    state = state.copyWith(selectedVoiceChannelId: channelId);
  }

  Future<bool> createChannel({
    required String name,
    required String type,
    String category = 'General',
    int position = 0,
    int bitrate = 48000,
    int userLimit = 15,
  }) async {
    try {
      await _ws.createChannel(
        name: name,
        type: type,
        category: category,
        position: position,
        bitrate: bitrate,
        userLimit: userLimit,
      );
      await fetchChannels();
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }

  Future<bool> deleteChannel(int channelId) async {
    try {
      await _ws.deleteChannel(channelId);
      state = state.copyWith(
        channels: state.channels.where((c) => c.id != channelId).toList(),
      );
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }
}

final channelsProvider = StateNotifierProvider<ChannelsNotifier, ChannelsState>((ref) {
  final ws = ref.watch(webSocketServiceProvider);
  return ChannelsNotifier(ws);
});
