package auth

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	"golang.org/x/crypto/argon2"
	"golang.org/x/crypto/bcrypt"
)

var (
	ErrInvalidHash         = errors.New("the encoded hash is not in the correct format")
	ErrIncompatibleVersion = errors.New("incompatible version of argon2")
)

type Argon2Params struct {
	Memory      uint32
	Iterations  uint32
	Parallelism uint8
	SaltLength  uint32
	KeyLength   uint32
}

var DefaultArgon2Params = &Argon2Params{
	Memory:      64 * 1024, // 64 MB
	Iterations:  3,
	Parallelism: 2,
	SaltLength:  16,
	KeyLength:   32,
}

// HashPassword hashes a plain-text password using Argon2id with cryptographically random salt.
func HashPassword(password string) (string, error) {
	salt := make([]byte, DefaultArgon2Params.SaltLength)
	if _, err := rand.Read(salt); err != nil {
		return "", fmt.Errorf("failed to generate random salt: %w", err)
	}

	hash := argon2.IDKey(
		[]byte(password),
		salt,
		DefaultArgon2Params.Iterations,
		DefaultArgon2Params.Memory,
		DefaultArgon2Params.Parallelism,
		DefaultArgon2Params.KeyLength,
	)

	b64Salt := base64.RawStdEncoding.EncodeToString(salt)
	b64Hash := base64.RawStdEncoding.EncodeToString(hash)

	encoded := fmt.Sprintf(
		"$argon2id$v=%d$m=%d,t=%d,p=%d$%s$%s",
		argon2.Version,
		DefaultArgon2Params.Memory,
		DefaultArgon2Params.Iterations,
		DefaultArgon2Params.Parallelism,
		b64Salt,
		b64Hash,
	)

	return encoded, nil
}

// VerifyPassword verifies if a plain-text password matches the stored Argon2id or bcrypt hash.
func VerifyPassword(password, encodedHash string) (bool, error) {
	if strings.HasPrefix(encodedHash, "$2a$") || strings.HasPrefix(encodedHash, "$2b$") || strings.HasPrefix(encodedHash, "$2y$") {
		// Bcrypt compatibility
		err := bcrypt.CompareHashAndPassword([]byte(encodedHash), []byte(password))
		if err != nil {
			return false, nil
		}
		return true, nil
	}

	vals := strings.Split(encodedHash, "$")
	if len(vals) != 6 {
		return false, ErrInvalidHash
	}

	var version int
	_, err := fmt.Sscanf(vals[2], "v=%d", &version)
	if err != nil {
		return false, err
	}
	if version != argon2.Version {
		return false, ErrIncompatibleVersion
	}

	p := &Argon2Params{}
	_, err = fmt.Sscanf(vals[3], "m=%d,t=%d,p=%d", &p.Memory, &p.Iterations, &p.Parallelism)
	if err != nil {
		return false, err
	}

	salt, err := base64.RawStdEncoding.Strict().DecodeString(vals[4])
	if err != nil {
		return false, err
	}

	decodedHash, err := base64.RawStdEncoding.Strict().DecodeString(vals[5])
	if err != nil {
		return false, err
	}
	p.KeyLength = uint32(len(decodedHash))

	otherHash := argon2.IDKey([]byte(password), salt, p.Iterations, p.Memory, p.Parallelism, p.KeyLength)

	if subtle.ConstantTimeCompare(decodedHash, otherHash) == 1 {
		return true, nil
	}
	return false, nil
}
