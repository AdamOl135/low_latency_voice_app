import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/constants.dart';
import '../../core/theme.dart';
import '../../models/message.dart';
import '../../state/auth_notifier.dart';
import '../../state/channels_notifier.dart';
import '../../state/chat_notifier.dart';
import 'voice_hud.dart';

class ChatPane extends ConsumerStatefulWidget {
  final VoidCallback? onToggleRoster;

  const ChatPane({super.key, this.onToggleRoster});

  @override
  ConsumerState<ChatPane> createState() => _ChatPaneState();
}

class _ChatPaneState extends ConsumerState<ChatPane> {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels <= _scrollController.position.minScrollExtent + 50) {
      final activeChannel = ref.read(channelsProvider).selectedTextChannel;
      if (activeChannel != null) {
        ref.read(chatProvider.notifier).loadMessages(activeChannel.id, loadMore: true);
      }
    }
  }

  void _sendMessage() {
    final text = _inputController.text.trim();
    if (text.isEmpty) return;

    final activeChannel = ref.read(channelsProvider).selectedTextChannel;
    final currentUser = ref.read(authProvider).user;

    if (activeChannel != null && currentUser != null) {
      ref.read(chatProvider.notifier).sendMessage(
        activeChannel.id,
        text,
        currentUser.username,
        currentUser.id,
      );
      _inputController.clear();
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final channelsState = ref.watch(channelsProvider);
    final activeChannel = channelsState.selectedTextChannel;
    final chatState = ref.watch(chatProvider);
    final messages = chatState.getMessagesFor(activeChannel?.id);

    return Container(
      color: AppTheme.backgroundMain,
      child: Column(
        children: [
          // Top Channel Header
          Container(
            height: AppConstants.topHeaderHeight,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: const BoxDecoration(
              color: AppTheme.backgroundMain,
              border: Border(
                bottom: BorderSide(color: AppTheme.dividerColor, width: 1),
              ),
            ),
            child: Row(
              children: [
                const Text(
                  '#',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.textMuted,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  activeChannel?.name ?? 'Select a text channel',
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const Spacer(),
                if (widget.onToggleRoster != null)
                  IconButton(
                    icon: const Icon(Icons.people_alt, color: AppTheme.textMuted, size: 20),
                    tooltip: 'Toggle Member Roster',
                    onPressed: widget.onToggleRoster,
                  ),
              ],
            ),
          ),

          // Active Voice HUD Banner
          const VoiceHud(),

          // Virtualized Message Stream
          Expanded(
            child: activeChannel == null
                ? const Center(
                    child: Text(
                      'Select a channel to begin chatting',
                      style: TextStyle(color: AppTheme.textMuted),
                    ),
                  )
                : messages.isEmpty
                    ? Center(
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.chat_bubble_outline, size: 48, color: AppTheme.textMuted),
                            const SizedBox(height: 12),
                            Text(
                              'Welcome to #${activeChannel.name}!',
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                color: AppTheme.textPrimary,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'This is the start of the #${activeChannel.name} channel.',
                              style: const TextStyle(color: AppTheme.textMuted, fontSize: 13),
                            ),
                          ],
                        ),
                      )
                    : ListView.builder(
                        controller: _scrollController,
                        padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                        itemCount: messages.length,
                        itemBuilder: (context, index) {
                          final msg = messages[index];
                          return _buildMessageItem(msg);
                        },
                      ),
          ),

          // Bottom Message Input Box
          if (activeChannel != null) _buildMessageInput(context, activeChannel.name),
        ],
      ),
    );
  }

  Widget _buildMessageItem(Message msg) {
    final date = DateTime.fromMillisecondsSinceEpoch(msg.timestamp * 1000);
    final timeStr =
        '${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Avatar
          Container(
            width: 38,
            height: 38,
            decoration: const BoxDecoration(
              color: AppTheme.primary,
              shape: BoxShape.circle,
            ),
            child: Center(
              child: Text(
                msg.senderName.isNotEmpty ? msg.senderName[0].toUpperCase() : '?',
                style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(width: 12),

          // Message Content
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      msg.senderName,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 14,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      timeStr,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppTheme.textMuted,
                      ),
                    ),
                    if (msg.isPending) ...[
                      const SizedBox(width: 6),
                      const Text(
                        '(sending...)',
                        style: TextStyle(fontSize: 11, color: AppTheme.warningYellow),
                      ),
                    ],
                    if (msg.hasFailed) ...[
                      const SizedBox(width: 6),
                      const Text(
                        '(failed)',
                        style: TextStyle(fontSize: 11, color: AppTheme.dangerRed),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                SelectableText(
                  msg.content,
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 14,
                    height: 1.3,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageInput(BuildContext context, String channelName) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: const BoxDecoration(
        color: AppTheme.backgroundMain,
        border: Border(
          top: BorderSide(color: AppTheme.dividerColor, width: 1),
        ),
      ),
      child: Container(
        decoration: BoxDecoration(
          color: AppTheme.backgroundSurface,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            const SizedBox(width: 12),
            Expanded(
              child: CallbackShortcuts(
                bindings: {
                  const SingleActivator(LogicalKeyboardKey.enter): _sendMessage,
                },
                child: TextField(
                  controller: _inputController,
                  maxLines: 4,
                  minLines: 1,
                  style: const TextStyle(color: AppTheme.textPrimary, fontSize: 14),
                  decoration: InputDecoration(
                    hintText: 'Message #$channelName',
                    border: InputBorder.none,
                    filled: false,
                    contentPadding: const EdgeInsets.symmetric(vertical: 12),
                  ),
                ),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.send, color: AppTheme.primary, size: 20),
              tooltip: 'Send Message',
              onPressed: _sendMessage,
            ),
          ],
        ),
      ),
    );
  }
}
