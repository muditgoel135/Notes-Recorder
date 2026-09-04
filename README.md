# Notes Recorder

A small Flask app for recording class notes from the browser microphone, transcribing them automatically, extracting key points, and browsing saved notes.

## Features

- Record audio directly in the browser.
- Audio is recorded in chunks and uploaded in real-time to the server, ensuring that recordings are preserved even if the browser crashes or the page is refreshed.
- Use a robust session-based chunking system that saves audio segments into unique session folders on the server, supports reload recovery, and lets an in-progress recording be canceled.
- Choose a subject before recording; subjects are managed in-app (add or delete via **Manage Subjects**) rather than hardcoded, and a note's subject can be edited afterwards. Each note also carries a **unit** (a sub-category of its subject, e.g. a chapter; default "General") that is set when editing a note's subject and can be used to filter the notes list.
- Start, pause/resume, and stop recordings manually. Pausing stops the microphone stream while keeping the session alive, and the wall-clock gaps are excluded from the recording's reported duration so playback length stays accurate.
- Save recordings to the local `recordings/` folder.
- Upload existing audio files; uploads are added under the `Uploaded` subject by default and can be edited afterwards.
- Play saved recordings from the app.
- Audio is converted to 16 kHz mono with ffmpeg before transcription, then passed through the RNNoise denoiser (ffmpeg's `arnndn` filter with a vendored model) to suppress steady background noise such as fan or AC hum. The denoise pass is best-effort: a missing model file or a failed filter pass falls back to the plain converted audio. No FFT-style spectral filtering is applied — aggressive filters were found to destroy speech and cause hallucinated transcripts — and the original recording file is never modified. The same denoised audio feeds both Whisper and speaker diarization, so diarization always runs on denoised audio.
- Automatic background transcription using OpenAI Whisper (runs fully offline, once the model is downloaded), with a live progress bar showing percent complete. Before transcription, leading and trailing silence is trimmed with a lightweight energy-based voice-activity detector (keeping a small margin on each side), which makes Whisper faster and less prone to hallucinating on dead air; word timestamps are shifted back into the original recording's time domain so they stay aligned with playback.
- Speaker diarization: automatically detects and labels distinct speakers ("Speaker 1", "Speaker 2", ...) in the transcript, shown as color-coded badges. Speakers can be renamed per note (e.g. "Teacher"). Attribution is capped at 15 speakers so pyannote can't invent phantom speakers out of background noise or cross-talk. Requires a Hugging Face token; falls back to an undifferentiated transcript if not configured.
- Automatic title and key-points extraction from the transcript using Ollama's hosted API (requires internet; waits and retries automatically if offline). When diarization is available, key points are generated from the speaker-labeled transcript.
- Drop timestamp bookmarks while recording (via the **Mark** button or by pressing **M**) to flag important moments; they're saved to the session and shown as clickable chips in the transcript, jumping playback to that point in the audio.
- Chat with selected transcript-ready recordings using Ollama's hosted API, with saved chat sessions, renameable chat titles, message history stored in the app database, markdown-rendered assistant replies, and recording context that includes metadata, tags, rich-note text, key points, transcripts, embedded-video transcripts, and available note/video images.
- Inline editing of note title, key points, subject, date, and start time. Date/time edits preserve the original recording duration and recalculate the end time.
- Rich notes can be captured while recording and edited later. The editor supports headings, font size/family, bold/italic/underline/strikethrough, subscript/superscript, alignment, indentation, RTL blocks, ordered/bulleted/check lists, blockquotes, code blocks, links, text/highlight colors, tables, image uploads, video embeds, and inline math. The font family picker offers a wide set of web-safe fonts.
- Rich-note images are stored locally and included as image context when Ollama generates key points or answers chats about selected recordings.
- Render markdown tables in generated key points and chat answers.
- YouTube/Vimeo videos embedded in rich notes are automatically downloaded (yt-dlp) during key-points extraction: the video's audio is transcribed with Whisper and merged into the note's transcript, and keyframes are extracted with ffmpeg and sent to the model as image context. Supported pasted inputs include YouTube watch/short/embed URLs, youtu.be links, Vimeo URLs, and iframe embed code.
- Inline math editing: use the **Math** button in the rich editor to insert LaTeX, click an existing formula to edit it, and see rendered math preserved in saved notes and the transcript view.
- Retry transcription or key-points extraction at any time, not just after a failure. Retrying transcription also re-runs key-points extraction on the new transcript.
- Download a note's transcript (`.txt`) or key points (`.md`).
- Click a word in the transcript to jump playback to that point in the audio, with the current word highlighted as it plays. A **Sync transcript with audio playback** checkbox toggles this behavior on or off (remembered across visits).
- Hierarchical tags: organize notes with nested tags, each with a custom color, managed in-app via **Manage Tags** (add, edit, delete, or add a subtag), and filter the notes list by tag. Filtering by a parent tag includes its subtags.
- Search and filter notes by text, date range, time range, subject and unit, transcription/key-points status (pending, processing, completed, or failed), or whether a note has any saved user notes (**Empty notes only**). Results can be sorted by date, title, subject, or transcription/key-points status. Text search uses a SQLite FTS5 index (built on startup and kept in sync as notes are created, edited, transcribed, or deleted) for fast, relevance-ranked results over titles, subjects, units, transcripts, key points, and rich-note text; it falls back to plain substring matching on SQLite builds without FTS5.
- For notes recorded under the "Hindi" subject, transcription is tuned for Hindi speech (with English words/phrases transcribed in English) using a Hindi-specific prompt and language setting.
- Paginated notes list.
- Delete a note, which also removes its saved recording file.
- Batch operations on multiple recordings: select checkboxes (or select the whole filtered result set) to delete several notes at once, change the subject of several notes at once (resetting their unit to "General"), add one tag to many recordings, or export multiple recordings together as a zip (audio plus transcripts, key points, and rich-note text, plus a `summary.txt`).
- Pin a recording to keep it at the top of the list; pinned recordings are shown in a separate **Pinned recordings** section above the rest, regardless of the current sort order.
- Store recording, note, tag, speaker, subject, unit, and chat metadata in SQLite.
- CSRF protection: state-changing requests (POST/PUT/PATCH/DELETE) that arrive with an `Origin` or `Referer` header naming a different host are rejected with a 403, so a third-party site cannot forge requests against the app. Same-origin AJAX and clients that send no origin headers (curl, scripts) are unaffected. Sessions also use `SESSION_COOKIE_SAMESITE=Lax`.
- The SQLite database runs in WAL journal mode with a busy timeout and `synchronous=NORMAL`, so the background transcription worker and the request threads can read/write concurrently without "database is locked" errors.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- Browser `MediaRecorder` API
- Bootstrap
- NumPy (energy-based voice-activity detection for silence trimming)
- ffmpeg (audio conversion for Whisper)
- OpenAI Whisper (speech-to-text)
- pyannote.audio (speaker diarization)
- Ollama hosted API (title generation, key-points generation, and chat)

## Project Structure

```text
Notes-Recorder/
|-- app.py             # entry point: wires everything together, starts the app
|-- core/
|   |-- extensions.py   # Flask app + SQLAlchemy db instances
|   |-- config.py       # environment-derived settings and constants
|   `-- models.py       # Note, Speaker, Subject, Unit, Tag, and chat database models
|-- services/
|   |-- notes_query.py  # DB init/migration, FTS5 search index, and notes list querying
|   |-- note_images.py  # rich-note image extraction and Ollama image encoding helpers
|   |-- text_filters.py # markdown/rich-note HTML sanitization, display formatting, and Jinja template filters
|   |-- csrf.py         # cross-origin request rejection for state-changing routes
|   `-- video_embeds.py # embedded YouTube/Vimeo download, transcription, and keyframes
|-- audio/
|   |-- recordings.py       # audio file storage helpers
|   |-- audio_processing.py # audio prep, Whisper, diarization, progress tracking
|   |-- key_points.py       # Ollama title/key-point generation and formatting
|   `-- transcription.py    # transcription orchestration and job scheduling
|-- models/
|   `-- rnnoise/
|       `-- std.rnnn        # pretrained RNNoise denoiser model used by the arnndn filter
|-- routes/
|   |-- __init__.py     # imports submodules to register Flask view functions
|   |-- chat.py         # chat page, chat session management, Ollama chat
|   |-- notes.py        # notes listing, filters, and per-note updates
|   |-- recordings.py   # recording upload, recording session, and file-serving routes
|   |-- taxonomy.py     # subject, unit, and tag routes
|   `-- bulk.py         # bulk delete, subject, tagging, and export routes
|-- LICENSE.txt
|-- requirements.txt
|-- pytest.ini        # pytest configuration (testpaths = tests)
|-- tests/            # pytest suite (route integration, CSRF, key-points, filters, audio)
|-- templates/
|   |-- index.html
|   |-- chat.html
|   |-- _notes_list.html
|   |-- _rich_notes_editor.html
|   |-- _transcript.html
|   `-- _transcript_macros.html
|-- static/
|   |-- rich-editor.js  # rich editor commands, image/math/table tools, shared DOM helpers
|   |-- recording.js    # recording sessions, chunk uploads, active rich notes, reload recovery
|   |-- app.js          # entry point: DOM refs, status, global event listeners
|   |-- notes-list.js         # notes list polling, filters, selection state, transcript sync
|   |-- notes-list-actions.js # per-note edit/delete/pin/retry/download UI actions
|   |-- notes-list-bulk.js    # bulk subject, tag, delete, and zip export actions
|   |-- notes-list-tags.js    # tag/subject/unit management, filters, MathQuill modal setup
|   |-- chat.js         # client-side JS for chat session and recording picker workflows
|   |-- style.css
|   `-- bootstrap-css/, bootstrap-js/, vendor/  # vendored Bootstrap, jQuery, and MathQuill assets
|-- recordings/
`-- instance/
```

`recordings/` stores saved audio files. Rich-note images are stored under `recordings/note_images/`, and in-progress chunked recordings use `recordings/session_chunks/`. `instance/database.db` stores the SQLite database.

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

[ffmpeg](https://ffmpeg.org/download.html) must be installed and available on `PATH` — it's used both by Whisper to decode audio and to convert recordings to 16 kHz mono before transcription.

On Windows, install the **full-shared** build (which ships the DLLs that `pyannote.audio`/`torchcodec` need to decode audio). The regular (static) builds only ship `ffmpeg.exe`/`ffprobe.exe` and will trigger a warning like `torchcodec is not installed correctly so built-in audio decoding will fail`, leaving speaker diarization unable to load audio. The easiest way to get the shared build is:

```powershell
winget install --exact --id Gyan.FFmpeg.Shared
```

After installing (or updating any PATH-related install), restart your terminal so the new `PATH` takes effect. Verify it with `ffmpeg -version`.

Optional environment variables (e.g. in a `.env` file):

- `SECRET_KEY` — Flask session secret. If not set, a persistent random key is generated on first run and stored in `instance/secret_key` (gitignored), so sessions survive restarts without leaking a key into the repo.
- `WHISPER_MODEL` — Whisper model size to load (default `small`).
- `RNNOISE_MODEL` — path to the RNNoise model file used to denoise recordings before transcription and speaker diarization (default `models/rnnoise/std.rnnn`). Point it at another `.rnn` file to swap the model, or set it to an empty value to disable denoising.
- `DIARIZATION_MAX_SPEAKERS` — maximum number of speakers speaker diarization may attribute turns to (default `15`). Lower it for small classes or raise it for large ones.
- `OLLAMA_API_KEY` — API key for Ollama's hosted chat API. Required for title/key-points extraction and chatting with recordings; without it, transcription still works.
- `KEY_POINTS_RETRY_SECONDS` — how often (in seconds) to retry key-points extraction while there is no internet connection (default `30`).
- `KEY_POINTS_MAX_RETRIES` — how many consecutive offline retries of key-points extraction are allowed before the note is marked failed (default `5`); prevents an endless retry timer during a long outage.
- `VIDEO_KEYFRAME_COUNT` — how many keyframes per embedded video are extracted and sent to the model (default `6`). Keyframes are cached under `recordings/video_cache/`; the downloaded video/audio media is removed after processing.
- `OLLAMA_MODEL` — Ollama model used for key-points extraction and chat (default `minimax-m3`). Must be a vision-capable model so images in rich notes are sent along; e.g. `minimax-m3` (1M context) or `gemma4:cloud`. Text-only models like `gpt-oss:20b` reject image input.
- `TRANSCRIBE_EXISTING_ON_STARTUP` — set to `false` to skip re-queuing any pending transcriptions/key-points on startup (default `true`).
- `DEFAULT_PER_PAGE` — number of notes shown per page in the notes list (default `10`).
- The rich notes editor relies on vendored `jquery` and `MathQuill` assets in `static/vendor/`, and the UI uses vendored Bootstrap assets in `static/bootstrap-css/` and `static/bootstrap-js/`, so no npm install step is needed.
- Rich-note image uploads support `.png`, `.jpg`, `.jpeg`, `.gif`, and `.webp`. These images can be sent to Ollama as context for key-points extraction and chat.
- `HUGGINGFACE_TOKEN` — Hugging Face access token used for speaker diarization (`pyannote.audio`). Without it, transcripts still work but aren't split by speaker. To set one up:
  1. Create a free account at [huggingface.co](https://huggingface.co) and generate a **read**-scope token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
  2. Accept the model terms (with that same account) for [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1), [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), and [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
  3. Set `HUGGINGFACE_TOKEN=hf_...` in `.env`. The diarization model downloads and caches locally the first time it's used.

## Run

```powershell
python app.py
```

The built-in Flask server runs with debug mode disabled by default.

Open:

```text
http://127.0.0.1:5000/
```

## Tests

```powershell
pytest
```

The suite in `tests/` covers route integration (listings, search, filters, edits, bulk operations, chat), CSRF rejection, key-points JSON parsing, notes-list/recording/audio-processing helpers, and the FTS5 search index. Tests run against a throwaway SQLite database (via `conftest.py`) and never touch `instance/database.db`.

## Usage

1. Select a subject.
2. Click **Start Recording**.
3. Allow microphone permission in the browser.
4. Add live **Recording notes** while recording if useful; they auto-save into the active recording session.
5. Use **Pause**/**Resume** to take breaks without stopping, and **Mark** (or press **M**) to drop a timestamp bookmark at an important moment while recording.
6. Click **Stop Recording** when you are done.
7. The recording is saved and appears in the recordings list, including any rich notes captured during recording.
8. Transcription and key-points extraction run in the background; the list updates automatically as they complete, showing a live progress bar while transcription is in progress.
9. Edit a note's title, key points, rich notes, tags, subject (including its unit), or date/time inline if needed. Editing rich notes automatically queues fresh key-points extraction when a transcript exists.
10. Use **Retry transcription** (next to **Show full transcript**) or **Retry key points** (next to **Show key points**) to redo either step at any time -- including after a failure, or just to regenerate with an updated model.
11. Once transcription or key-points extraction complete, download them from the note's **Download transcript** / **Download key points** buttons.
12. Click a word in the transcript to jump the audio to that point; the word being spoken is highlighted during playback. Click a **bookmark chip** above the transcript to jump straight to a moment you marked while recording.
13. Use the rich notes toolbar to add formatting, links, checklists, blockquotes, code blocks, tables, uploaded images, video embeds, and LaTeX formulas. Existing formulas can be clicked to reopen them in the math editor.
14. When diarization is configured, each speaker turn shows a colored badge (e.g. "Speaker 1"); click a badge to rename that speaker for the note (e.g. "Teacher").
15. Assign hierarchical tags to a note and filter the notes list by tag. Use **Manage Tags** to create, edit (name/color), delete, or nest tags as subtags. Deleting a tag also deletes its subtags.
16. Use **Manage Subjects** to add or delete subjects, and to create or delete **units** (sub-categories like chapters) within a subject.
17. Filter the notes list by subject/unit, transcription status, key-points status, or "empty notes" using the dropdowns above the list, and reorder results with the **Sort by** dropdown (pinned recordings always come first).
18. Pin a recording to the top of the list with the pin button on its card, and unpin it the same way.
19. Select several recordings with their checkboxes — **This page** selects the current page and **Select all results** selects every note matching the current filters — then use the toolbar to **Change subject**, **Add tag**, **Export** (download a zip), **Clear**, or **Delete** them in bulk.
20. Click **Chat with Recordings** to start or reopen saved chats. The recording picker uses search, date, time, tag, and subject filters, returns up to 100 transcript-ready recordings, and only includes recordings with completed transcripts.
21. Select one or more recordings, click **Start chat** or send a first message to create the chat, then use **Rename** to update the saved chat title if needed.
22. Click **Delete** on a note to remove it, along with its saved recording file.

You can also upload existing `.wav`, `.mp3`, `.ogg`, `.webm`, `.m4a`, or `.mp4` audio files.

Use the search box and date/time filters above the notes list to find recordings, and page through results when there are many notes.

## Notes

- Browser microphone recording works on `localhost`/`127.0.0.1` and HTTPS pages.
- The app records from the browser microphone, not the server machine's microphone.
- While recording, the app warns before page unloads. If the page is refreshed anyway, it attempts to restore the active session from browser `localStorage` and continue uploading chunks after microphone access is allowed again. Paused state and timestamp bookmarks are preserved across reloads.
- Rich notes entered during an active recording are saved to the active session and recovered with the recording after reloads.
- Browser recording chunks are uploaded about every 2 seconds. If stopping the recorder fails because a chunk upload is still pending or failed, the local active-session record is kept so reload recovery can still finish the recording.
- Pausing the recorder flushes the current buffer so the paused stretch ends its own WebM segment, keeping the resumed audio concatenable; the assembled media then contains only recorded (non-paused) audio, and the reported duration excludes paused time. Timestamp bookmarks are saved to the session and debounced-synced to the server during recording, then carried over to the finished note and shown as jump chips in the transcript.
- WebM recordings are patched with duration metadata when possible so saved browser recordings report a useful playback length.
- Saved recording files are ignored by Git through `recordings/` in `.gitignore`.
- The app creates or updates its SQLite tables on startup, and seeds a default subject list (Math, Physics, Chemistry, Biology, English, Hindi, Individuals and Societies) the first time it runs with no subjects yet. Manage or replace these afterwards via **Manage Subjects**. Deleting a subject removes it from the picker; existing notes keep their stored subject text.
- If FTS5 is available in the active SQLite build, the full-text search index is created on first startup and fully backfilled so every existing note is immediately searchable. It is kept in sync on every note create, edit, transcription, key-points update, and delete — so search results are always up to date.
- Every note is assigned a unit that defaults to "General". Changing a note's subject keeps its unit only if that unit exists under the new subject, otherwise the unit resets to "General" (bulk subject changes also reset units to "General").
- Transcription and key-points extraction run one at a time in a background worker; large backlogs process sequentially. On startup, pending or interrupted transcriptions/key-point jobs are re-queued unless `TRANSCRIBE_EXISTING_ON_STARTUP=false`.
- The first transcription run downloads the selected Whisper model, which can take a while depending on model size and network speed.
- Before transcription, leading/trailing silence is trimmed by a lightweight energy-based voice-activity detector that derives an adaptive threshold from the recording's own noise floor and peak level. The detected speech span keeps a small silence margin on each side, and files where no speech is found are skipped rather than transcribed. Whisper's timestamps, which are relative to the trimmed audio, are shifted back so transcript words and bookmarks stay aligned with the original recording.
- The app can be used fully offline for recording and transcription. Key-points extraction needs internet access to reach Ollama; while offline it shows as "Extracting key points..." and retries automatically until a connection is available.
- Chatting with recordings also requires internet access and `OLLAMA_API_KEY`; if a request fails, the user's message remains saved in the chat history. Any images embedded in the selected rich notes are attached to the Ollama context.
- Embedded video transcription requires internet access (for yt-dlp downloads) and `yt-dlp` installed via `pip install -r requirements.txt`. Downloaded videos are stored temporarily in `recordings/video_cache/`; only the extracted keyframes and transcripts are kept afterwards. Video audio is transcribed with the same local Whisper model used for recordings.
- Embedded video keyframes are scene-detected first, then fall back to evenly spaced frames for static or low-motion videos. Chat uses cached keyframes only; it does not download new videos during chat requests.
- Speaker diarization requires internet access (and a valid `HUGGINGFACE_TOKEN`) the first time it downloads the diarization model; after that it runs locally like Whisper. The audio fed to diarization is denoised first (RNNoise, the same denoise pass that precedes Whisper), and speaker attribution is capped at `DIARIZATION_MAX_SPEAKERS` (default 15). If diarization fails or isn't configured, transcription still completes normally, just without speaker labels.
- Generated markdown is normalized before rendering so common LLM list-indentation mistakes are shown as lists instead of code blocks.
- Key-points extraction tolerates minor JSON formatting mistakes in Ollama's response (e.g. stray backslashes) by attempting to repair and re-parse them before failing.
- Inline math in rich notes is stored as sanitized HTML with a `data-latex` payload so the app can round-trip, render, and edit formulas safely.
- Rich-note video embeds are sanitized to HTTPS YouTube/YouTube-nocookie and Vimeo player embeds before rendering or processing.
- Rich-note HTML is sanitized with Bleach before rendering or converting to text for Ollama prompts; local rich-note image paths are validated before the image data is read.
- The vendored `models/rnnoise/std.rnnn` is the standard pretrained RNNoise denoiser model (Xiph.org, BSD-3-Clause), the one bundled with the reference RNNoise implementation. It is applied with ffmpeg's `arnndn` filter to denoise recordings before transcription and speaker diarization.

## AI Disclosure

This project was developed with the assistance of AI tools, including OpenCode (primary), ChatGPT, Claude, Ollama, and GitHub Copilot. Human oversight, review, and final decisions were applied to all AI-generated or AI-assisted output.
