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

    final isTransmitting = voice.isConnected && voice.isLocalSpeaking && !voice.isMuted;

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
          // Connection Status Icon with speaking pulse
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isTransmitting
                  ? AppTheme.speakingGreen.withAlpha(40)
                  : (voice.isConnected ? AppTheme.speakingGreen.withAlpha(20) : AppTheme.warningYellow.withAlpha(20)),
              border: Border.all(
                color: isTransmitting ? AppTheme.speakingGreen : Colors.transparent,
                width: 1.5,
              ),
            ),
            child: Icon(
              voice.isConnected ? Icons.sensors : Icons.sensors_off,
              color: voice.isConnected ? AppTheme.speakingGreen : AppTheme.warningYellow,
              size: 18,
            ),
          ),
          const SizedBox(width: 12),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
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
                  if (isTransmitting) ...[
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                        color: AppTheme.speakingGreen.withAlpha(40),
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(color: AppTheme.speakingGreen, width: 1),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.mic, size: 10, color: AppTheme.speakingGreen),
                          SizedBox(width: 3),
                          Text(
                            'TRANSMITTING',
                            style: TextStyle(
                              fontSize: 9,
                              fontWeight: FontWeight.bold,
                              color: AppTheme.speakingGreen,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
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
                    if (voice.localInputLevelDb > -80.0 && !voice.isMuted) ...[
                      const SizedBox(width: 10),
                      Text(
                        '${voice.localInputLevelDb.toStringAsFixed(1)} dBFS',
                        style: const TextStyle(color: AppTheme.textMuted, fontSize: 10, fontFamily: 'monospace'),
                      ),
                    ],
                  ],
                ),
            ],
          ),
          const Spacer(),

          // Live audio waveform bar (visual feedback that audio is working)
          if (voice.isConnected && !voice.isMuted)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: _buildLiveWaveform(voice.localInputLevelDb, voice.isLocalSpeaking),
            ),

          // Local Mute Button
          IconButton(
            icon: Icon(
              voice.selfMuted ? Icons.mic_off : Icons.mic,
              color: voice.selfMuted ? AppTheme.dangerRed : (isTransmitting ? AppTheme.speakingGreen : AppTheme.textPrimary),
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

  Widget _buildLiveWaveform(double dbfs, bool isSpeaking) {
    final normalized = ((dbfs + 70.0) / 70.0).clamp(0.1, 1.0);
    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        _buildBar(normalized * 14.0, isSpeaking),
        const SizedBox(width: 2),
        _buildBar(normalized * 20.0, isSpeaking),
        const SizedBox(width: 2),
        _buildBar(normalized * 12.0, isSpeaking),
        const SizedBox(width: 2),
        _buildBar(normalized * 18.0, isSpeaking),
      ],
    );
  }

  Widget _buildBar(double height, bool isSpeaking) {
    return Container(
      width: 3,
      height: height.clamp(3.0, 20.0),
      decoration: BoxDecoration(
        color: isSpeaking ? AppTheme.speakingGreen : AppTheme.textMuted.withAlpha(100),
        borderRadius: BorderRadius.circular(1.5),
      ),
    );
  }
}
