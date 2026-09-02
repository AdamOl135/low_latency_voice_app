import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:low_latency_voice_app/core/constants.dart';
import 'package:low_latency_voice_app/core/theme.dart';
import 'package:low_latency_voice_app/main.dart';
import 'package:low_latency_voice_app/models/channel.dart';
import 'package:low_latency_voice_app/models/user.dart';
import 'package:low_latency_voice_app/state/auth_notifier.dart';
import 'package:low_latency_voice_app/state/channels_notifier.dart';
import 'package:low_latency_voice_app/state/roster_notifier.dart';
import 'package:low_latency_voice_app/state/settings_notifier.dart';
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
    await tester.pumpAndSettle();
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

  testWidgets('AudioSettingsDialog stops mic test on pop/dispose (R2)', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 900));
    final container = ProviderContainer();

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: MaterialApp(
          theme: AppTheme.darkTheme,
          home: Builder(
            builder: (context) => Scaffold(
              body: Center(
                child: ElevatedButton(
                  onPressed: () {
                    showDialog(
                      context: context,
                      builder: (_) => const AudioSettingsDialog(),
                    );
                  },
                  child: const Text('Open Settings'),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Open settings dialog
    await tester.tap(find.text('Open Settings'));
    await tester.pumpAndSettle();

    // Start mic test
    final testMicButton = find.byKey(const Key('mic_test_toggle_button'));
    await tester.tap(testMicButton);
    await tester.pump(const Duration(milliseconds: 50));
    expect(container.read(settingsProvider).isTestingMic, isTrue);

    // Close the dialog via close button (which calls pop and triggers dispose)
    final closeButton = find.byIcon(Icons.close);
    await tester.tap(closeButton);
    await tester.pumpAndSettle();

    // Verify mic test is stopped upon dialog disposal
    expect(container.read(settingsProvider).isTestingMic, isFalse);
    container.dispose();
  });

  testWidgets('ChannelsPane and RosterPane render green speaking halo ring when peer is speaking (R3)', (WidgetTester tester) async {
    const mockUser = User(
      id: 1,
      username: 'Alice',
      isAdmin: true,
      roles: ['admin'],
      permissions: 0xFFFFFFFF,
    );

    const peerProfile = UserProfile(
      userId: 2,
      username: 'Bob',
      roles: ['member'],
      online: true,
      voiceChannelId: 2,
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
                Channel(id: 2, name: 'Voice-Lounge', type: 'voice'),
              ],
              selectedVoiceChannelId: 2,
              voiceOccupants: {2: [2]},
            );
            return notifier;
          }),
          rosterProvider.overrideWith((ref) {
            final ws = ref.watch(webSocketServiceProvider);
            final notifier = RosterNotifier(ws);
            notifier.state = const RosterState(
              members: [
                UserProfile(userId: 1, username: 'Alice', online: true),
                peerProfile,
              ],
            );
            return notifier;
          }),
          voiceProvider.overrideWith((ref) {
            final ws = ref.watch(webSocketServiceProvider);
            final client = ref.watch(voiceClientProvider);
            final engine = ref.watch(audioEngineProvider);
            final notifier = VoiceNotifier(ws, client, engine, ref);
            notifier.state = const VoiceStateModel(
              status: VoiceConnectionStatus.connected,
              connectedChannelId: 2,
              connectedChannelName: 'Voice-Lounge',
              speakingUsers: {2: true}, // Bob is actively speaking
              userEnergyLevels: {2: 14},
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

    // Verify Bob is rendered in ChannelsPane and RosterPane
    expect(find.text('Bob'), findsWidgets);

    // Verify speaking halo styling: Look for Container with speakingGreen border
    final greenBorders = tester.widgetList<Container>(find.byType(Container)).where((container) {
      final decoration = container.decoration;
      if (decoration is BoxDecoration && decoration.border is Border) {
        final border = decoration.border as Border;
        return border.top.color == AppTheme.speakingGreen;
      }
      return false;
    });

    expect(greenBorders.length, greaterThanOrEqualTo(2)); // Present in both ChannelsPane and RosterPane
  });

  testWidgets('AudioSettingsDialog falls back to AppConstants.defaultWsPort on invalid port (R4)', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 1000));
    final container = ProviderContainer();

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
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

    // Scroll down the ListView to bring server settings into view
    await tester.drag(find.byType(ListView), const Offset(0, -400));
    await tester.pumpAndSettle();

    final textFields = find.byType(TextField);
    expect(textFields, findsNWidgets(2));
    final portField = textFields.at(1);

    // Clear port input to test fallback
    await tester.enterText(portField, '');
    await tester.pumpAndSettle();

    // Tap Save Changes
    final saveButton = find.widgetWithText(ElevatedButton, 'Save Changes');
    expect(saveButton, findsOneWidget);
    await tester.tap(saveButton);
    await tester.pumpAndSettle();

    // Verify settingsNotifier received AppConstants.defaultWsPort (8085)
    expect(container.read(settingsProvider).serverWsPort, equals(AppConstants.defaultWsPort));
    expect(container.read(settingsProvider).serverWsPort, equals(8085));

    container.dispose();
  });

  testWidgets('Login button with empty username or password shows validation error message', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(
      const ProviderScope(
        child: VoiceApp(),
      ),
    );
    await tester.pumpAndSettle();

    // Clear username and password
    final textFields = find.byType(TextField);
    await tester.enterText(textFields.at(0), '');
    await tester.enterText(textFields.at(1), '');
    await tester.pumpAndSettle();

    // Tap Log In button
    final loginButton = find.widgetWithText(ElevatedButton, 'Log In');
    expect(loginButton, findsOneWidget);
    await tester.tap(loginButton);
    await tester.pumpAndSettle();

    // Expect validation error message to be displayed on screen
    expect(find.text('Please enter both username and password.'), findsOneWidget);
  });

  testWidgets('Server settings toggle reveals host/port inputs and helper chips', (WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 720));
    await tester.pumpWidget(
      const ProviderScope(
        child: VoiceApp(),
      ),
    );
    await tester.pumpAndSettle();

    // Tap server settings dropdown
    final serverDropdown = find.textContaining('Server:');
    expect(serverDropdown, findsOneWidget);
    await tester.tap(serverDropdown);
    await tester.pumpAndSettle();

    // Expect SERVER HOST and PORT textfields to appear
    expect(find.text('SERVER HOST'), findsOneWidget);
    expect(find.text('PORT'), findsOneWidget);
    expect(find.widgetWithText(ActionChip, 'Localhost'), findsOneWidget);
    expect(find.widgetWithText(ActionChip, 'Default Server'), findsOneWidget);

    // Tap Localhost chip
    await tester.tap(find.widgetWithText(ActionChip, 'Localhost'));
    await tester.pumpAndSettle();

    // Verify Server text reflects 127.0.0.1:8085
    expect(find.text('Server: 127.0.0.1:8085'), findsOneWidget);

    // Tap Default Server chip
    await tester.tap(find.widgetWithText(ActionChip, 'Default Server'));
    await tester.pumpAndSettle();

    expect(find.text('Server: ${AppConstants.defaultHost}:${AppConstants.defaultWsPort}'), findsOneWidget);
  });
}
