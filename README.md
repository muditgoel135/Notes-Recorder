# Notes Recorder

A small Flask app for recording class notes from the browser microphone, transcribing them automatically, extracting key points, and browsing saved notes.

## Features

- Record audio directly in the browser.
- Audio is recorded in chunks and uploaded in real-time to the server, ensuring that recordings are preserved even if the browser crashes or the page is refreshed.
- Use a robust session-based chunking system that saves audio segments into unique session folders on the server.
- Choose a subject before recording; subjects are managed in-app (add or delete via **Manage Subjects**) rather than hardcoded, and a note's subject can be edited afterwards.
- Start and stop recordings manually.
- Save recordings to the local `recordings/` folder.
- Upload existing audio files.
- Play saved recordings from the app.
- Audio is denoised with ffmpeg before transcription to improve accuracy.
- Automatic background transcription using OpenAI Whisper (runs fully offline, once the model is downloaded), with a live progress bar showing percent complete.
- Speaker diarization: automatically detects and labels distinct speakers ("Speaker 1", "Speaker 2", ...) in the transcript, shown as color-coded badges. Speakers can be renamed per note (e.g. "Teacher"). Requires a Hugging Face token; falls back to an undifferentiated transcript if not configured.
- Automatic title and key-points extraction from the transcript using Ollama's hosted API (requires internet; waits and retries automatically if offline). When diarization is available, key points are generated from the speaker-labeled transcript.
- Inline editing of note title and key points.
- Retry transcription or key-points extraction at any time, not just after a failure. Retrying transcription also re-runs key-points extraction on the new transcript.
- Download a note's transcript (`.txt`) or key points (`.md`).
- Click a word in the transcript to jump playback to that point in the audio, with the current word highlighted as it plays. A **Sync transcript with audio playback** checkbox toggles this behavior on or off (remembered across visits).
- Hierarchical tags: organize notes with nested tags, each with a custom color, managed in-app via **Manage Tags** (add, edit, or add a subtag), and filter the notes list by tag.
- Search and filter notes by text, date range, time range, and subject.
- For notes recorded under the "Hindi" subject, transcription is tuned for Hindi speech (with English words/phrases transcribed in English) using a Hindi-specific prompt and language setting.
- Paginated notes list.
- Delete a note, which also removes its saved recording file.
- Store recording and note metadata in SQLite.

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
- Ollama API (title and key-points generation)

## Project Structure

```text
Notes-Recorder/
|-- app.py             # entry point: wires everything together, starts the app
|-- extensions.py       # Flask app + SQLAlchemy db instances
|-- config.py           # environment-derived settings and constants
|-- models.py           # Note, Speaker, Subject, Tag database models
|-- notes_query.py      # DB init/migration and notes list querying
|-- recordings.py       # audio file storage helpers
|-- transcription.py    # Whisper transcription, diarization, Ollama key points
|-- routes.py           # Flask view functions
|-- text_filters.py     # Jinja template filters (markdown, from_json)
|-- requirements.txt
|-- templates/
|   |-- index.html
|   |-- _notes_list.html
|   |-- _transcript.html
|   `-- _transcript_macros.html
|-- static/
|   |-- app.js          # all client-side JS: recording, filters, tags, subjects, transcript sync
|   |-- style.css
|   `-- bootstrap-css/, bootstrap-js/  # vendored Bootstrap assets
|-- recordings/
`-- instance/
```

`recordings/` stores saved audio files. `instance/database.db` stores the SQLite database.

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

Optional environment variables (e.g. in a `.env` file):

- `SECRET_KEY` — Flask session secret.
- `WHISPER_MODEL` — Whisper model size to load (default `small`).
- `OLLAMA_API_KEY` — API key for Ollama's hosted chat API. Required for title/key-points extraction; without it, key-points extraction fails for each note but transcription still works.
- `KEY_POINTS_RETRY_SECONDS` — how often (in seconds) to retry key-points extraction while there is no internet connection (default `30`).
- `OLLAMA_MODEL` — Ollama model used for key-points extraction (default `gpt-oss:20b`).
- `TRANSCRIBE_EXISTING_ON_STARTUP` — set to `false` to skip re-queuing any pending transcriptions/key-points on startup (default `true`).
- `DEFAULT_PER_PAGE` — number of notes shown per page in the notes list (default `10`).
- `HUGGINGFACE_TOKEN` — Hugging Face access token used for speaker diarization (`pyannote.audio`). Without it, transcripts still work but aren't split by speaker. To set one up:
  1. Create a free account at [huggingface.co](https://huggingface.co) and generate a **read**-scope token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
  2. Accept the model terms (with that same account) for [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1), [pyannote/segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), and [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1).
  3. Set `HUGGINGFACE_TOKEN=hf_...` in `.env`. The diarization model downloads and caches locally the first time it's used.

## Run

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5000/
```

## Usage

1. Select a subject.
2. Click **Start Recording**.
3. Allow microphone permission in the browser.
4. Click **Stop Recording** when you are done.
5. The recording is saved and appears in the recordings list.
6. Transcription and key-points extraction run in the background; the list updates automatically as they complete, showing a live progress bar while transcription is in progress.
7. Edit a note's title, key points, or subject inline if needed. Use **Retry transcription** (next to **Show full transcript**) or **Retry key points** (next to **Show key points**) to redo either step at any time — including after a failure, or just to regenerate with an updated model.
8. Once transcription or key-points extraction complete, download them from the note's **Download transcript** / **Download key points** buttons.
9. Click a word in the transcript to jump the audio to that point; the word being spoken is highlighted during playback.
10. When diarization is configured, each speaker turn shows a colored badge (e.g. "Speaker 1"); click a badge to rename that speaker for the note (e.g. "Teacher").
11. Assign hierarchical tags to a note and filter the notes list by tag. Use **Manage Tags** to create, edit (name/color), or nest tags as subtags.
12. Use **Manage Subjects** to add or delete subjects available when starting a recording.
13. Filter the notes list by one or more subjects using the **Subject** dropdown.
14. Click **Delete** on a note to remove it, along with its saved recording file.

You can also upload existing `.wav`, `.mp3`, `.ogg`, `.webm`, `.m4a`, or `.mp4` audio files.

Use the search box and date/time filters above the notes list to find recordings, and page through results when there are many notes.

## Notes

- Browser microphone recording works on `localhost`/`127.0.0.1` and HTTPS pages.
- The app records from the browser microphone, not the server machine's microphone.
- Saved recording files are ignored by Git through `recordings/` in `.gitignore`.
- The app creates or updates its SQLite tables on startup, and seeds a default subject list (Math, Physics, Chemistry, Biology, English, Hindi, Individuals and Societies) the first time it runs with no subjects yet. Manage or replace these afterwards via **Manage Subjects**.
- Transcription and key-points extraction run one at a time in a background worker; large backlogs process sequentially.
- The first transcription run downloads the selected Whisper model, which can take a while depending on model size and network speed.
- The app can be used fully offline for recording and transcription. Key-points extraction needs internet access to reach Ollama; while offline it shows as "Extracting key points..." and retries automatically until a connection is available.
- Speaker diarization requires internet access (and a valid `HUGGINGFACE_TOKEN`) the first time it downloads the diarization model; after that it runs locally like Whisper. If diarization fails or isn't configured, transcription still completes normally, just without speaker labels.
- Key-points extraction tolerates minor JSON formatting mistakes in Ollama's response (e.g. stray backslashes) by attempting to repair and re-parse them before failing.
