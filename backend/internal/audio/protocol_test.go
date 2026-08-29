package audio

import (
	"bytes"
	"encoding/binary"
	"testing"
)

func TestHeaderBinaryEncoding(t *testing.T) {
	pkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 14,
		SenderID:    0x12345678,
		ChannelID:   101,
		Sequence:    42,
		Timestamp:   0x00010000,
		Payload:     []byte{1, 2, 3, 4, 5},
	}

	encoded := pkt.Encode()
	if len(encoded) != HeaderSize+5 {
		t.Fatalf("expected encoded length %d, got %d", HeaderSize+5, len(encoded))
	}

	if encoded[0] != MagicByte {
		t.Errorf("expected magic 0x%X, got 0x%X", MagicByte, encoded[0])
	}
	if encoded[1] != ProtocolVersion {
		t.Errorf("expected version 0x%X, got 0x%X", ProtocolVersion, encoded[1])
	}
	if encoded[2] != TypeVoice {
		t.Errorf("expected type 0x%X, got 0x%X", TypeVoice, encoded[2])
	}

	// Flags: energy 14 (0xE0) | vad 1 (0x01) -> 0xE1
	if encoded[3] != 0xE1 {
		t.Errorf("expected flags 0xE1, got 0x%X", encoded[3])
	}

	senderID := binary.BigEndian.Uint32(encoded[4:8])
	if senderID != 0x12345678 {
		t.Errorf("expected senderID 0x12345678, got 0x%X", senderID)
	}

	channelID := binary.BigEndian.Uint32(encoded[8:12])
	if channelID != 101 {
		t.Errorf("expected channelID 101, got %d", channelID)
	}

	seq := binary.BigEndian.Uint16(encoded[12:14])
	if seq != 42 {
		t.Errorf("expected sequence 42, got %d", seq)
	}

	payloadLen := binary.BigEndian.Uint16(encoded[14:16])
	if payloadLen != 5 {
		t.Errorf("expected payloadLen 5, got %d", payloadLen)
	}

	ts := binary.BigEndian.Uint32(encoded[16:20])
	if ts != 0x00010000 {
		t.Errorf("expected timestamp 0x00010000, got 0x%X", ts)
	}

	if !bytes.Equal(encoded[20:], []byte{1, 2, 3, 4, 5}) {
		t.Errorf("payload mismatch: got %v", encoded[20:])
	}

	// Decode into a new struct
	decoded, err := Decode(encoded)
	if err != nil {
		t.Fatalf("decode failed: %v", err)
	}

	if decoded.Magic != MagicByte {
		t.Errorf("decoded magic mismatch: %d", decoded.Magic)
	}
	if decoded.VAD != true {
		t.Errorf("decoded VAD mismatch: %v", decoded.VAD)
	}
	if decoded.EnergyLevel != 14 {
		t.Errorf("decoded energy mismatch: %d", decoded.EnergyLevel)
	}
	if decoded.SenderID != 0x12345678 {
		t.Errorf("decoded sender mismatch: %d", decoded.SenderID)
	}
	if decoded.ChannelID != 101 {
		t.Errorf("decoded channel mismatch: %d", decoded.ChannelID)
	}
	if decoded.Sequence != 42 {
		t.Errorf("decoded sequence mismatch: %d", decoded.Sequence)
	}
	if decoded.Timestamp != 0x00010000 {
		t.Errorf("decoded timestamp mismatch: %d", decoded.Timestamp)
	}
	if !bytes.Equal(decoded.Payload, []byte{1, 2, 3, 4, 5}) {
		t.Errorf("decoded payload mismatch: %v", decoded.Payload)
	}
}

func TestDecodeErrors(t *testing.T) {
	// Too short (< 20 bytes)
	_, err := Decode([]byte{0x56, 0x01})
	if err != ErrPacketTooShort {
		t.Errorf("expected ErrPacketTooShort, got %v", err)
	}

	// Invalid Magic
	badMagic := make([]byte, 20)
	badMagic[0] = 0x99
	badMagic[1] = ProtocolVersion
	badMagic[2] = TypeVoice
	_, err = Decode(badMagic)
	if err != ErrInvalidMagic {
		t.Errorf("expected ErrInvalidMagic, got %v", err)
	}

	// Invalid Version
	badVer := make([]byte, 20)
	badVer[0] = MagicByte
	badVer[1] = 0x99
	badVer[2] = TypeVoice
	_, err = Decode(badVer)
	if err != ErrInvalidVersion {
		t.Errorf("expected ErrInvalidVersion, got %v", err)
	}

	// Invalid Type
	badType := make([]byte, 20)
	badType[0] = MagicByte
	badType[1] = ProtocolVersion
	badType[2] = 0x99
	_, err = Decode(badType)
	if err != ErrInvalidType {
		t.Errorf("expected ErrInvalidType, got %v", err)
	}

	// Payload length mismatch
	lenMismatch := make([]byte, 25)
	lenMismatch[0] = MagicByte
	lenMismatch[1] = ProtocolVersion
	lenMismatch[2] = TypeVoice
	binary.BigEndian.PutUint16(lenMismatch[14:16], 100) // Claims 100 bytes payload but only 5 present
	_, err = Decode(lenMismatch)
	if err == nil {
		t.Errorf("expected payload length mismatch error, got nil")
	}
}

func TestFlagsBitManipulation(t *testing.T) {
	testCases := []struct {
		vad    bool
		energy uint8
	}{
		{false, 0},
		{true, 0},
		{false, 15},
		{true, 15},
		{true, 8},
		{false, 4},
		{true, 12},
	}

	for _, tc := range testCases {
		flag := EncodeFlags(tc.vad, tc.energy)
		gotVAD, gotEnergy := DecodeFlags(flag)
		if gotVAD != tc.vad || gotEnergy != tc.energy {
			t.Errorf("Flags mismatch for VAD=%v Energy=%d: got VAD=%v Energy=%d (flags=0x%02X)",
				tc.vad, tc.energy, gotVAD, gotEnergy, flag)
		}
	}
}

func BenchmarkPacketDecode(b *testing.B) {
	pkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 14,
		SenderID:    1001,
		ChannelID:   101,
		Sequence:    500,
		Timestamp:   96000,
		Payload:     make([]byte, 80),
	}
	raw := pkt.Encode()

	p := &Packet{}
	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		_ = DecodeInto(raw, p)
	}
}

func BenchmarkPacketEncode(b *testing.B) {
	pkt := &Packet{
		Magic:       MagicByte,
		Version:     ProtocolVersion,
		Type:        TypeVoice,
		VAD:         true,
		EnergyLevel: 14,
		SenderID:    1001,
		ChannelID:   101,
		Sequence:    500,
		Timestamp:   96000,
		Payload:     make([]byte, 80),
	}
	dst := make([]byte, 1500)
	b.ReportAllocs()
	b.ResetTimer()

	for i := 0; i < b.N; i++ {
		_ = pkt.EncodeInto(dst)
	}
}
