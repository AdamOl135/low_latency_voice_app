import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:low_latency_voice_app/core/constants.dart';
import 'package:low_latency_voice_app/services/ptt_service.dart';
import 'package:low_latency_voice_app/services/vad_service.dart';
import 'package:low_latency_voice_app/services/voice_client.dart';

void main() {
  group('UDP Wire Protocol Serialization Tests', () {
    test('VoicePacket encode and decode roundtrip with VAD and energy level', () {
      final payload = Uint8List.fromList([0x12, 0x34, 0x56, 0x78, 0x9A]);
      final originalPacket = VoicePacket(
        magic: AppConstants.udpMagicByte,
        version: AppConstants.udpProtocolVersion,
        type: AppConstants.packetTypeVoice,
        vad: true,
        energyLevel: 12,
        senderId: 42,
        channelId: 101,
        sequence: 1337,
        timestamp: 48000,
        payload: payload,
      );

      final encoded = originalPacket.encode();
      expect(encoded.length, equals(AppConstants.udpHeaderSize + payload.length));

      // Header checks
      expect(encoded[0], equals(0x56)); // Magic 'V'
      expect(encoded[1], equals(0x01)); // Version 1
      expect(encoded[2], equals(0x01)); // Type Voice
      expect(encoded[3] & AppConstants.flagVad, equals(AppConstants.flagVad)); // VAD bit
      expect((encoded[3] & AppConstants.flagEnergyMask) >> 4, equals(12)); // Energy level 12

      final decoded = VoicePacket.decode(encoded);
      expect(decoded.magic, equals(AppConstants.udpMagicByte));
      expect(decoded.version, equals(AppConstants.udpProtocolVersion));
      expect(decoded.type, equals(AppConstants.packetTypeVoice));
      expect(decoded.vad, isTrue);
      expect(decoded.energyLevel, equals(12));
      expect(decoded.senderId, equals(42));
      expect(decoded.channelId, equals(101));
      expect(decoded.sequence, equals(1337));
      expect(decoded.timestamp, equals(48000));
      expect(decoded.payload, equals(payload));
    });

    test('HandshakePacket encode and decode with token payload', () {
      const token = 'test_udp_session_token_xyz';
      final tokenBytes = Uint8List.fromList(utf8.encode(token));
      final packet = VoicePacket(
        type: AppConstants.packetTypeHandshake,
        senderId: 5,
        channelId: 202,
        sequence: 1,
        timestamp: 1724930000,
        payload: tokenBytes,
      );

      final encoded = packet.encode();
      final decoded = VoicePacket.decode(encoded);

      expect(decoded.type, equals(AppConstants.packetTypeHandshake));
      expect(decoded.senderId, equals(5));
      expect(decoded.channelId, equals(202));
      expect(utf8.decode(decoded.payload), equals(token));
    });

    test('Decode throws FormatException on truncated packet', () {
      final shortData = Uint8List(10); // Less than 20 bytes
      expect(() => VoicePacket.decode(shortData), throwsFormatException);
    });
  });

  group('VAD Service Energy & Hangover Logic Tests', () {
    late VadService vad;

    setUp(() {
      vad = VadService();
      vad.setThreshold(-45.0);
      vad.setHangoverMs(100);
    });

    tearDown(() {
      vad.dispose();
    });

    test('Silence PCM produces energy below threshold and speaking = false', () {
      // 960 samples of silence (0)
      final silenceSamples = Int16List(AppConstants.frameSamples);
      final isSpeaking = vad.processPcmFrame(silenceSamples);

      expect(isSpeaking, isFalse);
      expect(vad.lastEnergyDb, equals(-90.0));
      expect(vad.lastEnergyLevel, equals(0));
    });

    test('Active speech PCM crosses -45dBFS threshold triggering speaking = true', () {
      // 960 samples of active wave (amplitude ~8000, RMS ~5656 -> ~ -15.2 dBFS)
      final speechSamples = Int16List(AppConstants.frameSamples);
      for (var i = 0; i < speechSamples.length; i++) {
        speechSamples[i] = (i % 2 == 0) ? 8000 : -8000;
      }

      final isSpeaking = vad.processPcmFrame(speechSamples);
      expect(isSpeaking, isTrue);
      expect(vad.lastEnergyDb, greaterThan(-45.0));
      expect(vad.lastEnergyLevel, greaterThan(5));
    });

    test('Hangover timer holds speaking state after brief drop below threshold', () async {
      final speechSamples = Int16List(AppConstants.frameSamples);
      for (var i = 0; i < speechSamples.length; i++) {
        speechSamples[i] = 10000;
      }
      vad.processPcmFrame(speechSamples);
      expect(vad.isSpeaking, isTrue);

      // Now feed silence - should remain true immediately due to hangover
      final silenceSamples = Int16List(AppConstants.frameSamples);
      final duringHangover = vad.processPcmFrame(silenceSamples);
      expect(duringHangover, isTrue);

      // Wait for hangover to expire (100ms + margin)
      await Future.delayed(const Duration(milliseconds: 150));
      expect(vad.isSpeaking, isFalse);
    });
  });

  group('PTT Service Hotkey Tests', () {
    late PttService ptt;

    setUp(() {
      ptt = PttService();
      ptt.setMode(InputActivationMode.pushToTalk);
      ptt.setHotkey(LogicalKeyboardKey.space);
    });

    tearDown(() {
      ptt.dispose();
    });

    test('PTT state updates on key down and key up', () {
      final states = <bool>[];
      ptt.pttStateStream.listen(states.add);

      ptt.handleKeyEvent(const KeyDownEvent(
        physicalKey: PhysicalKeyboardKey.space,
        logicalKey: LogicalKeyboardKey.space,
        timeStamp: Duration.zero,
      ));
      expect(ptt.isPressed, isTrue);

      ptt.handleKeyEvent(const KeyUpEvent(
        physicalKey: PhysicalKeyboardKey.space,
        logicalKey: LogicalKeyboardKey.space,
        timeStamp: Duration.zero,
      ));
      expect(ptt.isPressed, isFalse);
    });

    test('PTT ignores keys when mode is Voice Activity', () {
      ptt.setMode(InputActivationMode.voiceActivity);

      final handled = ptt.handleKeyEvent(const KeyDownEvent(
        physicalKey: PhysicalKeyboardKey.space,
        logicalKey: LogicalKeyboardKey.space,
        timeStamp: Duration.zero,
      ));
      expect(handled, isFalse);
      expect(ptt.isPressed, isFalse);
    });
  });
}
