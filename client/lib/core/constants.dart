/// Protocol constants, network endpoints, opcodes, and UI dimensions.
class AppConstants {
  // Network Endpoints
  static const String defaultHost = '127.0.0.1';
  static const int defaultWsPort = 8080;
  static const int defaultUdpPort = 7878;

  // UDP Audio Wire Protocol
  static const int udpHeaderSize = 20;
  static const int udpMagicByte = 0x56; // 'V'
  static const int udpProtocolVersion = 0x01;
  static const int udpMaxPayloadSize = 1480;
  static const int udpMaxPacketSize = 1500;

  // UDP Packet Types
  static const int packetTypeVoice = 0x01;
  static const int packetTypePing = 0x02;
  static const int packetTypePong = 0x03;
  static const int packetTypeHandshake = 0x04;

  // UDP Header Flags
  static const int flagVad = 0x01; // Bit 0: 1 = speaking, 0 = silence
  static const int flagReserved = 0x0E; // Bits 1-3
  static const int flagEnergyMask = 0xF0; // Bits 4-7: 4-bit energy level (0-15)

  // Audio Specifications
  static const int sampleRate = 48000;
  static const int audioChannels = 1; // Mono for low-latency voice
  static const int frameDurationMs = 20; // 20ms frame
  static const int frameSamples = (sampleRate * frameDurationMs) ~/ 1000; // 960 samples
  static const int defaultBitrate = 48000; // 48 kbps
  static const double defaultVadThresholdDb = -45.0; // dBFS
  static const int defaultVadHangoverMs = 200; // ms hangover time

  // Permission Bitfields
  static const int permAdmin = 1 << 0; // 0x0001
  static const int permManageChannels = 1 << 1; // 0x0002
  static const int permMoveMembers = 1 << 2; // 0x0004
  static const int permMuteMembers = 1 << 3; // 0x0008
  static const int permDeafenMembers = 1 << 4; // 0x0010
  static const int permKickMembers = 1 << 5; // 0x0020
  static const int permSendMessages = 1 << 6; // 0x0040
  static const int permConnectVoice = 1 << 7; // 0x0080
  static const int permSpeak = 1 << 8; // 0x0100
  static const int permAll = 0xFFFFFFFF;

  // Desktop Window Constraints
  static const double minWindowWidth = 960.0;
  static const double minWindowHeight = 600.0;
  static const double defaultWindowWidth = 1280.0;
  static const double defaultWindowHeight = 720.0;

  // UI Pane Dimensions
  static const double leftPaneWidth = 240.0;
  static const double rightPaneWidth = 220.0;
  static const double serverRailWidth = 68.0;
  static const double bottomUserDockHeight = 56.0;
  static const double voiceHudHeight = 52.0;
  static const double topHeaderHeight = 48.0;

  // Responsive Breakpoints
  static const double breakpointCollapseRoster = 1150.0;
  static const double breakpointCollapseChannels = 960.0;
}
