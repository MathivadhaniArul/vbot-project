# Security Notes

## Authentication

The current implementation uses `localStorage`-based user identification. This is sufficient for a college project demo but is **not production-secure**.

### Known Limitation

The `userId` is stored in the browser's `localStorage` and sent as a plain query parameter or request body field to the backend. A malicious user could:

1. Open browser DevTools
2. Modify the `userId` value in `localStorage`
3. Access another user's reminders and notifications

### Mitigation for Production

To make this production-ready, implement one of:

- **JWT Authentication**: Issue signed tokens on login, validate on every API call.
- **Session-based Auth**: Use server-side sessions with secure cookies.
- **OAuth2 / OpenID Connect**: Delegate authentication to an identity provider.

## Encryption Key

The `ENCRYPTION_KEY` environment variable (used for Google OAuth token encryption) must:

- **Never** be committed to version control
- Be stored only in the `.env` file (which is gitignored)
- Be rotated immediately if accidentally exposed
- Be generated using `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Google OAuth Tokens

OAuth refresh tokens are encrypted at rest using Fernet symmetric encryption before being stored in MongoDB. The encryption key is loaded from the `ENCRYPTION_KEY` environment variable.

## API Security

Current CORS configuration allows all origins (`*`). For production:

- Restrict `allow_origins` to your frontend domain only
- Add rate limiting to prevent abuse
- Add input validation and sanitization
- Use HTTPS exclusively
