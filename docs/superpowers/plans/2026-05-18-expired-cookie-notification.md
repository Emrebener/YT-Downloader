# Expired-Cookie Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a download fails because YouTube demands sign-in while `cookies.txt` is in use, tell the frontend the cookies look expired so it can guide the user to re-export them.

**Architecture:** A `DownloadFailed` exception gains a `cookies_expired` flag, set in the backend when a yt-dlp sign-in-wall error occurs *and* a cookies file is configured. The flag rides the error JSON to the browser, which then shows an "expired cookies" banner. Purely reactive — no server state, no file deletion.

**Tech Stack:** Python 3 / FastAPI / yt-dlp / pytest; vanilla JS frontend.

**Conventions:**
- Run Python only via `./venv/bin/python` (deps are not on PATH).
- Run tests with `./venv/bin/python -m pytest -m "not network"` (offline).
- All new tests are offline — they monkeypatch yt-dlp, so the `not network` marker applies.

---

## File Structure

- `app/downloader.py` — modified: `DownloadFailed` gains `cookies_expired`; new `_signin_wall()` predicate; `inspect()`, `download_one()`, `build_playlist_zip()` set/propagate the flag.
- `app/app.py` — modified: `_error()` includes `cookies_expired`; the three `DownloadFailed` handlers pass it through.
- `app/static/app.js` — modified: error objects carry `cookiesExpired`; banner builder refactored into `renderCookieBanner(variant)` with a new `"expired"` variant; catch sites show it.
- `tests/test_downloader.py` — modified: tests for the predicate and flag-setting.
- `tests/test_api.py` — modified: tests that error responses carry `cookies_expired`.

---

## Task 1: `cookies_expired` flag on `DownloadFailed` + `_signin_wall` predicate

**Files:**
- Modify: `app/downloader.py:12-13` (the `DownloadFailed` class), `app/downloader.py:21-33` (the `_friendly` function)
- Test: `tests/test_downloader.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_downloader.py`:

```python
def test_download_failed_defaults_cookies_expired_false():
    assert downloader.DownloadFailed("oops").cookies_expired is False


def test_download_failed_accepts_cookies_expired():
    assert downloader.DownloadFailed("oops", cookies_expired=True).cookies_expired is True


def test_signin_wall_detects_bot_check():
    assert downloader._signin_wall("ERROR: Sign in to confirm you're not a bot")


def test_signin_wall_detects_age_confirmation():
    assert downloader._signin_wall("Please confirm your age")


def test_signin_wall_ignores_plain_error():
    assert not downloader._signin_wall("Video unavailable")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -k "download_failed or signin_wall" -v`
Expected: FAIL — `AttributeError` on `cookies_expired` / `_signin_wall` not defined.

- [ ] **Step 3: Implement the change**

Replace the `DownloadFailed` class (`app/downloader.py:12-13`):

```python
class DownloadFailed(Exception):
    """Raised when yt-dlp cannot inspect or download a URL."""

    def __init__(self, message: str, cookies_expired: bool = False):
        super().__init__(message)
        #: True when the failure is YouTube's sign-in wall *and* a cookies
        #: file was in use — i.e. the cookies look expired.
        self.cookies_expired = cookies_expired
```

Add `_signin_wall` directly above `_friendly` (before `app/downloader.py:21`):

```python
def _signin_wall(message: str) -> bool:
    """True if a yt-dlp error is YouTube's sign-in / bot-check / age wall."""
    low = message.lower()
    return ("sign in to confirm" in low or "not a bot" in low
            or "confirm your age" in low)
```

Refactor `_friendly` to reuse it (replace `app/downloader.py:21-33`):

