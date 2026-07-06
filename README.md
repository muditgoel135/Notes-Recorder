# Notes Recorder

A small Flask app for recording class notes from the browser microphone, transcribing them automatically, extracting key points, and browsing saved notes.

## Features

- Record audio directly in the browser.
- Choose a subject before recording.
- Start and stop recordings manually.
- Save recordings to the local `recordings/` folder.
- Upload existing audio files.
- Play saved recordings from the app.
- Automatic background transcription using OpenAI Whisper.
- Automatic title and key-points extraction from the transcript using Ollama.
- Inline editing of note title and key points.
- Search and filter notes by text, date range, and time range.
- Paginated notes list.
- Store recording and note metadata in SQLite.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- Browser `MediaRecorder` API
- Bootstrap
- OpenAI Whisper (speech-to-text)
- Ollama API (title and key-points generation)

## Project Structure

```text
Notes-Recorder/
|-- app.py
|-- requirements.txt
|-- templates/
|   |-- index.html
|   `-- _notes_list.html
|-- static/
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

Optional environment variables (e.g. in a `.env` file):

- `SECRET_KEY` — Flask session secret.
- `WHISPER_MODEL` — Whisper model size to load (default `base`).
- `OLLAMA_API_KEY` — API key for Ollama's hosted chat API. Required for title/key-points extraction; without it, key-points extraction fails for each note but transcription still works.
- `OLLAMA_MODEL` — Ollama model used for key-points extraction (default `gpt-oss:20b`).
- `TRANSCRIBE_EXISTING_ON_STARTUP` — set to `false` to skip re-queuing any pending transcriptions/key-points on startup (default `true`).

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
6. Transcription and key-points extraction run in the background; the list updates automatically as they complete.
7. Edit a note's title or key points inline if needed.

You can also upload existing `.wav`, `.mp3`, `.ogg`, `.webm`, `.m4a`, or `.mp4` audio files.

Use the search box and date/time filters above the notes list to find recordings, and page through results when there are many notes.

## Notes

- Browser microphone recording works on `localhost`/`127.0.0.1` and HTTPS pages.
- The app records from the browser microphone, not the server machine's microphone.
- Saved recording files are ignored by Git through `recordings/` in `.gitignore`.
- The app creates or updates its SQLite tables on startup.
- Transcription and key-points extraction run one at a time in a background worker; large backlogs process sequentially.
- The first transcription run downloads the selected Whisper model, which can take a while depending on model size and network speed.
