import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:low_latency_voice_app/core/theme.dart';
import 'package:low_latency_voice_app/main.dart';
import 'package:low_latency_voice_app/models/channel.dart';
import 'package:low_latency_voice_app/models/user.dart';
import 'package:low_latency_voice_app/state/auth_notifier.dart';
import 'package:low_latency_voice_app/state/channels_notifier.dart';
import 'package:low_latency_voice_app/state/voice_notifier.dart';
import 'package:low_latency_voice_app/ui/channels_pane.dart';
import 'package:low_latency_voice_app/ui/chat_pane.dart';
import 'package:low_latency_voice_app/ui/dialogs/admin_mod_dialog.dart';
import 'package:low_latency_voice_app/ui/dialogs/audio_settings_dialog.dart';
import 'package:low_latency_voice_app/ui/main_layout.dart';
import 'package:low_latency_voice_app/ui/roster_pane.dart';
import 'package:low_latency_voice_app/ui/voice_hud.dart';

void main() {
  testWidgets('App renders login screen when unauthenticated', (WidgetTester tester) async {
    await tester.pumpWidget(
      const ProviderScope(
        child: VoiceApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Welcome Back!'), findsOneWidget);
    expect(find.text('USERNAME'), findsOneWidget);
    expect(find.text('PASSWORD'), findsOneWidget);
    expect(find.byType(ElevatedButton), findsOneWidget);
  });

  testWidgets('MainLayout renders 3-pane layout when authenticated', (WidgetTester tester) async {
    const mockUser = User(
      id: 1,
      username: 'TestAdmin',
      isAdmin: true,
      roles: ['admin'],
      permissions: 0xFFFFFFFF,
    );

    await tester.binding.setSurfaceSize(const Size(1280, 720));

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authProvider.overrideWith((ref) {
            final ws = ref.watch(webSocketServiceProvider);
            final notifier = AuthNotifier(ws);
            notifier.state = const AuthState(isAuthenticated: true, user: mockUser);
            return notifier;
          }),
          channelsProvider.overrideWith((ref) {
            final ws = ref.watch(webSocketServiceProvider);
            final notifier = ChannelsNotifier(ws);
            notifier.state = const ChannelsState(
              channels: [
                Channel(id: 1, name: 'general', type: 'text'),
                Channel(id: 2, name: 'Squad-Alpha', type: 'voice'),
              ],
              selectedTextChannelId: 1,
            );
            return notifier;
          }),
        ],
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: const MainLayout(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Verify 3 panes are present
    expect(find.byType(ChannelsPane), findsOneWidget);
    expect(find.byType(ChatPane), findsOneWidget);
    expect(find.byType(RosterPane), findsOneWidget);

    // Verify channel tree content
    expect(find.text('TEXT CHANNELS'), findsOneWidget);
    expect(find.text('VOICE CHANNELS'), findsOneWidget);
    expect(find.text('general'), findsWidgets);
    expect(find.text('Squad-Alpha'), findsOneWidget);
  });

  testWidgets('AudioSettingsDialog renders mic test card and toggles test state', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 900));
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: Center(
              child: AudioSettingsDialog(),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Voice & Audio Settings'), findsOneWidget);
    expect(find.text('INPUT DEVICE (MICROPHONE)'), findsOneWidget);
    expect(find.text('OUTPUT DEVICE (SPEAKERS / HEADPHONES)'), findsOneWidget);
    expect(find.text('MIC TEST'), findsOneWidget);
    expect(find.text('Test Mic'), findsOneWidget);
    expect(find.text('Voice Activity'), findsOneWidget);
    expect(find.text('Push-to-Talk'), findsOneWidget);

    // Tap "Test Mic" button
    final testMicButton = find.byKey(const Key('mic_test_toggle_button'));
    expect(testMicButton, findsOneWidget);
    await tester.tap(testMicButton);
    await tester.pump(const Duration(milliseconds: 50));

    // Should now show "Stop Testing"
    expect(find.text('Stop Testing'), findsOneWidget);

    // Tap again to stop
    await tester.tap(testMicButton);
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('Test Mic'), findsOneWidget);
  });

  testWidgets('VoiceHud renders live audio connection status and transmitting indicator', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          voiceProvider.overrideWith((ref) {
            final ws = ref.watch(webSocketServiceProvider);
            final client = ref.watch(voiceClientProvider);
            final engine = ref.watch(audioEngineProvider);
            final notifier = VoiceNotifier(ws, client, engine, ref);
            notifier.state = const VoiceStateModel(
              status: VoiceConnectionStatus.connected,
              connectedChannelId: 2,
              connectedChannelName: 'Squad-Alpha',
              pingMs: 12.0,
              isLocalSpeaking: true,
              localInputLevelDb: -18.5,
            );
            return notifier;
          }),
        ],
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: VoiceHud(),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Voice Connected / Squad-Alpha'), findsOneWidget);
    expect(find.text('TRANSMITTING'), findsOneWidget);
    expect(find.text('12ms RTC (UDP SFU)'), findsOneWidget);
  });

  testWidgets('AdminModDialog displays user moderation options', (WidgetTester tester) async {
    const targetUser = UserProfile(
      userId: 2,
      username: 'TargetUser',
      roles: ['member'],
      online: true,
    );

    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: const Scaffold(
            body: AdminModDialog(targetUser: targetUser),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Moderation: TargetUser'), findsOneWidget);
    expect(find.text('Server Mute'), findsOneWidget);
    expect(find.text('Server Deafen'), findsOneWidget);
    expect(find.text('Kick User Immediately'), findsOneWidget);
  });
}
