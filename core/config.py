"""

Config variables for the Flask app.
This module loads environment variables from a .env file and defines configuration constants for the Flask application, including paths, allowed file extensions, transcription and key points statuses, and API keys.

"""

# Import required modules
import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR: str = os.path.join(BASE_DIR, "recordings")
NOTE_IMAGES_DIR: str = os.path.join(RECORDINGS_DIR, "note_images")
VIDEO_CACHE_DIR: str = os.path.join(RECORDINGS_DIR, "video_cache")


def _load_or_create_secret_key() -> str:
    """
    Return the app's secret key, generating a persistent random one on first use.

    Prefers SECRET_KEY from the environment. Otherwise it loads the key stored
    in instance/secret_key, creating that file with a fresh random key when it
    does not exist yet. instance/ is gitignored, so the generated key never
    leaks into the repository and survives restarts.

    :return: The app's secret key.
    :rtype: str
    """

    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    instance_dir = os.path.join(BASE_DIR, "instance")
    key_file = os.path.join(instance_dir, "secret_key")
    if os.path.isfile(key_file):
        with open(key_file, "r", encoding="utf-8") as key_handle:
            stored_key = key_handle.read().strip()
        if stored_key:
            return stored_key

    os.makedirs(instance_dir, exist_ok=True)
    generated_key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as key_handle:
        key_handle.write(generated_key)
    return generated_key


SECRET_KEY: str = _load_or_create_secret_key()

ALLOWED_EXTENSIONS: set[str] = {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}

TRANSCRIPTION_PENDING: str = "pending"
TRANSCRIPTION_PROCESSING: str = "processing"
TRANSCRIPTION_COMPLETED: str = "completed"
TRANSCRIPTION_FAILED: str = "failed"
WHISPER_MODEL_NAME: str = os.environ.get("WHISPER_MODEL", "small")
TRANSCRIBE_EXISTING_ON_STARTUP: bool = (
    os.environ.get("TRANSCRIBE_EXISTING_ON_STARTUP", "true").lower() != "false"
)

# RNNoise model used to denoise recordings before transcription (removes
# steady background noise such as fan or AC hum). Point this at another .rnn
# file to swap the model, or set it to an empty value to disable denoising.
RNNOISE_MODEL = os.environ.get(
    "RNNOISE_MODEL", os.path.join(BASE_DIR, "models", "rnnoise", "std.rnnn")
)

KEY_POINTS_PENDING: str = "pending"
KEY_POINTS_PROCESSING: str = "processing"
KEY_POINTS_COMPLETED: str = "completed"
KEY_POINTS_FAILED: str = "failed"
OLLAMA_API_KEY: str = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "minimax-m3")
OLLAMA_CHAT_URL: str = "https://ollama.com/api/chat"
KEY_POINTS_RETRY_SECONDS: int = int(os.environ.get("KEY_POINTS_RETRY_SECONDS", "30"))
KEY_POINTS_MAX_RETRIES: int = int(os.environ.get("KEY_POINTS_MAX_RETRIES", "5"))
VIDEO_KEYFRAME_COUNT: int = int(os.environ.get("VIDEO_KEYFRAME_COUNT", "6"))

DEFAULT_PER_PAGE: int = int(os.environ.get("DEFAULT_PER_PAGE", "10"))

DEFAULT_UNIT: str = "General"

HUGGINGFACE_TOKEN: str = os.environ.get("HUGGINGFACE_TOKEN", "")

# Maximum number of speakers speaker diarization may attribute turns to.
# Classrooms rarely exceed this; capping it stops pyannote from inventing
# phantom speakers out of background noise or cross-talk.
DIARIZATION_MAX_SPEAKERS: int = int(os.environ.get("DIARIZATION_MAX_SPEAKERS", "15"))

PORT: int = int(os.environ.get("PORT", "5000"))

HINDI_SUBJECT: str = "Hindi"
HINDI_INITIAL_PROMPT: str = (
    "यह एक हिंदी कक्षा की रिकॉर्डिंग है। बातचीत मुख्यतः हिंदी में है, "
    "लेकिन बीच-बीच में अंग्रेजी शब्द और वाक्य भी बोले जाते हैं, "
    "जिन्हें अंग्रेजी में ही लिखा जाना चाहिए।"
)
