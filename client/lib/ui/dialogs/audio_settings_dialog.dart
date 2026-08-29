import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme.dart';
import '../../models/audio_device.dart';
import '../../services/ptt_service.dart';
import '../../state/settings_notifier.dart';

class AudioSettingsDialog extends ConsumerStatefulWidget {
  const AudioSettingsDialog({super.key});

  @override
  ConsumerState<AudioSettingsDialog> createState() => _AudioSettingsDialogState();
}

class _AudioSettingsDialogState extends ConsumerState<AudioSettingsDialog> {
  late TextEditingController _hostController;
  late TextEditingController _portController;
  bool _isListeningForHotkey = false;

  @override
  void initState() {
    super.initState();
    final settings = ref.read(settingsProvider);
    _hostController = TextEditingController(text: settings.serverHost);
    _portController = TextEditingController(text: settings.serverWsPort.toString());
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final settings = ref.watch(settingsProvider);
    final settingsNotifier = ref.read(settingsProvider.notifier);

    return Dialog(
      backgroundColor: AppTheme.backgroundElevated,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 580, maxHeight: 720),
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Dialog Header
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.settings_voice, color: AppTheme.primary, size: 24),
                      SizedBox(width: 10),
                      Text(
                        'Voice & Audio Settings',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ],
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
                    // Input Device Selection
                    const Text(
                      'INPUT DEVICE (MICROPHONE)',
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
                        child: DropdownButton<AudioDevice>(
                          value: settings.selectedInputDevice,
                          isExpanded: true,
                          dropdownColor: AppTheme.backgroundSurface,
                          items: settings.inputDevices.map((dev) {
                            return DropdownMenuItem<AudioDevice>(
                              value: dev,
                              child: Row(
                                children: [
                                  const Icon(Icons.mic, color: AppTheme.textMuted, size: 18),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      dev.name,
                                      style: const TextStyle(color: AppTheme.textPrimary),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  if (dev.isDefault)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: AppTheme.primary.withAlpha(50),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: const Text('DEFAULT', style: TextStyle(fontSize: 10, color: AppTheme.primary, fontWeight: FontWeight.bold)),
                                    ),
                                ],
                              ),
                            );
                          }).toList(),
                          onChanged: (dev) {
                            if (dev != null) settingsNotifier.setInputDevice(dev);
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Output Device Selection
                    const Text(
                      'OUTPUT DEVICE (SPEAKERS / HEADPHONES)',
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
                        child: DropdownButton<AudioDevice>(
                          value: settings.selectedOutputDevice,
                          isExpanded: true,
                          dropdownColor: AppTheme.backgroundSurface,
                          items: settings.outputDevices.map((dev) {
                            return DropdownMenuItem<AudioDevice>(
                              value: dev,
                              child: Row(
                                children: [
                                  const Icon(Icons.headphones, color: AppTheme.textMuted, size: 18),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      dev.name,
                                      style: const TextStyle(color: AppTheme.textPrimary),
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  if (dev.isDefault)
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: AppTheme.primary.withAlpha(50),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: const Text('DEFAULT', style: TextStyle(fontSize: 10, color: AppTheme.primary, fontWeight: FontWeight.bold)),
                                    ),
                                ],
                              ),
                            );
                          }).toList(),
                          onChanged: (dev) {
                            if (dev != null) settingsNotifier.setOutputDevice(dev);
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),

                    // ==========================================
                    // MIC TEST SECTION (Feature Deliverable)
                    // ==========================================
                    _buildMicTestCard(settings, settingsNotifier),

                    const SizedBox(height: 20),

                    // Input Mode Selection
                    const Text(
                      'INPUT ACTIVATION MODE',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textMuted,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: InkWell(
                            onTap: () => settingsNotifier.setActivationMode(InputActivationMode.voiceActivity),
                            child: Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: settings.activationMode == InputActivationMode.voiceActivity
                                    ? AppTheme.primary.withAlpha(50)
                                    : AppTheme.backgroundSurface,
                                border: Border.all(
                                  color: settings.activationMode == InputActivationMode.voiceActivity
                                      ? AppTheme.primary
                                      : Colors.transparent,
                                ),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.mic, color: AppTheme.primary, size: 18),
                                  SizedBox(width: 8),
                                  Flexible(child: Text('Voice Activity', style: TextStyle(color: AppTheme.textPrimary, fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis)),
                                ],
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: InkWell(
                            onTap: () => settingsNotifier.setActivationMode(InputActivationMode.pushToTalk),
                            child: Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: settings.activationMode == InputActivationMode.pushToTalk
                                    ? AppTheme.primary.withAlpha(50)
                                    : AppTheme.backgroundSurface,
                                border: Border.all(
                                  color: settings.activationMode == InputActivationMode.pushToTalk
                                      ? AppTheme.primary
                                      : Colors.transparent,
                                ),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.touch_app, color: AppTheme.primary, size: 18),
                                  SizedBox(width: 8),
                                  Flexible(child: Text('Push-to-Talk', style: TextStyle(color: AppTheme.textPrimary, fontWeight: FontWeight.w600), overflow: TextOverflow.ellipsis)),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),

                    // VAD Sensitivity Slider or PTT Keybind
                    if (settings.activationMode == InputActivationMode.voiceActivity) ...[
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Text(
                            'VAD SENSITIVITY THRESHOLD',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                              color: AppTheme.textMuted,
                              letterSpacing: 0.5,
                            ),
                          ),
                          Text(
                            '${settings.vadThresholdDb.toStringAsFixed(1)} dBFS',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: AppTheme.speakingGreen,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Slider(
                        value: settings.vadThresholdDb,
                        min: -70.0,
                        max: -10.0,
                        divisions: 60,
                        activeColor: AppTheme.primary,
                        inactiveColor: AppTheme.backgroundSurface,
                        label: '${settings.vadThresholdDb.toStringAsFixed(1)} dBFS',
                        onChanged: (val) => settingsNotifier.setVadThreshold(val),
                      ),
                    ] else ...[
                      const Text(
                        'PUSH-TO-TALK SHORTCUT',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.textMuted,
                          letterSpacing: 0.5,
                        ),
                      ),
                      const SizedBox(height: 8),
                      KeyboardListener(
                        focusNode: FocusNode(),
                        onKeyEvent: (event) {
                          if (_isListeningForHotkey && event is KeyDownEvent) {
                            settingsNotifier.setPttHotkey(event.logicalKey);
                            setState(() => _isListeningForHotkey = false);
                          }
                        },
                        child: InkWell(
                          onTap: () => setState(() => _isListeningForHotkey = true),
                          child: Container(
                            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                            decoration: BoxDecoration(
                              color: AppTheme.backgroundSurface,
                              border: Border.all(
                                color: _isListeningForHotkey ? AppTheme.primary : Colors.transparent,
                                width: 1.5,
                              ),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text(
                                  _isListeningForHotkey
                                      ? 'Press a key...'
                                      : settings.pttHotkey.keyLabel,
                                  style: TextStyle(
                                    color: _isListeningForHotkey ? AppTheme.primary : AppTheme.textPrimary,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const Icon(Icons.keyboard, color: AppTheme.textMuted),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),

                    // Server Configuration
                    const Text(
                      'SERVER CONNECTION',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textMuted,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          flex: 3,
                          child: TextField(
                            controller: _hostController,
                            decoration: const InputDecoration(labelText: 'Host / IP'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          flex: 2,
                          child: TextField(
                            controller: _portController,
                            decoration: const InputDecoration(labelText: 'WS Port'),
                            keyboardType: TextInputType.number,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Close', style: TextStyle(color: AppTheme.textMuted)),
                  ),
                  const SizedBox(width: 12),
                  ElevatedButton(
                    onPressed: () {
                      final port = int.tryParse(_portController.text) ?? 8080;
                      settingsNotifier.setServerEndpoint(_hostController.text, port);
                      Navigator.of(context).pop();
                    },
                    child: const Text('Save Changes'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildMicTestCard(SettingsState settings, SettingsNotifier settingsNotifier) {
    final isTesting = settings.isTestingMic;
    final levelDb = settings.micTestInputLevelDb;
    final isSpeaking = settings.isMicSpeaking;

    // Normalize level (-70 dBFS to 0 dBFS) into 0.0 to 1.0
    final normalizedLevel = isTesting
        ? ((levelDb + 70.0) / 70.0).clamp(0.0, 1.0)
        : 0.0;

    // Threshold position (normalized)
    final thresholdPosition = ((settings.vadThresholdDb + 70.0) / 70.0).clamp(0.0, 1.0);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppTheme.backgroundSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isTesting ? AppTheme.primary.withAlpha(150) : AppTheme.dividerColor,
          width: 1.5,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'MIC TEST',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textPrimary,
                        letterSpacing: 0.5,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      isTesting
                          ? 'Audio loopback active. Speak to hear yourself.'
                          : 'Having mic issues? Test and verify your audio.',
                      style: const TextStyle(fontSize: 11, color: AppTheme.textMuted),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              ElevatedButton.icon(
                key: const Key('mic_test_toggle_button'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: isTesting ? AppTheme.dangerRed : AppTheme.primary,
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                ),
                icon: Icon(isTesting ? Icons.stop : Icons.mic, size: 16),
                label: Text(isTesting ? 'Stop Testing' : 'Test Mic'),
                onPressed: () => settingsNotifier.toggleMicTest(),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Animated VU Meter Bar
          Stack(
            children: [
              // Background track
              Container(
                height: 16,
                width: double.infinity,
                decoration: BoxDecoration(
                  color: const Color(0xFF1E1F22),
                  borderRadius: BorderRadius.circular(4),
                ),
              ),

              // Animated Level Bar
              FractionallySizedBox(
                widthFactor: normalizedLevel,
                child: Container(
                  height: 16,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(4),
                    gradient: LinearGradient(
                      colors: isSpeaking
                          ? [AppTheme.speakingGreen, const Color(0xFF2ECC71), const Color(0xFFF1C40F)]
                          : [const Color(0xFF4E5058), const Color(0xFF72767D)],
                    ),
                  ),
                ),
              ),

              // VAD Threshold Marker Line
              Align(
                alignment: Alignment((thresholdPosition * 2.0 - 1.0).clamp(-1.0, 1.0), 0.0),
                child: Container(
                  width: 2.5,
                  height: 16,
                  color: Colors.white.withAlpha(220),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),

          // Level readout and speaking status
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: isTesting
                          ? (isSpeaking ? AppTheme.speakingGreen : AppTheme.warningYellow)
                          : AppTheme.textMuted,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    isTesting
                        ? (isSpeaking
                            ? 'Voice Detected (Speaking)'
                            : (levelDb > -80 ? 'Listening for voice...' : 'Quiet / No Input'))
                        : 'Click "Test Mic" to start testing',
                    style: TextStyle(
                      fontSize: 11,
                      color: isTesting && isSpeaking ? AppTheme.speakingGreen : AppTheme.textMuted,
                      fontWeight: isSpeaking ? FontWeight.bold : FontWeight.normal,
                    ),
                  ),
                ],
              ),
              Text(
                isTesting ? '${levelDb.toStringAsFixed(1)} dBFS' : '- dBFS',
                style: const TextStyle(fontSize: 11, color: AppTheme.textMuted, fontFamily: 'monospace'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
