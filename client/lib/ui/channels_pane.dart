import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/constants.dart';
import '../../core/theme.dart';
import '../../models/channel.dart';
import '../../models/user.dart';
import '../../state/auth_notifier.dart';
import '../../state/channels_notifier.dart';
import '../../state/roster_notifier.dart';
import '../../state/voice_notifier.dart';
import 'dialogs/audio_settings_dialog.dart';

class ChannelsPane extends ConsumerWidget {
  const ChannelsPane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channelsState = ref.watch(channelsProvider);
    final channelsNotifier = ref.read(channelsProvider.notifier);
    final authState = ref.watch(authProvider);
    final voiceState = ref.watch(voiceProvider);
    final voiceNotifier = ref.read(voiceProvider.notifier);

    final canCreateChannel = authState.isAuthenticated;

    return Container(
      width: AppConstants.leftPaneWidth,
      color: AppTheme.backgroundSidebar,
      child: Column(
        children: [
          // Server Header
          Container(
            height: AppConstants.topHeaderHeight,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: const BoxDecoration(
              border: Border(
                bottom: BorderSide(color: AppTheme.dividerColor, width: 1),
              ),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Expanded(
                  child: Row(
                    children: [
                      Icon(Icons.hub, color: AppTheme.primary, size: 20),
                      SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'VoiceHQ Server',
                          style: TextStyle(
                            fontWeight: FontWeight.bold,
                            fontSize: 15,
                            color: AppTheme.textPrimary,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
                if (canCreateChannel)
                  IconButton(
                    icon: const Icon(Icons.add, color: AppTheme.textMuted, size: 20),
                    tooltip: 'Create Channel',
                    onPressed: () => _showCreateChannelDialog(context, channelsNotifier),
                  ),
              ],
            ),
          ),

          // Channel List
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: [
                // Text Channels Category
                _buildCategoryHeader(context, 'TEXT CHANNELS'),
                ...channelsState.textChannels.map((ch) {
                  final isSelected = ch.id == channelsState.selectedTextChannelId;
                  return _buildTextChannelTile(context, ch, isSelected, () {
                    channelsNotifier.selectTextChannel(ch.id);
                  });
                }),

                const SizedBox(height: 16),

                // Voice Channels Category
                _buildCategoryHeader(context, 'VOICE CHANNELS'),
                ...channelsState.voiceChannels.map((ch) {
                  final isConnected = ch.id == voiceState.connectedChannelId;
                  final occupants = channelsState.voiceOccupants[ch.id] ?? [];
                  return _buildVoiceChannelSection(
                    context,
                    ref,
                    ch,
                    isConnected,
                    occupants,
                    () {
                      if (isConnected) {
                        voiceNotifier.disconnect();
                      } else {
                        voiceNotifier.joinVoice(ch.id, ch.name);
                      }
                    },
                  );
                }),
              ],
            ),
          ),

          // Bottom User Profile Dock
          _buildUserProfileDock(context, ref),
        ],
      ),
    );
  }

