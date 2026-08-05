# Notes Recorder

A small Flask app for recording class notes from the browser microphone, transcribing them automatically, extracting key points, and browsing saved notes.

## Features

- Record audio directly in the browser.
- Audio is recorded in chunks and uploaded in real-time to the server, ensuring that recordings are preserved even if the browser crashes or the page is refreshed.
- Use a robust session-based chunking system that saves audio segments into unique session folders on the server, supports reload recovery, and lets an in-progress recording be canceled.
- Choose a subject before recording; subjects are managed in-app (add or delete via **Manage Subjects**) rather than hardcoded, and a note's subject can be edited afterwards. Each note also carries a **unit** (a sub-category of its subject, e.g. a chapter; default "General") that is set when editing a note's subject and can be used to filter the notes list.
- Start and stop recordings manually.
- Save recordings to the local `recordings/` folder.
- Upload existing audio files; uploads are added under the `Uploaded` subject by default and can be edited afterwards.
- Play saved recordings from the app.
- Audio is denoised with ffmpeg before transcription to improve accuracy.
- Automatic background transcription using OpenAI Whisper (runs fully offline, once the model is downloaded), with a live progress bar showing percent complete.
- Speaker diarization: automatically detects and labels distinct speakers ("Speaker 1", "Speaker 2", ...) in the transcript, shown as color-coded badges. Speakers can be renamed per note (e.g. "Teacher"). Requires a Hugging Face token; falls back to an undifferentiated transcript if not configured.
- Automatic title and key-points extraction from the transcript using Ollama's hosted API (requires internet; waits and retries automatically if offline). When diarization is available, key points are generated from the speaker-labeled transcript.
- Chat with selected transcript-ready recordings using Ollama's hosted API, with saved chat sessions, renameable chat titles, and message history stored in the app database.
- Inline editing of note title, key points, subject, date, and start time. Date/time edits preserve the original recording duration and recalculate the end time.
- Rich notes can be captured while recording and edited later. The editor supports headings, bold/italic/underline, lists, links, text/highlight colors, tables, image uploads, and inline math.
- Rich-note images are stored locally and included as image context when Ollama generates key points or answers chats about selected recordings.
- YouTube/Vimeo videos embedded in rich notes are automatically downloaded (yt-dlp) during key-points extraction: the video's audio is transcribed with Whisper and merged into the note's transcript, and keyframes are extracted with ffmpeg and sent to the model as image context.
- Inline math editing: use the **Math** button in the rich editor to insert LaTeX, click an existing formula to edit it, and see rendered math preserved in saved notes and the transcript view.
- Retry transcription or key-points extraction at any time, not just after a failure. Retrying transcription also re-runs key-points extraction on the new transcript.
- Download a note's transcript (`.txt`) or key points (`.md`).
- Click a word in the transcript to jump playback to that point in the audio, with the current word highlighted as it plays. A **Sync transcript with audio playback** checkbox toggles this behavior on or off (remembered across visits).
- Hierarchical tags: organize notes with nested tags, each with a custom color, managed in-app via **Manage Tags** (add, edit, delete, or add a subtag), and filter the notes list by tag. Filtering by a parent tag includes its subtags.
- Search and filter notes by text, date range, time range, subject and unit, transcription/key-points status (pending, processing, completed, or failed), or whether a note has any saved user notes (**Empty notes only**). Results can be sorted by date, title, subject, or transcription/key-points status.
- Render markdown tables in generated key points and chat answers.
- For notes recorded under the "Hindi" subject, transcription is tuned for Hindi speech (with English words/phrases transcribed in English) using a Hindi-specific prompt and language setting.
- Paginated notes list.
- Delete a note, which also removes its saved recording file.
- Batch operations on multiple recordings: select checkboxes (or select the whole filtered result set) to delete several notes at once, change the subject of several notes at once (resetting their unit to "General"), add one tag to many recordings, or export multiple recordings together as a zip (audio plus transcripts, key points, and rich-note text, plus a `summary.txt`).
- Pin a recording to keep it at the top of the list; pinned recordings are shown in a separate **Pinned recordings** section above the rest, regardless of the current sort order.
- Store recording, note, tag, speaker, subject, unit, and chat metadata in SQLite.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- Browser `MediaRecorder` API
- Bootstrap
- ffmpeg (audio denoising)
- OpenAI Whisper (speech-to-text)
- pyannote.audio (speaker diarization)
- Ollama API (title generation, key-points generation, and chat)

## Project Structure

