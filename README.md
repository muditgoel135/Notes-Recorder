# Notes Recorder

A small Flask app for recording class notes from the browser microphone, saving the audio locally, and listing saved recordings for playback.

## Features

- Record audio directly in the browser.
- Choose a subject before recording.
- Auto-stop after a chosen duration, or stop manually.
- Save recordings to the local `recordings/` folder.
- Store recording metadata in SQLite.
- Upload existing audio files.
- Play saved recordings from the app.

## Tech Stack

- Python
- Flask
- Flask-SQLAlchemy
- SQLite
- Browser `MediaRecorder` API
- Bootstrap

## Project Structure

```text
Notes-Recorder/
|-- app.py
|-- requirements.txt
|-- templates/
|   `-- index.html
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

Optional: create a `.env` file or set a `SECRET_KEY` environment variable for Flask sessions.

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
2. Enter a recording duration in seconds.
3. Click **Start Recording**.
4. Allow microphone permission in the browser.
5. Click **Stop Recording**, or wait for the duration to finish.
6. The recording is saved and appears in the recordings list.

You can also upload existing `.wav`, `.mp3`, `.ogg`, `.webm`, `.m4a`, or `.mp4` audio files.

## Notes

- Browser microphone recording works on `localhost`/`127.0.0.1` and HTTPS pages.
- The app records from the browser microphone, not the server machine's microphone.
- Saved recording files are ignored by Git through `recordings/` in `.gitignore`.
- The app creates or updates its SQLite tables on startup.
