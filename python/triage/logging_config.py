import os
import logging

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_initialized_loggers = set()


def get_log_level() -> int:
    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_str, logging.INFO)


def setup_logging(logger_name: str, log_file: str = "") -> logging.Logger:
    logger = logging.getLogger(logger_name)
    level = get_log_level()
    logger.setLevel(level)

    if logger_name in _initialized_loggers:
        return logger
    _initialized_loggers.add(logger_name)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    if log_file:
        file_path = os.path.join("/tmp", log_file)
        file_handler = logging.FileHandler(file_path)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger
