# Expired-cookie notification — design

## Problem

The backend only checks that `cookies/cookies.txt` *exists* (`downloader.cookie_file()`).
It never learns when those cookies stop working. When cookies expire, YouTube
returns its sign-in / bot-check wall and the download simply fails with a generic
error; the user is not told that the cause is a stale `cookies.txt` or what to do
about it.

## Goal

When a download fails because YouTube demands sign-in *while a cookies file is in
use*, treat the cookies as expired and tell the frontend so it can guide the user
to re-export `cookies.txt`.

Explicitly **out of scope**: no active validation (no extra web request), no
deletion of `cookies.txt`, no server-side state. The warning is purely reactive —
it lives in the failed response and clears on page reload.

## Data flow

```
download fails (yt-dlp) → backend tags error as cookie-expiry case
                         → error JSON carries cookies_expired flag
                         → frontend shows "expired cookies" banner + error message
```

## Components

### 1. `app/downloader.py`

- `DownloadFailed` gains a `cookies_expired: bool` attribute, default `False`,
  set via `__init__(self, message, cookies_expired=False)`.
- New predicate `_signin_wall(message) -> bool` — matches the same phrases
  `_friendly()` already uses for YouTube's sign-in / bot wall
  (`"sign in to confirm"`, `"not a bot"`, `"confirm your age"`). `_friendly()` is
  refactored to call this predicate so the match logic lives in one place.
- In the `except YoutubeDLError` blocks of `inspect()` and `download_one()`:
  set `cookies_expired = _signin_wall(raw) and cookie_file() is not None`.
  The `cookie_file() is not None` clause is the key distinction — a sign-in wall
  *with* cookies in use means they are stale; *without* cookies it is merely
  "not configured yet", which the existing missing-cookies banner already covers.
- `build_playlist_zip()`: if any per-track `DownloadFailed` had
  `cookies_expired` true, the final "all N videos failed" `DownloadFailed` is
  raised with `cookies_expired=True` as well.

### 2. `app/app.py`

- `_error(message, code=400, cookies_expired=False)` — includes `cookies_expired`
  in the JSON body.
- The three `except downloader.DownloadFailed` handlers (`api_inspect`,
  `api_download`, `api_download_zip`) pass `exc.cookies_expired` through to
  `_error`.
- `/api/status` is unchanged.

### 3. `app/static/app.js`

- Fetch error handlers in `inspectUrl`, `downloadOne`, and `downloadZip` attach
  `err.cookiesExpired = data.cookies_expired` to the thrown `Error`.
- The banner builder in `checkCookieStatus()` is refactored into a reusable
  `renderCookieBanner(variant)` with two variants:
  - `"missing"` — current text ("No YouTube cookies configured").
  - `"expired"` — e.g. "Your cookies.txt looks expired — YouTube is asking to
    sign in again. Re-export cookies.txt from your browser, replace the file in
    the cookies/ folder, and restart the container."
- Each `catch` site that handles a failed download (single download, playlist
  ZIP, per-track row, sequential download) calls `renderCookieBanner("expired")`
  when `e.cookiesExpired` is set, in addition to its normal error display.

### 4. Tests

- `tests/test_downloader.py`: a sign-in-wall yt-dlp error sets `cookies_expired`
  true when a cookies file is present and false when it is absent; a plain error
  leaves it false; `build_playlist_zip` propagates the flag when all tracks fail
  on the sign-in wall.
- `tests/test_api.py`: `/api/download` and `/api/download-zip` error responses
  include `cookies_expired` matching the underlying failure.

## Error handling

- A non-cookie failure (network error, unavailable video, etc.) leaves
  `cookies_expired` false; the frontend behaviour is unchanged.
- The missing-cookies case (sign-in wall, no cookies file) is unaffected — it is
  not flagged as "expired" and the existing on-load missing-cookies banner stands.
