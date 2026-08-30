package audio

import (
	"encoding/binary"
	"fmt"
)

// Packet represents a parsed 20-byte binary wire protocol packet with payload.
type Packet struct {
	Magic       uint8  // 0x56 ('V')
	Version     uint8  // 0x01
	Type        uint8  // TypeVoice, TypePing, TypePong, TypeHandshake
	Flags       uint8  // Raw byte 3
	VAD         bool   // True if active speech detected (Bit 0 of Flags)
	EnergyLevel uint8  // 4-bit quantized energy 0..15 (Bits 4-7 of Flags)
	SenderID    uint32 // User ID of the transmitting client (BE uint32)
	ChannelID   uint32 // Voice Channel ID (BE uint32)
	Sequence    uint16 // Packet sequence counter (BE uint16)
	PayloadLen  uint16 // Payload byte length (BE uint16)
	Timestamp   uint32 // 48kHz audio sample timestamp (BE uint32)
	Payload     []byte // Raw payload sub-slice
}

// Reset clears all fields of the Packet for object pool reuse.
func (p *Packet) Reset() {
	p.Magic = 0
	p.Version = 0
	p.Type = 0
	p.Flags = 0
	p.VAD = false
	p.EnergyLevel = 0
	p.SenderID = 0
	p.ChannelID = 0
	p.Sequence = 0
	p.PayloadLen = 0
	p.Timestamp = 0
	p.Payload = nil
}

// Decode parses a raw datagram buffer into a new heap-allocated Packet struct.
func Decode(data []byte) (*Packet, error) {
	pkt := &Packet{}
	if err := DecodeInto(data, pkt); err != nil {
		return nil, err
	}
	return pkt, nil
}

// DecodeInto parses a raw datagram buffer into an existing Packet struct without heap allocation.
func DecodeInto(data []byte, pkt *Packet) error {
	if len(data) < HeaderSize {
		return ErrPacketTooShort
	}

	pkt.Magic = data[0]
	if pkt.Magic != MagicByte {
		return ErrInvalidMagic
	}

	pkt.Version = data[1]
	if pkt.Version != ProtocolVersion {
		return ErrInvalidVersion
	}

	pkt.Type = data[2]
	if !IsValidPacketType(pkt.Type) {
		return ErrInvalidType
	}

	pkt.Flags = data[3]
	pkt.VAD, pkt.EnergyLevel = DecodeFlags(pkt.Flags)

	pkt.SenderID = binary.BigEndian.Uint32(data[4:8])
	pkt.ChannelID = binary.BigEndian.Uint32(data[8:12])
	pkt.Sequence = binary.BigEndian.Uint16(data[12:14])
	pkt.PayloadLen = binary.BigEndian.Uint16(data[14:16])
	pkt.Timestamp = binary.BigEndian.Uint32(data[16:20])

	if pkt.PayloadLen > MaxPayloadSize {
		return ErrPayloadTooLarge
	}

	expectedTotal := HeaderSize + int(pkt.PayloadLen)
	if len(data) < expectedTotal {
		return fmt.Errorf("%w: header says %d bytes, buffer has %d bytes",
			ErrPayloadLengthMismatch, pkt.PayloadLen, len(data)-HeaderSize)
	}

	pkt.Payload = data[HeaderSize:expectedTotal]
	return nil
}

// Encode serializes the packet into a newly allocated byte slice.
func (p *Packet) Encode() []byte {
	totalLen := HeaderSize + len(p.Payload)
	buf := make([]byte, totalLen)
	p.EncodeInto(buf)
	return buf
}

// EncodeInto serializes the packet directly into dst buffer without allocations.
// dst must have length >= HeaderSize + len(p.Payload). Returns the number of bytes written.
func (p *Packet) EncodeInto(dst []byte) int {
	totalLen := HeaderSize + len(p.Payload)
	if len(dst) < totalLen {
		return 0
	}

	magic := p.Magic
	if magic == 0 {
		magic = MagicByte
	}
	version := p.Version
	if version == 0 {
		version = ProtocolVersion
	}

	dst[0] = magic
	dst[1] = version
	dst[2] = p.Type
	dst[3] = EncodeFlags(p.VAD, p.EnergyLevel)
	binary.BigEndian.PutUint32(dst[4:8], p.SenderID)
	binary.BigEndian.PutUint32(dst[8:12], p.ChannelID)
	binary.BigEndian.PutUint16(dst[12:14], p.Sequence)
	binary.BigEndian.PutUint16(dst[14:16], uint16(len(p.Payload)))
	binary.BigEndian.PutUint32(dst[16:20], p.Timestamp)

	if len(p.Payload) > 0 {
		copy(dst[HeaderSize:totalLen], p.Payload)
	}

	return totalLen
}
