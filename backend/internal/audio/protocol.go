package audio

import (
	"errors"
)

const (
	// HeaderSize is the fixed size of the binary wire protocol header in bytes.
	HeaderSize = 20

	// MagicByte identifies valid application UDP datagrams ('V' = 0x56).
	MagicByte = 0x56

	// ProtocolVersion defines the current wire protocol version (0x01).
	ProtocolVersion = 0x01

	// MaxPayloadSize defines the maximum supported payload length in bytes (MTU 1500 - Header 20).
	MaxPayloadSize = 1480

	// MaxPacketSize is the maximum datagram size (1500 bytes).
	MaxPacketSize = 1500

	// DefaultPort is the standard UDP audio listening port.
	DefaultPort = 7878
)

// Packet type discriminants (Header byte 2).
const (
	TypeVoice     uint8 = 0x01 // Opus encoded audio frame (10ms-20ms)
	TypePing      uint8 = 0x02 // RTT latency probe from client
	TypePong      uint8 = 0x03 // RTT latency response from SFU
	TypeHandshake uint8 = 0x04 // UDP endpoint registration / token authentication
)

// Bitfield masks for Header byte 3 (Flags / VAD + Energy Level).
const (
	FlagVAD        uint8 = 0x01 // Bit 0: 1 = speaking, 0 = silence
	FlagReserved   uint8 = 0x0E // Bits 1-3: Reserved (must be 0)
	FlagEnergyMask uint8 = 0xF0 // Bits 4-7: 4-bit quantized energy level (0..15)
)

var (
	ErrPacketTooShort        = errors.New("audio: packet data too short for 20-byte header")
	ErrInvalidMagic          = errors.New("audio: invalid protocol magic byte")
	ErrInvalidVersion        = errors.New("audio: unsupported protocol version")
	ErrInvalidType           = errors.New("audio: unknown packet type")
	ErrPayloadLengthMismatch = errors.New("audio: payload length does not match header length")
	ErrPayloadTooLarge       = errors.New("audio: payload exceeds maximum supported MTU size")
	ErrSessionNotFound       = errors.New("audio: voice session not found")
	ErrUnauthorizedSession   = errors.New("audio: unauthorized or invalid voice token")
	ErrUserServerMuted       = errors.New("audio: user is server-muted")
	ErrChannelMismatch       = errors.New("audio: channel ID mismatch")
)

// EncodeFlags packs the boolean VAD speaking state and 4-bit energy level (0..15) into byte 3.
func EncodeFlags(vad bool, energy uint8) uint8 {
	var f uint8
	if vad {
		f |= FlagVAD
	}
	f |= (energy & 0x0F) << 4
	return f
}

// DecodeFlags unpacks byte 3 into boolean VAD speaking state and 4-bit energy level (0..15).
func DecodeFlags(flags uint8) (vad bool, energy uint8) {
	vad = (flags & FlagVAD) != 0
	energy = (flags & FlagEnergyMask) >> 4
	return vad, energy
}

// IsValidPacketType checks whether the given type discriminant is supported.
func IsValidPacketType(t uint8) bool {
	switch t {
	case TypeVoice, TypePing, TypePong, TypeHandshake:
		return true
	default:
		return false
	}
}
