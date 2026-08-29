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
        constraints: const BoxConstraints(maxWidth: 540, maxHeight: 680),
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Expanded(
                    child: Text(
                      'Voice & Audio Settings',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.textPrimary,
                      ),
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
                    // Input Device
                    const Text(
                      'INPUT DEVICE',
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
                              child: Text(dev.name, style: const TextStyle(color: AppTheme.textPrimary)),
                            );
                          }).toList(),
                          onChanged: (dev) {
                            if (dev != null) settingsNotifier.setInputDevice(dev);
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Output Device
                    const Text(
                      'OUTPUT DEVICE',
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
                              child: Text(dev.name, style: const TextStyle(color: AppTheme.textPrimary)),
                            );
                          }).toList(),
                          onChanged: (dev) {
                            if (dev != null) settingsNotifier.setOutputDevice(dev);
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Input Mode
                    const Text(
                      'INPUT MODE',
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
                                  SizedBox(width: 6),
                                  Flexible(child: Text('Voice Activity', style: TextStyle(color: AppTheme.textPrimary), overflow: TextOverflow.ellipsis)),
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
                                  SizedBox(width: 6),
                                  Flexible(child: Text('Push-to-Talk', style: TextStyle(color: AppTheme.textPrimary), overflow: TextOverflow.ellipsis)),
                                ],
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),

                    // VAD Slider or PTT Keybind
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
                      Slider(
                        value: settings.vadThresholdDb,
                        min: -70.0,
                        max: -10.0,
                        divisions: 60,
                        label: '${settings.vadThresholdDb.toStringAsFixed(1)} dB',
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
                    child: const Text('Cancel', style: TextStyle(color: AppTheme.textMuted)),
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
}
