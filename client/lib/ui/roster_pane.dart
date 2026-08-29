import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/constants.dart';
import '../../core/theme.dart';
import '../../models/role.dart';
import '../../models/user.dart';
import '../../state/auth_notifier.dart';
import '../../state/roster_notifier.dart';
import '../../state/voice_notifier.dart';
import 'dialogs/admin_mod_dialog.dart';

class RosterPane extends ConsumerWidget {
  const RosterPane({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final roster = ref.watch(rosterProvider);
    final currentUser = ref.watch(authProvider).user;
    final isAdminOrMod = currentUser != null &&
        (currentUser.isAdmin ||
            Role.hasPermission(currentUser.permissions, AppConstants.permMoveMembers) ||
            Role.hasPermission(currentUser.permissions, AppConstants.permKickMembers));

    return Container(
      width: AppConstants.rightPaneWidth,
      color: AppTheme.backgroundSidebar,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Roster Top Header
          Container(
            height: AppConstants.topHeaderHeight,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: const BoxDecoration(
              border: Border(
                bottom: BorderSide(color: AppTheme.dividerColor, width: 1),
              ),
            ),
            child: Row(
              children: [
                const Icon(Icons.people, color: AppTheme.textMuted, size: 18),
                const SizedBox(width: 8),
                Text(
                  'Members (${roster.members.length})',
                  style: const TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),

          // Member Categories
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: [
                // Admins
                if (roster.admins.isNotEmpty) ...[
                  _buildRoleHeader('ADMINS — ${roster.admins.length}', const Color(0xFFF1C40F)),
                  ...roster.admins.map((m) => _buildMemberTile(context, ref, m, isAdminOrMod)),
                  const SizedBox(height: 12),
                ],

                // Moderators
                if (roster.moderators.isNotEmpty) ...[
                  _buildRoleHeader('MODERATORS — ${roster.moderators.length}', const Color(0xFF1ABC9C)),
                  ...roster.moderators.map((m) => _buildMemberTile(context, ref, m, isAdminOrMod)),
                  const SizedBox(height: 12),
                ],

                // Standard Online Members
                if (roster.standardOnlineMembers.isNotEmpty) ...[
                  _buildRoleHeader('ONLINE — ${roster.standardOnlineMembers.length}', AppTheme.textMuted),
                  ...roster.standardOnlineMembers.map((m) => _buildMemberTile(context, ref, m, isAdminOrMod)),
                  const SizedBox(height: 12),
                ],

                // Offline Members
                if (roster.offlineMembers.isNotEmpty) ...[
                  _buildRoleHeader('OFFLINE — ${roster.offlineMembers.length}', AppTheme.textMuted),
                  ...roster.offlineMembers.map((m) => _buildMemberTile(context, ref, m, isAdminOrMod)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRoleHeader(String title, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Text(
        title,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.bold,
          color: color,
          letterSpacing: 0.5,
        ),
      ),
    );
  }

  Widget _buildMemberTile(
    BuildContext context,
    WidgetRef ref,
    UserProfile member,
    bool canModerate,
  ) {
    final voiceState = ref.watch(voiceProvider);
    final voiceNotifier = ref.read(voiceProvider.notifier);
    final memberVoice = ref.watch(rosterProvider).getVoiceState(member.userId);
    final currentUser = ref.watch(authProvider).user;
    final isSpeaking = (voiceState.speakingUsers[member.userId] == true) ||
        (member.userId == currentUser?.id && voiceState.isLocalSpeaking && !voiceState.isMuted);

    final userVolume = voiceState.userVolumes[member.userId] ?? 1.0;

    return InkWell(
      onSecondaryTapUp: (details) {
        _showMemberContextMenu(context, ref, details.globalPosition, member, canModerate, userVolume, voiceNotifier);
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Row(
          children: [
            // Avatar with speaking halo ring
            Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppTheme.primary,
                border: Border.all(
                  color: isSpeaking ? AppTheme.speakingGreen : Colors.transparent,
                  width: 2.5,
                ),
                boxShadow: isSpeaking
                    ? [
                        BoxShadow(
                          color: AppTheme.speakingGreen.withAlpha(120),
                          blurRadius: 6,
                          spreadRadius: 1,
                        ),
                      ]
                    : null,
              ),
              child: Stack(
                children: [
                  Center(
                    child: Text(
                      member.username.isNotEmpty ? member.username[0].toUpperCase() : '?',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                    ),
                  ),
                  // Online/Offline Status Dot
                  Positioned(
                    bottom: 0,
                    right: 0,
                    child: Container(
                      width: 9,
                      height: 9,
                      decoration: BoxDecoration(
                        color: member.online ? AppTheme.statusOnline : AppTheme.statusOffline,
                        shape: BoxShape.circle,
                        border: Border.all(color: AppTheme.backgroundSidebar, width: 1.5),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),

            // Username
            Expanded(
              child: Text(
                member.username,
                style: TextStyle(
                  color: member.online ? AppTheme.textPrimary : AppTheme.textMuted,
                  fontSize: 13,
                  fontWeight: member.isAdmin ? FontWeight.bold : FontWeight.normal,
                ),
                overflow: TextOverflow.ellipsis,
              ),
            ),

            // Voice State Badges
            if (memberVoice != null && memberVoice.isMuted)
              const Padding(
                padding: EdgeInsets.only(left: 4),
                child: Icon(Icons.mic_off, color: AppTheme.dangerRed, size: 14),
              ),
            if (memberVoice != null && memberVoice.isDeafened)
              const Padding(
                padding: EdgeInsets.only(left: 4),
                child: Icon(Icons.headset_off, color: AppTheme.dangerRed, size: 14),
              ),
          ],
        ),
      ),
    );
  }

  void _showMemberContextMenu(
    BuildContext context,
    WidgetRef ref,
    Offset position,
    UserProfile member,
    bool canModerate,
    double currentVolume,
    VoiceNotifier voiceNotifier,
  ) {
    showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        position.dx + 200,
        position.dy + 200,
      ),
      color: AppTheme.backgroundElevated,
      items: [
        PopupMenuItem<String>(
          enabled: false,
          child: Text(
            member.username,
            style: const TextStyle(fontWeight: FontWeight.bold, color: AppTheme.textPrimary),
          ),
        ),
        const PopupMenuDivider(),
        if (canModerate)
          const PopupMenuItem<String>(
            value: 'moderate',
            child: Row(
              children: [
                Icon(Icons.security, size: 16, color: AppTheme.primary),
                SizedBox(width: 8),
                Text('Admin Moderation...', style: TextStyle(color: AppTheme.textPrimary)),
              ],
            ),
          ),
      ],
    ).then((choice) {
      if (context.mounted && choice == 'moderate') {
        showDialog(
          context: context,
          builder: (_) => AdminModDialog(targetUser: member),
        );
      }
    });
  }
}
