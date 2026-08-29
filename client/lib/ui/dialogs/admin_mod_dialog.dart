import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme.dart';
import '../../models/user.dart';
import '../../state/channels_notifier.dart';
import '../../state/roster_notifier.dart';

class AdminModDialog extends ConsumerStatefulWidget {
  final UserProfile targetUser;

  const AdminModDialog({super.key, required this.targetUser});

  @override
  ConsumerState<AdminModDialog> createState() => _AdminModDialogState();
}

class _AdminModDialogState extends ConsumerState<AdminModDialog> {
  int? _selectedVoiceChannelId;
  late TextEditingController _kickReasonController;

  @override
  void initState() {
    super.initState();
    _selectedVoiceChannelId = widget.targetUser.voiceChannelId;
    _kickReasonController = TextEditingController(text: 'Rule violation');
  }

  @override
  void dispose() {
    _kickReasonController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final channels = ref.watch(channelsProvider).voiceChannels;
    final rosterNotifier = ref.read(rosterProvider.notifier);
    final voiceState = ref.watch(rosterProvider).getVoiceState(widget.targetUser.userId);

    final isServerMuted = voiceState?.serverMuted ?? false;
    final isServerDeafened = voiceState?.serverDeafened ?? false;

    return Dialog(
      backgroundColor: AppTheme.backgroundElevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 460, maxHeight: 520),
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      'Moderation: ${widget.targetUser.username}',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textPrimary,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.close, color: AppTheme.textMuted),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: ListView(
                  children: [
                    // Move Voice Channel
                    const Text(
                      'MOVE TO VOICE CHANNEL',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textMuted,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        color: AppTheme.backgroundSurface,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: DropdownButtonHideUnderline(
                        child: DropdownButton<int>(
                          value: _selectedVoiceChannelId,
                          hint: const Text('Select a voice channel', style: TextStyle(color: AppTheme.textMuted)),
                          isExpanded: true,
                          dropdownColor: AppTheme.backgroundSurface,
                          items: channels.map((ch) {
                            return DropdownMenuItem<int>(
                              value: ch.id,
                              child: Text(ch.name, style: const TextStyle(color: AppTheme.textPrimary)),
                            );
                          }).toList(),
                          onChanged: (id) {
                            if (id != null) {
                              setState(() => _selectedVoiceChannelId = id);
                              rosterNotifier.moveMember(widget.targetUser.userId, id);
                            }
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Server Mute & Deafen Toggles
                    const Text(
                      'SERVER-WIDE RESTRICTIONS',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textMuted,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 8),
                    SwitchListTile(
                      tileColor: AppTheme.backgroundSurface,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                      title: const Text('Server Mute', style: TextStyle(color: AppTheme.textPrimary, fontSize: 14)),
                      subtitle: const Text('Prevents user from speaking in all voice channels', style: TextStyle(color: AppTheme.textMuted, fontSize: 12)),
                      value: isServerMuted,
                      activeThumbColor: AppTheme.dangerRed,
                      onChanged: (val) {
                        rosterNotifier.setServerMute(widget.targetUser.userId, val);
                      },
                    ),
                    const SizedBox(height: 8),
                    SwitchListTile(
                      tileColor: AppTheme.backgroundSurface,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                      title: const Text('Server Deafen', style: TextStyle(color: AppTheme.textPrimary, fontSize: 14)),
                      subtitle: const Text('Prevents user from hearing or speaking in channels', style: TextStyle(color: AppTheme.textMuted, fontSize: 12)),
                      value: isServerDeafened,
                      activeThumbColor: AppTheme.dangerRed,
                      onChanged: (val) {
                        rosterNotifier.setServerDeafen(widget.targetUser.userId, val);
                      },
                    ),
                    const SizedBox(height: 20),

                    // Kick User
                    const Text(
                      'KICK MEMBER',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.dangerRed,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      controller: _kickReasonController,
                      decoration: const InputDecoration(
                        labelText: 'Reason for kick',
                      ),
                    ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.dangerRed,
                        foregroundColor: Colors.white,
                      ),
                      onPressed: () {
                        rosterNotifier.kickMember(
                          widget.targetUser.userId,
                          reason: _kickReasonController.text,
                        );
                        Navigator.of(context).pop();
                      },
                      icon: const Icon(Icons.gavel, size: 18),
                      label: const Text('Kick User Immediately'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
