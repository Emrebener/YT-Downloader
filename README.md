# YT Downloader

A simple, self-hosted website for saving YouTube videos and playlists as **audio**
(MP3, M4A, Opus, FLAC, WAV) or **video** (MP4, WebM, MKV) files — no ads, no
sketchy websites. You run it on your own computer and use it from your browser.

> ### 📖 A note on this guide
> **Special care has been taken to make these instructions as clear as possible
> for people who are *not* technical** — even if you have never used Docker, a
> terminal, or GitHub before. Every step is spelled out on purpose. Don't be put
> off by the length: it just means nothing is skipped. If you get stuck, jump to
> the [Troubleshooting](#troubleshooting) section near the bottom.

---

## What it does

- Paste a YouTube link, pick a format, click **Download**.
- **Single video** → downloads straight away.
- **Playlist** → lists every video so you can grab them one by one, or get the
  whole thing as one ZIP file.
- Files are named neatly as `Channel - Title.mp3` (or `.mp4`, etc.).
- Runs entirely on your machine. Nothing is uploaded anywhere.

---

## Before you start

You only need **one** thing installed: **Docker**. Docker is a free program that
runs this app in a tidy, self-contained box so you don't have to install Python,
ffmpeg, or anything else by hand. You install it once and forget about it.

The whole setup is 5 steps and takes about 10–15 minutes the first time (most of
that is just waiting for things to download).

---

## Step 1 — Install Docker

**Windows or macOS:**

1. Go to <https://www.docker.com/products/docker-desktop/>.
2. Download **Docker Desktop** for your system and install it like any normal
   program (double-click the installer, follow the prompts).
3. After installing, **open Docker Desktop** and leave it running. You'll know
   it's ready when its whale icon stops animating.
   - On Windows it may ask to install or update "WSL"; allow it and restart if
     prompted.

**Linux:**

Install Docker Engine and the Compose plugin by following the official guide for
your distribution: <https://docs.docker.com/engine/install/>. Make sure the
`docker compose` command works afterwards.

> 💡 **Docker Desktop must be running** whenever you want to use this app
> (Windows/macOS). If you reboot your computer, open Docker Desktop again first.

---

## Step 2 — Download this project

You have two ways to get the files. **If you're not sure, use Option A.**

### Option A — Download the ZIP (easiest)

1. On this project's GitHub page, click the green **`< > Code`** button.
2. Click **Download ZIP**.
3. Find the downloaded ZIP file and **unzip / extract it** (right-click →
   "Extract All" on Windows, or double-click on macOS).
4. You now have a folder with all the project files. Move it somewhere you'll
   remember — for example your Desktop. **Remember where this folder is**; you'll
   need it in the next step.

### Option B — Clone with Git (if you have Git)

1. On the GitHub page, click the green **`< > Code`** button and copy the HTTPS
   URL.
2. In a terminal, run (paste the URL you copied in place of `<URL>`):
   ```bash
   git clone <URL>
   ```

---

## Step 3 — Open a terminal *inside* the project folder

A "terminal" is a window where you type commands. You need to open one **inside
the project folder** (the folder that contains the file `docker-compose.yml`).

- **Windows 11:** Open the project folder, right-click an empty area inside it,
  and choose **"Open in Terminal"**.
- **Windows 10:** Open the project folder, click once on the address bar at the
  top, type `cmd`, and press **Enter**.
- **macOS:** Right-click the project folder and choose
  **"New Terminal at Folder"**. (If you don't see that option, enable it in
  System Settings → Keyboard → Keyboard Shortcuts → Services.)
- **Linux:** Right-click inside the folder in your file manager and choose
  **"Open Terminal Here"** (wording varies by system).

To check you're in the right place, type `ls` (macOS/Linux) or `dir` (Windows)
and press Enter — you should see `docker-compose.yml` listed.

---

## Step 4 — Start the app

In that terminal, type this command exactly and press **Enter**:

```bash
docker compose up -d --build
```

**The first time, this takes several minutes** — it downloads and assembles
everything. You'll see lots of text scroll by. That's normal. Wait until it
finishes and you get your normal prompt back.

When it's done, the app is running quietly in the background. You won't need this
terminal again unless you want to stop or update the app later.

> If you see an error mentioning **"port is already allocated"**, see
> [Troubleshooting](#troubleshooting).

---

## Step 5 — Open it in your browser

Open your web browser and go to:

```
http://localhost:8800
```

You should see the YT Downloader page. **That's it — setup is done.**

You can bookmark that address. As long as Docker is running, the app is too.

---

## How to use it

1. **Choose your format** at the top: **Audio** or **Video**, then the file type
   and quality.
2. **Paste a YouTube link** into the big box.
3. Click **Download**.
   - For a **single video**, your browser's normal "Save" download starts.
   - For a **playlist**, you'll see the list of videos. You can download each one
     with its own button, get them all as one **ZIP** file, or download them
     **one by one**.
4. Downloaded files land in your browser's usual **Downloads** folder.

---

## ⚠️ Important: YouTube sign-in (cookies)

YouTube often blocks downloads from tools like this with a *"Sign in to confirm
you're not a bot"* check — **playlists trip this especially often.** If your
downloads fail, this is almost always why.

The app shows a **yellow warning banner** at the top until you complete this
one-time setup. Here's how:

1. **Install a cookies extension** in your browser. A good free one is
   **"Get cookies.txt LOCALLY"** (search for it in the Chrome Web Store or
   Firefox Add-ons).
2. **Sign in to YouTube** normally in that browser.
3. With a **`youtube.com` tab open and focused**, click the extension's icon and
   press **Export** (not "Export All Cookies"). This saves a file called
   **`cookies.txt`**.
4. Move that `cookies.txt` file into the **`cookies`** folder inside this
   project (the same folder that has `docker-compose.yml` has a `cookies` folder
   next to it). The final location should be `cookies/cookies.txt`.
5. Reload the app page in your browser — the warning banner should disappear and
   downloads should work.

> 🔒 **Keep `cookies.txt` private.** It's like a key to your YouTube account —
> don't share it or upload it anywhere. (This project is set up to never include
> it if you share the code.)
>
> Cookies expire after a while. If downloads start failing again weeks or months
> later, just repeat the steps above to replace the file with a fresh one.

---

## Everyday commands

Run these in a terminal **inside the project folder** (see Step 3).

| What you want to do | Command |
|---|---|
| **Start** the app (after a reboot, etc.) | `docker compose up -d` |
| **Stop** the app | `docker compose down` |
| **Update** to the latest YouTube fixes | `docker compose up -d --build` |
| **See logs** (if something seems wrong) | `docker compose logs -f` (press `Ctrl+C` to exit) |

> **Why update?** YouTube changes things constantly, which can break downloading.
> Running the update command rebuilds the app with the newest `yt-dlp` (the
> engine that does the downloading). If downloads suddenly stop working, **update
> first.**

---

## Download options explained

- **Audio** — MP3, M4A, Opus, FLAC, or WAV. Bitrate options 320 / 256 / 192 / 128
  kbps (higher = better quality, bigger file). FLAC and WAV are lossless, so the
  bitrate setting doesn't apply to them.
- **Video** — MP4, WebM, or MKV, with a resolution cap from "Best" down to 360p.
- **Embed thumbnail** — saves the video's thumbnail as the file's cover art.
- **Embed metadata** — fills in title, artist, and chapter info inside the file.

---

## Troubleshooting

**"Port is already allocated" when starting**
Another program on your computer is using port 8800. Open `docker-compose.yml`
in a text editor, find the line `- "8800:8000"`, and change `8800` to another
number like `8900`. Save, run `docker compose up -d` again, and use
`http://localhost:8900` instead.

**"docker: command not found" or "Cannot connect to the Docker daemon"**
Docker isn't installed, or Docker Desktop isn't running. Revisit
[Step 1](#step-1--install-docker) and make sure Docker Desktop is open.

**Downloads fail, or a video shows a "sign-in" error**
YouTube is blocking the request. Set up cookies — see
[YouTube sign-in (cookies)](#️-important-youtube-sign-in-cookies) above.

**Downloads used to work and suddenly stopped**
YouTube probably changed something. Run `docker compose up -d --build` to update,
then try again.

**The page won't load at `http://localhost:8800`**
Give it a few seconds after starting. Make sure Docker is running and that
`docker compose up -d` finished without errors. Check `docker compose logs -f`.

**A playlist ZIP only contains some of the videos**
Some videos in the playlist are unavailable, private, or removed. The app skips
those automatically and lists them in an `_errors.txt` file inside the ZIP —
that's expected behaviour.

---

## Notes & limits

- It actually accepts links from ~1800 sites that `yt-dlp` supports, not just
  YouTube — the name just reflects the main use case.
- For **very large playlists**, the ZIP option can take a long time and use a lot
  of disk space temporarily. Downloading videos individually is gentler.
- This tool is meant for **personal use on your own machine / home network**. It
  has no password or accounts. Only download content you have the right to.

---

## For developers

Run it without Docker for development:

```bash
pip install -r requirements-dev.txt
pytest -m "not network"      # fast offline test suite
pytest                       # also runs network integration tests
WORK_DIR=$(mktemp -d) uvicorn app.app:app --reload
```

Tech stack: Python + FastAPI backend (`yt-dlp` as a library, `ffmpeg` for
conversion), a single static HTML/CSS/JS page, packaged with Docker. `yt-dlp` is
intentionally left unpinned so each image rebuild pulls the latest release.
