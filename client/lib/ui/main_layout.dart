import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/constants.dart';
import '../../core/theme.dart';
import '../../services/websocket_service.dart';
import '../../state/auth_notifier.dart';
import '../../state/channels_notifier.dart';
import '../../state/roster_notifier.dart';
import '../../state/settings_notifier.dart';
import 'channels_pane.dart';
import 'chat_pane.dart';
import 'roster_pane.dart';

class MainLayout extends ConsumerStatefulWidget {
  const MainLayout({super.key});

  @override
  ConsumerState<MainLayout> createState() => _MainLayoutState();
}

class _MainLayoutState extends ConsumerState<MainLayout> {
  bool _showRoster = true;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  // Auth controllers
  final TextEditingController _usernameController = TextEditingController(text: 'Admin');
  final TextEditingController _passwordController = TextEditingController(text: 'admin123456');
  final TextEditingController _hostController = TextEditingController(text: AppConstants.defaultHost);
  final TextEditingController _portController = TextEditingController(text: '${AppConstants.defaultWsPort}');
  bool _isRegistering = false;
  bool _showServerSettings = false;

  @override
  void initState() {
    super.initState();
    // Auto-login or bootstrap session
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final settingsNotifier = ref.read(settingsProvider.notifier);
      await settingsNotifier.loadPersistedSettings();
      if (mounted) {
        final settings = ref.read(settingsProvider);
        setState(() {
          _hostController.text = settings.serverHost;
          _portController.text = '${settings.serverWsPort}';
        });
      }

      await ref.read(authProvider.notifier).checkSavedSession();
      if (mounted && ref.read(authProvider).isAuthenticated) {
        ref.read(channelsProvider.notifier).fetchChannels();
        ref.read(rosterProvider.notifier).fetchRoster();
      }
    });
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  void _onLoginOrRegister() async {
    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();
    final authNotifier = ref.read(authProvider.notifier);

    if (username.isEmpty || password.isEmpty) {
      authNotifier.setErrorMessage('Please enter both username and password.');
      return;
    }

    final rawHost = _hostController.text.trim().isNotEmpty
        ? _hostController.text.trim()
        : AppConstants.defaultHost;
    final rawPort = int.tryParse(_portController.text.trim()) ?? AppConstants.defaultWsPort;

    final parsed = WebSocketService.parseEndpoint(rawHost, rawPort);
    _hostController.text = parsed.host;
    _portController.text = '${parsed.port}';

    await ref.read(settingsProvider.notifier).setServerEndpoint(parsed.host, parsed.port);
    ref.read(webSocketServiceProvider).configure(host: parsed.host, port: parsed.port);

    try {
      bool success;
      if (_isRegistering) {
        success = await authNotifier.register(username, password);
      } else {
        success = await authNotifier.login(username, password);
      }

      if (success) {
        ref.read(channelsProvider.notifier).fetchChannels();
        ref.read(rosterProvider.notifier).fetchRoster();
      } else {
        final error = ref.read(authProvider).errorMessage ?? '';
        if (error.contains('reach voice server') ||
            error.contains('Could not connect') ||
            error.contains('WebSocket is not connected')) {
          if (mounted) setState(() => _showServerSettings = true);
        }
      }
    } catch (e) {
      authNotifier.setErrorMessage('Login failed: ${e.toString().replaceAll('Exception: ', '')}');
      if (mounted) setState(() => _showServerSettings = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    if (!authState.isAuthenticated) {
      return _buildAuthScreen(context, authState);
    }

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: AppTheme.backgroundDarkest,
      endDrawer: const Drawer(
        child: RosterPane(),
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth;
          final isNarrow = width < AppConstants.breakpointCollapseRoster;
          final isVeryNarrow = width < AppConstants.breakpointCollapseChannels;

          return Row(
            children: [
              // 1. Left Channels Pane (240px)
              if (!isVeryNarrow) const ChannelsPane(),

              // 2. Center Content Pane (Flexible)
              Expanded(
                child: ChatPane(
                  onToggleRoster: isNarrow
                      ? () => _scaffoldKey.currentState?.openEndDrawer()
                      : () => setState(() => _showRoster = !_showRoster),
                ),
              ),

              // 3. Right Live Member Roster (220px)
              if (!isNarrow && _showRoster) const RosterPane(),
            ],
          );
        },
      ),
    );
  }

  Widget _buildAuthScreen(BuildContext context, AuthState auth) {
    return Scaffold(
      backgroundColor: AppTheme.backgroundDarkest,
      body: Center(
        child: SingleChildScrollView(
          child: Container(
            width: 420,
            padding: const EdgeInsets.all(32),
            decoration: BoxDecoration(
              color: AppTheme.backgroundElevated,
              borderRadius: BorderRadius.circular(8),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withAlpha(80),
                  blurRadius: 16,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                const Icon(Icons.hub, size: 48, color: AppTheme.primary),
                const SizedBox(height: 12),
                Text(
                  _isRegistering ? 'Create an Account' : 'Welcome Back!',
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  _isRegistering
                      ? 'Register to join the voice & chat server'
                      : 'We\'re so excited to see you again!',
                  style: const TextStyle(fontSize: 13, color: AppTheme.textMuted),
                ),
                const SizedBox(height: 24),

                if (auth.errorMessage != null)
                  Container(
                    padding: const EdgeInsets.all(10),
                    margin: const EdgeInsets.only(bottom: 16),
                    decoration: BoxDecoration(
                      color: AppTheme.dangerRed.withAlpha(40),
                      border: Border.all(color: AppTheme.dangerRed),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      auth.errorMessage!,
                      style: const TextStyle(color: Colors.white, fontSize: 13),
                    ),
                  ),

                TextField(
                  controller: _usernameController,
                  decoration: const InputDecoration(
                    labelText: 'USERNAME',
                    prefixIcon: Icon(Icons.person, color: AppTheme.textMuted),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'PASSWORD',
                    prefixIcon: Icon(Icons.lock, color: AppTheme.textMuted),
                  ),
                  onSubmitted: (_) => _onLoginOrRegister(),
                ),
                const SizedBox(height: 24),

                SizedBox(
                  width: double.infinity,
                  height: 44,
                  child: ElevatedButton(
                    onPressed: auth.isLoading ? null : _onLoginOrRegister,
                    child: auth.isLoading
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : Text(_isRegistering ? 'Register' : 'Log In'),
                  ),
                ),
                const SizedBox(height: 16),

                TextButton(
                  onPressed: () {
                    setState(() => _isRegistering = !_isRegistering);
                  },
                  child: Text(
                    _isRegistering
                      ? 'Already have an account? Log In'
                      : 'Need an account? Register',
                    style: const TextStyle(color: AppTheme.primary, fontSize: 13),
                  ),
                ),
                const SizedBox(height: 8),
                InkWell(
                  onTap: () => setState(() => _showServerSettings = !_showServerSettings),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          _showServerSettings ? Icons.arrow_drop_up : Icons.arrow_drop_down,
                          color: AppTheme.textMuted,
                          size: 18,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          'Server: ${_hostController.text.trim().isEmpty ? AppConstants.defaultHost : _hostController.text.trim()}:${_portController.text.trim().isEmpty ? AppConstants.defaultWsPort : _portController.text.trim()}',
                          style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                ),
                if (_showServerSettings) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        flex: 3,
                        child: TextField(
                          controller: _hostController,
                          onChanged: (_) => setState(() {}),
                          decoration: const InputDecoration(
                            labelText: 'SERVER HOST',
                            hintText: '127.0.0.1 or domain',
                            isDense: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        flex: 2,
                        child: TextField(
                          controller: _portController,
                          onChanged: (_) => setState(() {}),
                          decoration: const InputDecoration(
                            labelText: 'PORT',
                            hintText: '8085',
                            isDense: true,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      ActionChip(
                        label: const Text('Localhost', style: TextStyle(fontSize: 11)),
                        onPressed: () {
                          setState(() {
                            _hostController.text = '127.0.0.1';
                            _portController.text = '8085';
                          });
                        },
                      ),
                      const SizedBox(width: 8),
                      ActionChip(
                        label: const Text('Default Server', style: TextStyle(fontSize: 11)),
                        onPressed: () {
                          setState(() {
                            _hostController.text = AppConstants.defaultHost;
                            _portController.text = '${AppConstants.defaultWsPort}';
                          });
                        },
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
