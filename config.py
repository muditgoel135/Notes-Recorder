import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
NOTE_IMAGES_DIR = os.path.join(RECORDINGS_DIR, "note_images")

ALLOWED_EXTENSIONS = {"wav", "mp3", "ogg", "webm", "m4a", "mp4"}

TRANSCRIPTION_PENDING = "pending"
TRANSCRIPTION_PROCESSING = "processing"
TRANSCRIPTION_COMPLETED = "completed"
TRANSCRIPTION_FAILED = "failed"
WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")
TRANSCRIBE_EXISTING_ON_STARTUP = (
    os.environ.get("TRANSCRIBE_EXISTING_ON_STARTUP", "true").lower() != "false"
)

KEY_POINTS_PENDING = "pending"
KEY_POINTS_PROCESSING = "processing"
KEY_POINTS_COMPLETED = "completed"
KEY_POINTS_FAILED = "failed"
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_CHAT_URL = "https://ollama.com/api/chat"
KEY_POINTS_RETRY_SECONDS = int(os.environ.get("KEY_POINTS_RETRY_SECONDS", "30"))

DEFAULT_PER_PAGE = int(os.environ.get("DEFAULT_PER_PAGE", "10"))

HUGGINGFACE_TOKEN = os.environ.get("HUGGINGFACE_TOKEN", "")

HINDI_SUBJECT = "Hindi"
HINDI_INITIAL_PROMPT = (
    "यह एक हिंदी कक्षा की रिकॉर्डिंग है। बातचीत मुख्यतः हिंदी में है, "
    "लेकिन बीच-बीच में अंग्रेजी शब्द और वाक्य भी बोले जाते हैं, "
    "जिन्हें अंग्रेजी में ही लिखा जाना चाहिए।"
)
