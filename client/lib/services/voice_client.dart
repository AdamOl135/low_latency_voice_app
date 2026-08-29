import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import '../core/constants.dart';

/// Parsed inbound/outbound binary UDP voice packet.
class VoicePacket {
  final int magic;
  final int version;
  final int type;
  final int flags;
  final bool vad;
  final int energyLevel;
  final int senderId;
  final int channelId;
  final int sequence;
  final int timestamp;
  final Uint8List payload;

  const VoicePacket({
    this.magic = AppConstants.udpMagicByte,
    this.version = AppConstants.udpProtocolVersion,
    required this.type,
    this.flags = 0,
    this.vad = false,
    this.energyLevel = 0,
    required this.senderId,
    required this.channelId,
    required this.sequence,
    required this.timestamp,
    required this.payload,
  });

  /// Decodes raw datagram buffer into VoicePacket.
  factory VoicePacket.decode(Uint8List data) {
    if (data.length < AppConstants.udpHeaderSize) {
      throw const FormatException('UDP packet too short for 20-byte header');
    }

    final byteData = ByteData.sublistView(data);
    final magic = byteData.getUint8(0);
    final version = byteData.getUint8(1);
    final type = byteData.getUint8(2);
    final rawFlags = byteData.getUint8(3);

    final vad = (rawFlags & AppConstants.flagVad) != 0;
    final energyLevel = (rawFlags & AppConstants.flagEnergyMask) >> 4;

    final senderId = byteData.getUint32(4, Endian.big);
    final channelId = byteData.getUint32(8, Endian.big);
    final sequence = byteData.getUint16(12, Endian.big);
    final payloadLen = byteData.getUint16(14, Endian.big);
    final timestamp = byteData.getUint32(16, Endian.big);

    final expectedTotal = AppConstants.udpHeaderSize + payloadLen;
    if (data.length < expectedTotal) {
      throw FormatException(
        'UDP payload length mismatch: header=$payloadLen, actual=${data.length - AppConstants.udpHeaderSize}',
      );
    }

    final payload = data.sublist(AppConstants.udpHeaderSize, expectedTotal);

    return VoicePacket(
      magic: magic,
      version: version,
      type: type,
      flags: rawFlags,
      vad: vad,
      energyLevel: energyLevel,
      senderId: senderId,
      channelId: channelId,
      sequence: sequence,
      timestamp: timestamp,
      payload: payload,
    );
  }

  /// Encodes VoicePacket into 20-byte header + payload.
  Uint8List encode() {
    final totalLen = AppConstants.udpHeaderSize + payload.length;
    final buffer = Uint8List(totalLen);
    final byteData = ByteData.sublistView(buffer);

    byteData.setUint8(0, magic);
    byteData.setUint8(1, version);
    byteData.setUint8(2, type);

    var rawFlags = 0;
    if (vad) rawFlags |= AppConstants.flagVad;
    rawFlags |= (energyLevel & 0x0F) << 4;
    byteData.setUint8(3, rawFlags);

    byteData.setUint32(4, senderId, Endian.big);
    byteData.setUint32(8, channelId, Endian.big);
    byteData.setUint16(12, sequence, Endian.big);
    byteData.setUint16(14, payload.length, Endian.big);
    byteData.setUint32(16, timestamp, Endian.big);

    if (payload.isNotEmpty) {
      buffer.setRange(AppConstants.udpHeaderSize, totalLen, payload);
    }

    return buffer;
  }
}

/// UDP client handling 20-byte wire protocol, token handshake, in-band VAD, and ping/pong latency probes.
class VoiceClient {
  RawDatagramSocket? _socket;
  Timer? _pingTimer;

  InternetAddress? _serverAddress;
  int _serverPort = AppConstants.defaultUdpPort;

  int _userId = 0;
  int _channelId = 0;
  int _sequenceCounter = 0;
  int _sampleTimestamp = 0;
  double _lastRttMs = 0.0;
  bool _isConnected = false;

  final Map<int, int> _pingSendTimes = {}; // seq -> sendTimestampMs

  final StreamController<VoicePacket> _inboundPacketController =
      StreamController<VoicePacket>.broadcast();
  Stream<VoicePacket> get inboundPacketStream => _inboundPacketController.stream;

  final StreamController<({int userId, bool isSpeaking, int energyLevel})> _speakingStateController =
      StreamController<({int userId, bool isSpeaking, int energyLevel})>.broadcast();
  Stream<({int userId, bool isSpeaking, int energyLevel})> get speakingStateStream =>
      _speakingStateController.stream;

  final StreamController<double> _rttController =
      StreamController<double>.broadcast();
  Stream<double> get rttStream => _rttController.stream;

  bool get isConnected => _isConnected;
  double get lastRttMs => _lastRttMs;