```python
def _friendly(message: str) -> str:
    """Turn a raw yt-dlp error into a concise, user-facing message.

    YouTube's sign-in / bot-check wall has a long, link-laden error; collapse it
    into a short hint pointing at cookie setup.
    """
    cleaned = _clean(message)
    if _signin_wall(cleaned):
        return ("YouTube blocked this download with a sign-in check. Add a "
                "cookies.txt file — or refresh it if it has expired. See the "
                "app's setup notes.")
    return cleaned
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -k "download_failed or signin_wall or friendly" -v`
Expected: PASS (the new tests plus any existing `_friendly` test).

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: add cookies_expired flag and _signin_wall predicate"
```

---

## Task 2: Flag the expiry in `inspect()` and `download_one()`

**Files:**
- Modify: `app/downloader.py:65-66` (`inspect` except block), `app/downloader.py:115-116` (`download_one` except block)
- Test: `tests/test_downloader.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_downloader.py`:

```python
class _SigninWallYDL:
    """Fake YoutubeDL whose extract_info always raises YouTube's bot wall."""

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        from yt_dlp.utils import YoutubeDLError
        raise YoutubeDLError("ERROR: Sign in to confirm you're not a bot")


def test_inspect_flags_expired_when_cookies_present(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("COOKIES_FILE", str(f))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.inspect("http://x")
    assert exc.value.cookies_expired is True


def test_inspect_no_flag_when_cookies_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "absent.txt"))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.inspect("http://x")
    assert exc.value.cookies_expired is False


