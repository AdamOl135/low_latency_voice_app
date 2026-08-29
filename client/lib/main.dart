import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/theme.dart';
import 'ui/main_layout.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    const ProviderScope(
      child: VoiceApp(),
    ),
  );
}

class VoiceApp extends StatelessWidget {
  const VoiceApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'VoiceHQ - Low Latency Voice & Text',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      home: const MainLayout(),
    );
  }
}
