import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/user.dart';
import '../models/voice_state.dart';
import '../services/websocket_service.dart';
import 'auth_notifier.dart';

class RosterState {
  final List<UserProfile> members;
  final Map<int, VoiceState> voiceStates; // userId -> VoiceState
  final bool isLoading;
  final String? errorMessage;

  const RosterState({
    this.members = const [],
    this.voiceStates = const {},
    this.isLoading = false,
    this.errorMessage,
  });

  List<UserProfile> get onlineMembers =>
      members.where((m) => m.online).toList()..sort((a, b) => a.username.compareTo(b.username));

  List<UserProfile> get offlineMembers =>
      members.where((m) => !m.online).toList()..sort((a, b) => a.username.compareTo(b.username));

  List<UserProfile> get admins =>
      members.where((m) => m.isAdmin && m.online).toList();

  List<UserProfile> get moderators =>
      members.where((m) => !m.isAdmin && m.roles.contains('moderator') && m.online).toList();

  List<UserProfile> get standardOnlineMembers =>
      members.where((m) => !m.isAdmin && !m.roles.contains('moderator') && m.online).toList();

  VoiceState? getVoiceState(int userId) => voiceStates[userId];

  RosterState copyWith({
    List<UserProfile>? members,
    Map<int, VoiceState>? voiceStates,
    bool? isLoading,
    String? errorMessage,
  }) {
    return RosterState(
      members: members ?? this.members,
      voiceStates: voiceStates ?? this.voiceStates,
      isLoading: isLoading ?? this.isLoading,
      errorMessage: errorMessage,
    );
  }
}

class RosterNotifier extends StateNotifier<RosterState> {
  final WebSocketService _ws;

  RosterNotifier(this._ws) : super(const RosterState()) {
    _listenToEvents();
  }

  void _listenToEvents() {
    _ws.eventStream.listen((event) {
      final eventType = event['event']?.toString();
      final data = (event['data'] is Map) ? event['data'] as Map<String, dynamic> : event;

      if (eventType == 'presence_update') {
        final userId = data['user_id'] as int?;
        final online = data['online'] == true;
        if (userId != null) {
          final updated = state.members.map((m) {
            if (m.userId == userId) {
              return m.copyWith(online: online, status: online ? 'online' : 'offline');
            }
            return m;
          }).toList();
          state = state.copyWith(members: updated);
        }
      } else if (eventType == 'voice_state_update') {
        final userId = data['user_id'] as int?;
        if (userId != null) {
          final vs = VoiceState.fromJson(Map<String, dynamic>.from(data));
          final updatedStates = Map<int, VoiceState>.from(state.voiceStates);

          if (vs.channelId == null || vs.channelId == 0) {
            updatedStates.remove(userId);
          } else {
            updatedStates[userId] = vs;
          }

          final updatedMembers = state.members.map((m) {
            if (m.userId == userId) {
              return m.copyWith(voiceChannelId: vs.channelId);
            }
            return m;
          }).toList();

          state = state.copyWith(voiceStates: updatedStates, members: updatedMembers);
        }
      } else if (eventType == 'member_joined') {
        fetchRoster();
      } else if (eventType == 'member_kicked') {
        final kickedId = data['user_id'] as int?;
        if (kickedId != null) {
          state = state.copyWith(
            members: state.members.where((m) => m.userId != kickedId).toList(),
          );
        }
      }
    });
  }

  Future<void> fetchRoster() async {
    state = state.copyWith(isLoading: true, errorMessage: null);
    try {
      final res = await _ws.getRoster();
      final listData = (res['data'] is Map && res['data']['members'] is List)
          ? res['data']['members'] as List
          : (res['result'] is Map && res['result']['members'] is List
              ? res['result']['members'] as List
              : (res['members'] is List ? res['members'] as List : []));

      final members = <UserProfile>[];
      final voiceStates = <int, VoiceState>{};

      for (final item in listData) {
        if (item is Map) {
          final profile = UserProfile.fromJson(Map<String, dynamic>.from(item));
          members.add(profile);

          if (item['voice_state'] is Map) {
            final vs = VoiceState.fromJson(Map<String, dynamic>.from(item['voice_state'] as Map));
            if (vs.channelId != null && vs.channelId! > 0) {
              voiceStates[vs.userId] = vs;
            }
          }
        }
      }

      state = state.copyWith(
        members: members,
        voiceStates: voiceStates,
        isLoading: false,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, errorMessage: e.toString());
    }
  }

  // Moderation Methods
  Future<bool> moveMember(int targetUserId, int toChannelId) async {
    try {
      await _ws.moveMember(targetUserId, toChannelId);
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }

  Future<bool> setServerMute(int targetUserId, bool muted) async {
    try {
      await _ws.setServerMute(targetUserId, muted);
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }

  Future<bool> setServerDeafen(int targetUserId, bool deafened) async {
    try {
      await _ws.setServerDeafen(targetUserId, deafened);
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }

  Future<bool> kickMember(int targetUserId, {String reason = 'Kicked by moderator'}) async {
    try {
      await _ws.kickMember(targetUserId, reason: reason);
      state = state.copyWith(
        members: state.members.where((m) => m.userId != targetUserId).toList(),
      );
      return true;
    } catch (e) {
      state = state.copyWith(errorMessage: e.toString());
      return false;
    }
  }
}

final rosterProvider = StateNotifierProvider<RosterNotifier, RosterState>((ref) {
  final ws = ref.watch(webSocketServiceProvider);
  return RosterNotifier(ws);
});