def test_download_one_flags_expired_when_cookies_present(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("COOKIES_FILE", str(f))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.download_one("http://x", DownloadOptions(), str(tmp_path))
    assert exc.value.cookies_expired is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -k "flags_expired or no_flag" -v`
Expected: FAIL — `cookies_expired` is `False` (flag not yet wired).

- [ ] **Step 3: Implement the change**

In `inspect()`, replace the except block at `app/downloader.py:65-66`:

```python
    except YoutubeDLError as exc:
        raw = str(exc)
        raise DownloadFailed(
            _friendly(raw),
            cookies_expired=_signin_wall(raw) and cookie_file() is not None,
        )
```

In `download_one()`, replace the except block at `app/downloader.py:115-116`:

```python
    except YoutubeDLError as exc:
        raw = str(exc)
        raise DownloadFailed(
            _friendly(raw),
            cookies_expired=_signin_wall(raw) and cookie_file() is not None,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -k "flags_expired or no_flag" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: flag expired cookies on inspect and download failures"
```

---

## Task 3: Propagate the flag through `build_playlist_zip()`

**Files:**
- Modify: `app/downloader.py:152` (add `cookies_expired` local), `app/downloader.py:160-164` (per-track except), `app/downloader.py:167-171` (all-failed raise)
- Test: `tests/test_downloader.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_downloader.py`:

```python
def test_build_playlist_zip_propagates_cookies_expired(monkeypatch, tmp_path):
    fake = {
        "type": "playlist", "title": "Blocked Mix", "count": 1,
        "entries": [{"url": "http://x/1", "title": "A", "channel": "C"}],
    }
    monkeypatch.setattr(downloader, "inspect", lambda url: fake)

    def boom(url, options, out_dir):
        raise downloader.DownloadFailed("blocked", cookies_expired=True)
    monkeypatch.setattr(downloader, "download_one", boom)

    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.build_playlist_zip("http://x", DownloadOptions(), str(tmp_path))
    assert exc.value.cookies_expired is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -k "propagates_cookies_expired" -v`
Expected: FAIL — `cookies_expired` is `False` on the re-raised "all failed" error.

- [ ] **Step 3: Implement the change**

In `build_playlist_zip()`, add a flag local next to `errors` (replace `app/downloader.py:152`):

```python
    errors: list[str] = []
    cookies_expired = False              # set if any track hit the sign-in wall
```

Replace the per-track except block (`app/downloader.py:160-164`):

```python
        except DownloadFailed as exc:
            label = entry.get("title") or f"track-{idx}"
            errors.append(f"{label}: {exc}")
            if exc.cookies_expired:
                cookies_expired = True
            shutil.rmtree(track_dir, ignore_errors=True)
            continue
```

Replace the all-failed raise (`app/downloader.py:167-171`):

```python
    if not files:
        detail = errors[0] if errors else "the playlist had no usable entries"
        raise DownloadFailed(
            f"All {len(entries)} videos failed to download. First error — {detail}",
            cookies_expired=cookies_expired,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_downloader.py -m "not network" -v`
Expected: PASS — the new test plus all existing `test_downloader.py` tests.

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: propagate cookies_expired through playlist ZIP failures"
```

---

## Task 4: Surface `cookies_expired` in API error responses

**Files:**
- Modify: `app/app.py:45-46` (`_error`), `app/app.py:109-110` (`api_inspect`), `app/app.py:123-125` (`api_download`), `app/app.py:171-173` (`api_download_zip`)
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_inspect_error_includes_cookies_expired(client, monkeypatch):
    def boom(url):
        raise downloader.DownloadFailed("blocked", cookies_expired=True)
    monkeypatch.setattr(downloader, "inspect", boom)
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "blocked", "cookies_expired": True}


def test_download_error_includes_cookies_expired(client, monkeypatch):
    def boom(url, options, out_dir):
        raise downloader.DownloadFailed("blocked", cookies_expired=True)
    monkeypatch.setattr(downloader, "download_one", boom)
    res = client.post("/api/download", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "blocked", "cookies_expired": True}


def test_download_zip_error_includes_cookies_expired(client, monkeypatch):
    def boom(url, options, job_dir):
        raise downloader.DownloadFailed("blocked", cookies_expired=True)
    monkeypatch.setattr(downloader, "build_playlist_zip", boom)
    res = client.get("/api/download-zip", params={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "blocked", "cookies_expired": True}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_api.py -m "not network" -k "includes_cookies_expired" -v`
Expected: FAIL — responses are `{"error": "blocked"}` without the `cookies_expired` key.

- [ ] **Step 3: Implement the change**

Replace `_error` (`app/app.py:45-46`):

```python
def _error(message: str, code: int = 400, cookies_expired: bool = False) -> JSONResponse:
    body = {"error": message}
    if cookies_expired:
        body["cookies_expired"] = True
    return JSONResponse(status_code=code, content=body)
```

In `api_inspect`, replace the except block (`app/app.py:109-110`):

```python
    except downloader.DownloadFailed as exc:
        return _error(str(exc), cookies_expired=exc.cookies_expired)
```

In `api_download`, replace the except block (`app/app.py:123-125`):

```python
    except downloader.DownloadFailed as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _error(str(exc), cookies_expired=exc.cookies_expired)
```

In `api_download_zip`, replace the except block (`app/app.py:171-173`):

```python
    except downloader.DownloadFailed as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _error(str(exc), cookies_expired=exc.cookies_expired)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/bin/python -m pytest tests/test_api.py -m "not network" -v`
Expected: PASS — the new tests plus all existing `test_api.py` tests (plain-error tests still match `{"error": ...}` since the key is omitted when false).

- [ ] **Step 5: Commit**

```bash
git add app/app.py tests/test_api.py
git commit -m "feat: include cookies_expired in API error responses"
```

---

## Task 5: Frontend — "expired cookies" banner

**Files:**
- Modify: `app/static/app.js` — `inspectUrl` (lines 80-91), `downloadOne` (lines 94-108), `downloadZip` (lines 112-151), `buildTrackRow` click handler (lines 191-199), `renderPlaylist` seq handler (lines 239-254), `onDownload` (lines 257-281), `checkCookieStatus` (lines 284-310)

This task has no automated test (the project has no JS test harness); it is verified manually in Step 4.

- [ ] **Step 1: Add `renderCookieBanner` and `reportError`, refactor `checkCookieStatus`**

Replace the whole `checkCookieStatus` function (`app/static/app.js:283-310`) with:

```javascript
// Render the cookie setup/expiry banner. variant is "missing" or "expired".
function renderCookieBanner(variant) {
  const banner = $("cookie-banner");
  banner.replaceChildren();

  const heading = document.createElement("strong");
  const body = document.createElement("p");

  if (variant === "expired") {
    heading.textContent = "⚠ YouTube cookies expired";
    body.textContent =
      "Your cookies.txt looks expired — YouTube is asking to sign in again. " +
      "Re-export the youtube.com cookies from your browser, replace the file " +
      "in the app's cookies/ folder, then restart the container. See the " +
      "README for details.";
  } else {
    heading.textContent = "⚠ No YouTube cookies configured";
    body.textContent =
      "YouTube may block downloads with a sign-in check. To fix it: install a " +
      "\"cookies.txt\" browser extension, sign in to YouTube, export the " +
      "youtube.com cookies, save the file as cookies.txt in the app's cookies/ " +
      "folder, then restart the container. See the README for details.";
  }

  banner.append(heading, body);
  banner.hidden = false;
}

// Show an error message and, if it was a cookie-expiry failure, the banner.
function reportError(e) {
  showError(e.message);
  if (e.cookiesExpired) renderCookieBanner("expired");
}

// Show a one-time setup banner when no YouTube cookies file is configured.
async function checkCookieStatus() {
  let data;
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    data = await res.json();
  } catch (e) {
    return;
  }
  if (data.cookies) return;          // cookies present — nothing to warn about
  renderCookieBanner("missing");
}
```

- [ ] **Step 2: Attach `cookiesExpired` to thrown errors**

In `inspectUrl`, replace the `if (!res.ok)` block (`app/static/app.js:86-89`):

```javascript
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data.error || "Could not read that URL.");
    err.cookiesExpired = Boolean(data.cookies_expired);
    throw err;
  }
