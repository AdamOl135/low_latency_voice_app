package control

// JSON-RPC standard and application error codes.
const (
	// Standard JSON-RPC 2.0 errors
	ErrCodeParseError     = -32700
	ErrCodeInvalidRequest = -32600
	ErrCodeMethodNotFound = -32601
	ErrCodeInvalidParams  = -32602
	ErrCodeInternalError  = -32603

	// Application-specific errors
	ErrCodeUnauthorized         = 4001
	ErrCodeInvalidCredentials    = 4002
	ErrCodeForbidden            = 4003
	ErrCodeUserAlreadyExists    = 4004
	ErrCodeChannelNotFound      = 4005
	ErrCodeInvalidChannelType   = 4006
	ErrCodeMessageEmpty         = 4007
	ErrCodeMessageTooLong       = 4008
	ErrCodeChannelFull          = 4009
	ErrCodeImmutableCreatorRole = 4010
	ErrCodeTokenExpired         = 4011
	ErrCodeRateLimitExceeded    = 4012
)

// ErrorDetail describes an error for JSON responses.
type ErrorDetail struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// ErrorResponse represents a standardized JSON-RPC error payload.
type ErrorResponse struct {
	ID        interface{} `json:"id"`
	Status    string      `json:"status"` // always "error"
	Action    string      `json:"action,omitempty"`
	RequestID string      `json:"request_id,omitempty"`
	Error     ErrorDetail `json:"error"`
}

// NewErrorResponse constructs an ErrorResponse with given action, ID, error code and message.
func NewErrorResponse(id interface{}, action string, code int, message string) *ErrorResponse {
	var reqIDStr string
	if s, ok := id.(string); ok {
		reqIDStr = s
	}
	return &ErrorResponse{
		ID:        id,
		Status:    "error",
		Action:    action,
		RequestID: reqIDStr,
		Error: ErrorDetail{
			Code:    code,
			Message: message,
		},
	}
}
