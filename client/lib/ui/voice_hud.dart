import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/constants.dart';
import '../../core/theme.dart';
import '../../state/voice_notifier.dart';

class VoiceHud extends ConsumerWidget {
  const VoiceHud({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final voice = ref.watch(voiceProvider);
    final voiceNotifier = ref.read(voiceProvider.notifier);

    if (!voice.isConnected && voice.status != VoiceConnectionStatus.connecting) {
      return const SizedBox.shrink();
    }

    Color pingColor = AppTheme.speakingGreen;
    if (voice.pingMs > 80.0) {
      pingColor = AppTheme.dangerRed;
    } else if (voice.pingMs > 40.0) {
      pingColor = AppTheme.warningYellow;
    }

    return Container(
      height: AppConstants.voiceHudHeight,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: const BoxDecoration(
        color: AppTheme.backgroundSurface,
        border: Border(
          bottom: BorderSide(color: AppTheme.dividerColor, width: 1),
        ),
      ),
      child: Row(
        children: [
          // Connection Status Icon & Ping Badge
          Icon(
            voice.isConnected ? Icons.sensors : Icons.sensors_off,
            color: voice.isConnected ? AppTheme.speakingGreen : AppTheme.warningYellow,
            size: 20,
          ),
          const SizedBox(width: 10),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                voice.isConnected
                    ? 'Voice Connected / ${voice.connectedChannelName ?? "Voice"}'
                    : 'Connecting to Voice...',
                style: TextStyle(
                  color: voice.isConnected ? AppTheme.speakingGreen : AppTheme.warningYellow,
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                ),
              ),
              if (voice.isConnected)
                Row(
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        color: pingColor,
                        shape: BoxShape.circle,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${voice.pingMs.toStringAsFixed(0)}ms RTC (UDP SFU)',
                      style: TextStyle(color: pingColor, fontSize: 11),
                    ),
                  ],
                ),
            ],
          ),
          const Spacer(),

          // Local Mute Button
          IconButton(
            icon: Icon(
              voice.selfMuted ? Icons.mic_off : Icons.mic,
              color: voice.selfMuted ? AppTheme.dangerRed : AppTheme.textPrimary,
              size: 20,
            ),
            tooltip: voice.selfMuted ? 'Unmute Microphone' : 'Mute Microphone',
            onPressed: () => voiceNotifier.toggleMute(),
          ),

          // Local Deafen Button
          IconButton(
            icon: Icon(
              voice.selfDeafened ? Icons.headset_off : Icons.headset,
              color: voice.selfDeafened ? AppTheme.dangerRed : AppTheme.textPrimary,
              size: 20,
            ),
            tooltip: voice.selfDeafened ? 'Undeafen' : 'Deafen',
            onPressed: () => voiceNotifier.toggleDeafen(),
          ),

          // Disconnect Button
          IconButton(
            icon: const Icon(Icons.call_end, color: AppTheme.dangerRed, size: 20),
            tooltip: 'Disconnect from Voice',
            onPressed: () => voiceNotifier.disconnect(),
          ),
        ],
      ),
    );
  }
}