```text
Notes-Recorder/
|-- app.py             # entry point: wires everything together, starts the app
|-- core/
|   |-- extensions.py   # Flask app + SQLAlchemy db instances
|   |-- config.py       # environment-derived settings and constants
|   `-- models.py       # Note, Speaker, Subject, Unit, Tag, and chat database models
|-- services/
|   |-- notes_query.py  # DB init/migration and notes list querying
|   |-- note_images.py  # rich-note image extraction and Ollama image encoding helpers
|   |-- text_filters.py # Jinja template filters (markdown, from_json)
|   `-- video_embeds.py # embedded YouTube/Vimeo download, transcription, and keyframes
|-- audio/
|   |-- recordings.py       # audio file storage helpers
|   `-- transcription.py    # Whisper transcription, diarization, Ollama key points
|-- routes/
|   |-- __init__.py     # imports submodules to register Flask view functions
|   |-- chat.py         # chat page, chat session management, Ollama chat
|   |-- notes.py        # notes listing, filters, and per-note updates
|   |-- recordings.py   # recording upload, recording session, and file-serving routes
|   |-- taxonomy.py     # subject, unit, and tag routes
|   `-- bulk.py         # bulk delete, subject, tagging, and export routes
|-- LICENSE.txt
|-- requirements.txt
|-- templates/
|   |-- index.html
|   |-- chat.html
|   |-- _notes_list.html
|   |-- _rich_notes_editor.html
|   |-- _transcript.html
|   `-- _transcript_macros.html
|-- static/
|   |-- app.js          # recording, active rich notes, rich editor commands, image/math tools
|   |-- notes-list.js   # notes list interactions, filters, tags, subjects, transcript sync
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

