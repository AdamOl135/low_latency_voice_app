package audio

import (
	"sync"
)

var (
	// bufferPool manages reusable 1500-byte datagram buffers to prevent GC allocations.
	bufferPool = sync.Pool{
		New: func() interface{} {
			b := make([]byte, MaxPacketSize)
			return &b
		},
	}

	// packetPool manages reusable *Packet structs to eliminate heap allocations during decode.
	packetPool = sync.Pool{
		New: func() interface{} {
			return &Packet{}
		},
	}
)

// GetBuffer retrieves a 1500-byte slice from the global buffer pool.
func GetBuffer() []byte {
	bufPtr := bufferPool.Get().(*[]byte)
	return (*bufPtr)[:MaxPacketSize]
}

// PutBuffer returns a buffer slice to the global buffer pool.
func PutBuffer(buf []byte) {
	if cap(buf) < MaxPacketSize {
		return
	}
	// Re-slice to full capacity before returning
	full := buf[:MaxPacketSize]
	bufferPool.Put(&full)
}

// GetPacket retrieves a clean Packet struct from the global packet pool.
func GetPacket() *Packet {
	pkt := packetPool.Get().(*Packet)
	pkt.Reset()
	return pkt
}

// PutPacket returns a Packet struct to the pool after clearing fields.
func PutPacket(pkt *Packet) {
	if pkt == nil {
		return
	}
	pkt.Reset()
	packetPool.Put(pkt)
}
