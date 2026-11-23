OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen2.5-coder:3b"

MAX_REPAIR_ITERATIONS = 5
SANDBOX_DRY_RUN_TIMEOUT = 4.0  # Seconds to test if the game initializes without crashing

# Modules blocked inside the generated game code for security
FORBIDDEN_IMPORTS = {
    "subprocess", "shutil", "socket", "urllib", "requests",
    "http", "ftplib", "telnetlib", "ctypes", "multiprocessing"
}
