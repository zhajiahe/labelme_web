# Browser edits are the source of truth; GET must not change current

While an Image is open, the browser owns the live Shapes, Flags, and dirty
flag. The FastAPI process holds the current Image only so Save, AI Assist, and
navigation can read pixels. GET handlers are pure: an index maps to a path and
a disk read. They never call `open_index()`. Changing current is a POST
(`/api/session/current` or `/api/session/navigate`). A successful Save returns
an ACK (`ok`, `revision`, `saved_path`) and must not replace the browser's
in-memory Shapes — a stale ACK must not roll edits back.

## Considered options

- **Keep GET `/api/files/{index}/annotation` as "open this file"** — rejected:
  concurrent image requests reorder `AnnotationSession.current`, and Next with
  `auto_save: false` discarded unsaved Shapes.
- **Apply the Save response as a new session snapshot** — rejected: an older
  in-flight Save can overwrite newer browser Shapes. The client tracks
  `editVersion` / `savedVersion` and ignores stale ACKs.
- **Require a Bearer token on every bind** — rejected for loopback
  (`127.0.0.1`, `localhost`, `::1`) so `pip install` / `labelme` stays
  frictionless. Non-loopback binds (`0.0.0.0`, LAN addresses) generate a random
  token and reject `/api` calls without it.

## Consequences

- Unsaved Next/Prev/Open/Close/unload goes through `guardUnsavedChanges()`.
- File List pagination (`GET /api/files?offset&limit`) does not resend the
  whole dataset on every Save.
- AI Assist still runs against the server's current Image; the client must POST
  current before prompting.
