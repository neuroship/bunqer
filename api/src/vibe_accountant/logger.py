"""Logging configuration for the application."""

import logging
import sys


class FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit for containerized environments."""

    def emit(self, record):
        super().emit(record)
        self.flush()


# Set level - always DEBUG for development
log_level = logging.DEBUG

# Create handler with stdout (more compatible with container logging)
handler = FlushingStreamHandler(sys.stdout)
handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

# Configure root logger to capture all logs
logging.basicConfig(
    level=log_level,
    handlers=[handler],
    force=True,  # Override any existing configuration
)

# Create our app logger
logger = logging.getLogger("vibe_accountant")
logger.setLevel(log_level)

# Also configure uvicorn loggers to use same format
for name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    uv_logger = logging.getLogger(name)
    uv_logger.setLevel(log_level)
