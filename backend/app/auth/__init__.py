"""Sign-in plumbing owned by FastAPI: opaque DB sessions (hashed at rest),
cookies, CSRF, rate limits and PII-free auth event logs.

Provider flows (magic link, Google, GitHub) and the invite gate build on this."""