```

In `downloadOne`, replace the `if (!res.ok)` block (`app/static/app.js:100-103`):

```javascript
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data.error || "Download failed.");
    err.cookiesExpired = Boolean(data.cookies_expired);
    throw err;
  }
```

In `downloadZip`, replace the `if (!res.ok)` block (`app/static/app.js:128-131`):

```javascript
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const err = new Error(data.error || "ZIP download failed.");
      err.cookiesExpired = Boolean(data.cookies_expired);
      throw err;
    }
```

- [ ] **Step 3: Show the banner at every catch site**

In `downloadZip`, replace the `catch` block (`app/static/app.js:144-146`):

```javascript
  } catch (e) {
    reportError(e);
  } finally {
```

In `buildTrackRow`'s button click handler, replace the `catch` block (`app/static/app.js:196-198`):

```javascript
    } catch (e) {
      setTrackStatus(row, "error", e.message);
      if (e.cookiesExpired) renderCookieBanner("expired");
    }
```

In `renderPlaylist`'s `seqBtn` handler, replace the `catch` block (`app/static/app.js:248-250`):

```javascript
      } catch (e) {
        setTrackStatus(rows[i], "error", e.message);
        if (e.cookiesExpired) renderCookieBanner("expired");
      }
```

In `onDownload`, replace the `catch` block (`app/static/app.js:275-278`):

```javascript
  } catch (e) {
    setStatus("");
    reportError(e);
  } finally {
```

- [ ] **Step 4: Verify manually**

Start the app: `WORK_DIR=$(mktemp -d) ./venv/bin/uvicorn app.app:app --reload`

Temporarily make the backend always raise an expiry error to exercise the UI — in `app/downloader.py`, at the top of `download_one`, add `raise DownloadFailed("test", cookies_expired=True)`. Reload `http://localhost:8000`, paste any video URL, click Download.
Expected: the inline error shows "test" **and** the orange banner reads "⚠ YouTube cookies expired".

Remove the temporary `raise` line afterwards. Confirm `git diff app/downloader.py` shows no leftover change.

- [ ] **Step 5: Commit**

```bash
git add app/static/app.js
git commit -m "feat: show expired-cookies banner when a download is blocked"
```

---

## Final Verification

- [ ] Run the full offline suite: `./venv/bin/python -m pytest -m "not network" -v` — expected: all PASS.
- [ ] Confirm `git status` is clean and `git diff app/downloader.py` has no temporary debug `raise`.