  /// Connects UDP socket and performs handshake with the SFU.
  Future<void> connect({
    required String host,
    required int port,
    required int userId,
    required int channelId,
    required String udpToken,
  }) async {
    await disconnect();

    _userId = userId;
    _channelId = channelId;
    _serverPort = port;

    final parsed = InternetAddress.tryParse(host);
    if (parsed != null) {
      _serverAddress = parsed;
    } else {
      _serverAddress = (await InternetAddress.lookup(host)).first;
    }

    _socket = await RawDatagramSocket.bind(InternetAddress.anyIPv4, 0);
    _isConnected = true;

    _socket!.listen((RawSocketEvent event) {
      if (event == RawSocketEvent.read) {
        final datagram = _socket?.receive();
        if (datagram != null) {
          _handleInboundDatagram(datagram.data);
        }
      }
    });

    // Send Handshake (Type 0x04) with burst for UDP delivery guarantee
    final tokenBytes = utf8.encode(udpToken);
    final handshakePacket = VoicePacket(
      type: AppConstants.packetTypeHandshake,
      senderId: _userId,
      channelId: _channelId,
      sequence: ++_sequenceCounter,
      timestamp: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      payload: Uint8List.fromList(tokenBytes),
    );
    sendPacket(handshakePacket);
    Future.delayed(const Duration(milliseconds: 80), () {
      if (_isConnected) sendPacket(handshakePacket);
    });
    Future.delayed(const Duration(milliseconds: 250), () {
      if (_isConnected) sendPacket(handshakePacket);
    });

    _startPingProbe();
  }

  void _handleInboundDatagram(Uint8List data) {
    try {
      final packet = VoicePacket.decode(data);

      switch (packet.type) {
        case AppConstants.packetTypeVoice:
          // Ignore own voice packets if looped back or sent by self
          if (packet.senderId == _userId || packet.senderId == 0) {
            return;
          }

          // Fast-Path: In-band VAD & energy notification (<30ms)
          _speakingStateController.add((
            userId: packet.senderId,
            isSpeaking: packet.vad,
            energyLevel: packet.energyLevel,
          ));
          _inboundPacketController.add(packet);
          break;

        case AppConstants.packetTypePong:
          final now = DateTime.now().millisecondsSinceEpoch;
          final sendTime = _pingSendTimes.remove(packet.sequence);
          if (sendTime != null) {
            _lastRttMs = (now - sendTime).toDouble();
            _rttController.add(_lastRttMs);
          }
          break;
      }
    } catch (_) {
      // Ignored malformed UDP datagram
    }
  }

  /// Sends an Opus encoded audio frame to the SFU.
  void sendVoiceFrame({
    required Uint8List opusData,
    required bool isSpeaking,
    required int energyLevel,
  }) {
    if (!_isConnected || _socket == null || _serverAddress == null) return;

    _sampleTimestamp += AppConstants.frameSamples;
    _sequenceCounter = (_sequenceCounter + 1) & 0xFFFF;

    final packet = VoicePacket(
      type: AppConstants.packetTypeVoice,
      vad: isSpeaking,
      energyLevel: energyLevel,
      senderId: _userId,
      channelId: _channelId,
      sequence: _sequenceCounter,
      timestamp: _sampleTimestamp,
      payload: opusData,
    );

    sendPacket(packet);
  }

  /// Sends a raw VoicePacket over UDP.
  void sendPacket(VoicePacket packet) {
    if (_socket == null || _serverAddress == null) return;
    final bytes = packet.encode();
    _socket!.send(bytes, _serverAddress!, _serverPort);
  }

  void _startPingProbe() {
    _pingTimer?.cancel();
    _pingTimer = Timer.periodic(const Duration(milliseconds: 1000), (_) {
      if (!_isConnected || _socket == null || _serverAddress == null) return;

      _sequenceCounter = (_sequenceCounter + 1) & 0xFFFF;
      final now = DateTime.now().millisecondsSinceEpoch;
      _pingSendTimes[_sequenceCounter] = now;

      // Retain max 50 pending pings
      if (_pingSendTimes.length > 50) {
        _pingSendTimes.remove(_pingSendTimes.keys.first);
      }

      final pingPacket = VoicePacket(
        type: AppConstants.packetTypePing,
        senderId: _userId,
        channelId: _channelId,
        sequence: _sequenceCounter,
        timestamp: now ~/ 1000,
        payload: Uint8List(0),
      );

      sendPacket(pingPacket);
    });
  }

  /// Updates active channel ID without tearing down UDP socket (for admin move).
  void updateChannel(int newChannelId) {
    _channelId = newChannelId;
  }

  Future<void> disconnect() async {
    _isConnected = false;
    _userId = 0;
    _channelId = 0;
    _serverPort = AppConstants.defaultUdpPort;
    _pingTimer?.cancel();
    _pingTimer = null;
    _pingSendTimes.clear();
    _socket?.close();
    _socket = null;
  }

  void dispose() {
    disconnect();
    _inboundPacketController.close();
    _speakingStateController.close();
    _rttController.close();
  }
}