[ffmpeg](https://ffmpeg.org/download.html) must be installed and available on `PATH` — it's used both by Whisper to decode audio and to denoise recordings before transcription.

On Windows, install the **full-shared** build (which ships the DLLs that `pyannote.audio`/`torchcodec` need to decode audio). The regular (static) builds only ship `ffmpeg.exe`/`ffprobe.exe` and will trigger a warning like `torchcodec is not installed correctly so built-in audio decoding will fail`, leaving speaker diarization unable to load audio. The easiest way to get the shared build is:

```powershell
winget install --exact --id Gyan.FFmpeg.Shared
```

After installing (or updating any PATH-related install), restart your terminal so the new `PATH` takes effect. Verify it with `ffmpeg -version`.

Optional environment variables (e.g. in a `.env` file):

- `SECRET_KEY` — Flask session secret.
- `WHISPER_MODEL` — Whisper model size to load (default `small`).
- `OLLAMA_API_KEY` — API key for Ollama's hosted chat API. Required for title/key-points extraction and chatting with recordings; without it, transcription still works.
- `KEY_POINTS_RETRY_SECONDS` — how often (in seconds) to retry key-points extraction while there is no internet connection (default `30`).
- `VIDEO_KEYFRAME_COUNT` — how many keyframes per embedded video are extracted and sent to the model (default `6`). Keyframes are cached under `recordings/video_cache/`.
- `OLLAMA_MODEL` — Ollama model used for key-points extraction and chat (default `minimax-m3`). Must be a vision-capable model so images in rich notes are sent along; e.g. `minimax-m3` (1M context) or `gemma4:cloud`. Text-only models like `gpt-oss:20b` reject image input.
- `TRANSCRIBE_EXISTING_ON_STARTUP` — set to `false` to skip re-queuing any pending transcriptions/key-points on startup (default `true`).
- `DEFAULT_PER_PAGE` — number of notes shown per page in the notes list (default `10`).
- The rich notes editor relies on vendored `jquery` and `MathQuill` assets in `static/vendor/`, so no extra npm install step is needed for math editing.
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

## Usage

1. Select a subject.
2. Click **Start Recording**.
3. Allow microphone permission in the browser.
4. Add live **Recording notes** while recording if useful; they auto-save into the active recording session.
5. Click **Stop Recording** when you are done.
6. The recording is saved and appears in the recordings list, including any rich notes captured during recording.
7. Transcription and key-points extraction run in the background; the list updates automatically as they complete, showing a live progress bar while transcription is in progress.
8. Edit a note's title, key points, rich notes, tags, subject (including its unit), or date/time inline if needed. Editing rich notes automatically queues fresh key-points extraction when a transcript exists.
9. Use **Retry transcription** (next to **Show full transcript**) or **Retry key points** (next to **Show key points**) to redo either step at any time -- including after a failure, or just to regenerate with an updated model.
10. Once transcription or key-points extraction complete, download them from the note's **Download transcript** / **Download key points** buttons.
11. Click a word in the transcript to jump the audio to that point; the word being spoken is highlighted during playback.
12. Use the rich notes toolbar to add formatting, links, tables, uploaded images, and LaTeX formulas. Existing formulas can be clicked to reopen them in the math editor.
13. When diarization is configured, each speaker turn shows a colored badge (e.g. "Speaker 1"); click a badge to rename that speaker for the note (e.g. "Teacher").
14. Assign hierarchical tags to a note and filter the notes list by tag. Use **Manage Tags** to create, edit (name/color), delete, or nest tags as subtags. Deleting a tag also deletes its subtags.
15. Use **Manage Subjects** to add or delete subjects, and to create or delete **units** (sub-categories like chapters) within a subject.
16. Filter the notes list by subject/unit, transcription status, key-points status, or "empty notes" using the dropdowns above the list, and reorder results with the **Sort by** dropdown (pinned recordings always come first).
17. Pin a recording to the top of the list with the pin button on its card, and unpin it the same way.
18. Select several recordings with their checkboxes — **This page** selects the current page and **Select all results** selects every note matching the current filters — then use the toolbar to **Change subject**, **Add tag**, **Export** (download a zip), **Clear**, or **Delete** them in bulk.
19. Click **Chat with Recordings** to start or reopen saved chats. The recording picker uses the current search/date/time/tag/subject filters and only includes recordings with completed transcripts.
20. Select one or more recordings, click **Start chat** or send a first message to create the chat, then use **Rename** to update the saved chat title if needed.
21. Click **Delete** on a note to remove it, along with its saved recording file.

You can also upload existing `.wav`, `.mp3`, `.ogg`, `.webm`, `.m4a`, or `.mp4` audio files.

Use the search box and date/time filters above the notes list to find recordings, and page through results when there are many notes.

## Notes

- Browser microphone recording works on `localhost`/`127.0.0.1` and HTTPS pages.
- The app records from the browser microphone, not the server machine's microphone.
- While recording, the app warns before page unloads. If the page is refreshed anyway, it attempts to restore the active session from browser `localStorage` and continue uploading chunks after microphone access is allowed again.
- Rich notes entered during an active recording are saved to the active session and recovered with the recording after reloads.
- WebM recordings are patched with duration metadata when possible so saved browser recordings report a useful playback length.
- Saved recording files are ignored by Git through `recordings/` in `.gitignore`.
- The app creates or updates its SQLite tables on startup, and seeds a default subject list (Math, Physics, Chemistry, Biology, English, Hindi, Individuals and Societies) the first time it runs with no subjects yet. Manage or replace these afterwards via **Manage Subjects**. Deleting a subject removes it from the picker; existing notes keep their stored subject text.
- Every note is assigned a unit that defaults to "General". Changing a note's subject keeps its unit only if that unit exists under the new subject, otherwise the unit resets to "General" (bulk subject changes also reset units to "General").
- Transcription and key-points extraction run one at a time in a background worker; large backlogs process sequentially. On startup, pending or interrupted transcriptions/key-point jobs are re-queued unless `TRANSCRIBE_EXISTING_ON_STARTUP=false`.
- The first transcription run downloads the selected Whisper model, which can take a while depending on model size and network speed.
- The app can be used fully offline for recording and transcription. Key-points extraction needs internet access to reach Ollama; while offline it shows as "Extracting key points..." and retries automatically until a connection is available.
- Chatting with recordings also requires internet access and `OLLAMA_API_KEY`; if a request fails, the user's message remains saved in the chat history. Any images embedded in the selected rich notes are attached to the Ollama context.
- Embedded video transcription requires internet access (for yt-dlp downloads) and `yt-dlp` installed via `pip install -r requirements.txt`. Downloaded videos are stored temporarily in `recordings/video_cache/`; only the extracted keyframes and transcripts are kept afterwards. Video audio is transcribed with the same local Whisper model used for recordings.
- Speaker diarization requires internet access (and a valid `HUGGINGFACE_TOKEN`) the first time it downloads the diarization model; after that it runs locally like Whisper. If diarization fails or isn't configured, transcription still completes normally, just without speaker labels.
- Generated markdown is normalized before rendering so common LLM list-indentation mistakes are shown as lists instead of code blocks.
- Key-points extraction tolerates minor JSON formatting mistakes in Ollama's response (e.g. stray backslashes) by attempting to repair and re-parse them before failing.
- Inline math in rich notes is stored as sanitized HTML with a `data-latex` payload so the app can round-trip, render, and edit formulas safely.
- Rich-note HTML is sanitized with Bleach before rendering or converting to text for Ollama prompts; local rich-note image paths are validated before the image data is read.