  Widget _buildCategoryHeader(BuildContext context, String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Text(
        title,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.bold,
          color: AppTheme.textMuted,
          letterSpacing: 0.5,
        ),
      ),
    );
  }

  Widget _buildTextChannelTile(
    BuildContext context,
    Channel channel,
    bool isSelected,
    VoidCallback onTap,
  ) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      child: Material(
        color: isSelected ? const Color(0xFF35373C) : Colors.transparent,
        borderRadius: BorderRadius.circular(4),
        child: ListTile(
          dense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
          leading: const Text(
            '#',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: AppTheme.textMuted,
            ),
          ),
          title: Text(
            channel.name,
            style: TextStyle(
              color: isSelected ? AppTheme.textPrimary : AppTheme.textSecondary,
              fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
              fontSize: 14,
            ),
          ),
          onTap: onTap,
        ),
      ),
    );
  }

  Widget _buildVoiceChannelSection(
    BuildContext context,
    WidgetRef ref,
    Channel channel,
    bool isConnected,
    List<int> occupantIds,
    VoidCallback onTap,
  ) {
    final roster = ref.watch(rosterProvider);
    final voiceState = ref.watch(voiceProvider);
    final currentUser = ref.watch(authProvider).user;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          child: Material(
            color: isConnected ? AppTheme.speakingGreen.withAlpha(30) : Colors.transparent,
            borderRadius: BorderRadius.circular(4),
            child: ListTile(
              dense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
              leading: Icon(
                Icons.volume_up,
                color: isConnected ? AppTheme.speakingGreen : AppTheme.textMuted,
                size: 20,
              ),
              title: Text(
                channel.name,
                style: TextStyle(
                  color: isConnected ? AppTheme.speakingGreen : AppTheme.textSecondary,
                  fontWeight: isConnected ? FontWeight.w600 : FontWeight.normal,
                  fontSize: 14,
                ),
              ),
              trailing: Text(
                '${occupantIds.length}/${channel.userLimit}',
                style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
              ),
              onTap: onTap,
            ),
          ),
        ),

        // Nested Occupants List
        if (occupantIds.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 32, right: 8, bottom: 4),
            child: Column(
              children: occupantIds.map((userId) {
                final member = roster.members.firstWhere(
                  (m) => m.userId == userId,
                  orElse: () => UserProfile(userId: userId, username: 'User #$userId'),
                );
                final isSpeaking = (voiceState.speakingUsers[userId] == true) ||
                    (userId == currentUser?.id && voiceState.isLocalSpeaking && !voiceState.isMuted);
                final vs = roster.getVoiceState(userId);

                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Container(
                        width: 22,
                        height: 22,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: AppTheme.backgroundElevated,
                          border: Border.all(
                            color: isSpeaking ? AppTheme.speakingGreen : Colors.transparent,
                            width: 2,
                          ),
                          boxShadow: isSpeaking
                              ? [
                                  BoxShadow(
                                    color: AppTheme.speakingGreen.withAlpha(120),
                                    blurRadius: 4,
                                    spreadRadius: 1,
                                  ),
                                ]
                              : null,
                        ),
                        child: Center(
                          child: Text(
                            member.username.isNotEmpty ? member.username[0].toUpperCase() : '?',
                            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          member.username,
                          style: TextStyle(
                            color: isSpeaking ? AppTheme.speakingGreen : AppTheme.textSecondary,
                            fontSize: 13,
                            fontWeight: isSpeaking ? FontWeight.w600 : FontWeight.normal,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      if (vs != null && vs.isMuted)
                        const Icon(Icons.mic_off, color: AppTheme.dangerRed, size: 14),
                      if (vs != null && vs.isDeafened)
                        const Icon(Icons.headset_off, color: AppTheme.dangerRed, size: 14),
                    ],
                  ),
                );
              }).toList(),
            ),
          ),
      ],
    );
  }

  Widget _buildUserProfileDock(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);
    final voiceState = ref.watch(voiceProvider);
    final voiceNotifier = ref.read(voiceProvider.notifier);
    final user = authState.user;
    final isLocalSpeaking = (user != null && voiceState.speakingUsers[user.id] == true) ||
        (voiceState.isLocalSpeaking && !voiceState.isMuted);

    return Container(
      height: AppConstants.bottomUserDockHeight,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      color: const Color(0xFF232428),
      child: Row(
        children: [
          // Avatar with Speaking Halo
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: AppTheme.primary,
              border: Border.all(
                color: isLocalSpeaking ? AppTheme.speakingGreen : Colors.transparent,
                width: 2.5,
              ),
              boxShadow: isLocalSpeaking
                  ? [
                      BoxShadow(
                        color: AppTheme.speakingGreen.withAlpha(150),
                        blurRadius: 6,
                        spreadRadius: 1,
                      ),
                    ]
                  : null,
            ),
            child: Center(
              child: Text(
                user != null && user.username.isNotEmpty ? user.username[0].toUpperCase() : 'U',
                style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(width: 8),

          // User Handle
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  user?.username ?? 'Guest',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: AppTheme.textPrimary,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  user != null && user.isAdmin ? 'Admin' : '#${user?.id ?? 0}',
                  style: const TextStyle(fontSize: 11, color: AppTheme.textMuted),
                ),
              ],
            ),
          ),

          // Microphone Button
          IconButton(
            icon: Icon(
              voiceState.selfMuted ? Icons.mic_off : Icons.mic,
              color: voiceState.selfMuted ? AppTheme.dangerRed : AppTheme.textPrimary,
              size: 19,
            ),
            tooltip: voiceState.selfMuted ? 'Unmute Mic' : 'Mute Mic',
            onPressed: () => voiceNotifier.toggleMute(),
          ),

          // Deafen Button
          IconButton(
            icon: Icon(
              voiceState.selfDeafened ? Icons.headset_off : Icons.headset,
              color: voiceState.selfDeafened ? AppTheme.dangerRed : AppTheme.textPrimary,
              size: 19,
            ),
            tooltip: voiceState.selfDeafened ? 'Undeafen' : 'Deafen',
            onPressed: () => voiceNotifier.toggleDeafen(),
          ),

          // Settings Cogwheel
          IconButton(
            icon: const Icon(Icons.settings, color: AppTheme.textPrimary, size: 19),
            tooltip: 'User Settings',
            onPressed: () {
              showDialog(
                context: context,
                builder: (_) => const AudioSettingsDialog(),
              );
            },
          ),
        ],
      ),
    );
  }

  void _showCreateChannelDialog(BuildContext context, ChannelsNotifier notifier) {
    final nameController = TextEditingController();
    String channelType = 'text';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          backgroundColor: AppTheme.backgroundElevated,
          title: const Text('Create Channel'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                decoration: const InputDecoration(labelText: 'Channel Name'),
              ),
              const SizedBox(height: 16),
              DropdownButton<String>(
                value: channelType,
                isExpanded: true,
                dropdownColor: AppTheme.backgroundSurface,
                items: const [
                  DropdownMenuItem(value: 'text', child: Text('Text Channel (#)')),
                  DropdownMenuItem(value: 'voice', child: Text('Voice Channel (🔊)')),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => channelType = val);
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('Cancel', style: TextStyle(color: AppTheme.textMuted)),
            ),
            ElevatedButton(
              onPressed: () {
                if (nameController.text.trim().isNotEmpty) {
                  notifier.createChannel(
                    name: nameController.text.trim(),
                    type: channelType,
                  );
                  Navigator.of(ctx).pop();
                }
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
  }
}
