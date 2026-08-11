"""

Config variables for the Flask app.
This module loads environment variables from a .env file and defines configuration constants for the Flask application, including paths, allowed file extensions, transcription and key points statuses, and API keys.

"""

# Import required modules
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
NOTE_IMAGES_DIR = os.path.join(RECORDINGS_DIR, "note_images")
VIDEO_CACHE_DIR = os.path.join(RECORDINGS_DIR, "video_cache")

SECRET_KEY = os.environ.get("SECRET_KEY", "default_secret_key")

ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}

TRANSCRIPTION_PENDING = "pending"
TRANSCRIPTION_PROCESSING = "processing"
TRANSCRIPTION_COMPLETED = "completed"
TRANSCRIPTION_FAILED = "failed"
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
TRANSCRIBE_EXISTING_ON_STARTUP = (
    os.environ.get("TRANSCRIBE_EXISTING_ON_STARTUP", "true").lower() != "false"
)

# RNNoise model used to denoise recordings before transcription (removes
# steady background noise such as fan or AC hum). Point this at another .rnn
# file to swap the model, or set it to an empty value to disable denoising.
RNNOISE_MODEL = os.environ.get(
    "RNNOISE_MODEL", os.path.join(BASE_DIR, "models", "rnnoise", "std.rnnn")
)

KEY_POINTS_PENDING = "pending"
KEY_POINTS_PROCESSING = "processing"
KEY_POINTS_COMPLETED = "completed"
KEY_POINTS_FAILED = "failed"
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "minimax-m3")
OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
KEY_POINTS_RETRY_SECONDS = int(os.environ.get("KEY_POINTS_RETRY_SECONDS", "30"))
VIDEO_KEYFRAME_COUNT = int(os.environ.get("VIDEO_KEYFRAME_COUNT", "6"))

DEFAULT_PER_PAGE = int(os.environ.get("DEFAULT_PER_PAGE", "10"))

DEFAULT_UNIT = "General"

HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

HINDI_SUBJECT = "Hindi"
HINDI_INITIAL_PROMPT = (
    "यह एक हिंदी कक्षा की रिकॉर्डिंग है। बातचीत मुख्यतः हिंदी में है, "
    "लेकिन बीच-बीच में अंग्रेजी शब्द और वाक्य भी बोले जाते हैं, "
    "जिन्हें अंग्रेजी में ही लिखा जाना चाहिए।"
)
