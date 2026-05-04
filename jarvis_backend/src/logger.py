import os
import logging
from logging.handlers import TimedRotatingFileHandler

# Define the logs directory at the root of the jarvis project
# jarvis/jarvis_backend/src/logger.py -> jarvis/logs
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)

# Create a logger object
logger = logging.getLogger("jarvis")
logger.setLevel(logging.DEBUG)  # Capture all levels of logs

# Create formatter
formatter = logging.Formatter(
    fmt="[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 1. File Handler: rotates at midnight every day
# It creates files like jarvis_backend.log.2023-10-25
file_handler = TimedRotatingFileHandler(
    filename=os.path.join(LOG_DIR, "jarvis_backend.log"),
    when="midnight",
    interval=1,
    backupCount=30,  # Keep 30 days of logs
    encoding="utf-8"
)
file_handler.suffix = "%Y-%m-%d"
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

# 2. Console Handler: outputs to terminal
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)  # Keep terminal less noisy (INFO and above)

# Add handlers
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

