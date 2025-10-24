"""YellowDB logging module.

Provides a singleton logger for YellowDB operations. Logs are written to both
console (stdout) and to a log file in the database directory.
"""

import logging
import sys

from .config import Config


class Logger:
    """Singleton logger for YellowDB operations.

    Logs messages to both console and file. The log level is configurable
    via the Config singleton. Uses Python's built-in logging module with
    custom formatting.

    Attributes:
        logger: The underlying Python logging.Logger instance
        _instance: Singleton instance
        _initialized: Flag to prevent re-initialization

    Example:
        >>> logger = Logger()
        >>> logger.info("Database started")
        >>> logger.error("Operation failed")

        Or using the helper function:

        >>> logger = get_logger()
        >>> logger.debug("Debug message")

    """

    _instance = None
    _initialized = False

    def __new__(cls):
        """Create or return the singleton Logger instance.

        Returns:
            The singleton Logger instance

        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the logger (only once due to singleton pattern).

        Sets up console and file handlers with appropriate formatters.
        File logs are written to logs/yellowdb.log in the data directory.
        """
        if Logger._initialized:
            return

        self.config = Config()

        self.logger = self._setup_logger()
        Logger._initialized = True

    def _setup_logger(self) -> logging.Logger:
        """Set up the Python logger with handlers and formatters.

        Creates console and file handlers with consistent formatting.
        File handler is optional and silently fails if file creation fails.

        Returns:
            Configured logging.Logger instance

        """
        logger = logging.getLogger("yellowdb")
        logger.setLevel(self.config.log_level)
        logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self.config.log_level)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

        try:
            log_directory = self.config.data_directory / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_directory / "yellowdb.log")
            file_handler.setLevel(self.config.log_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception:
            pass

        return logger

    def debug(self, message: str) -> None:
        """Log a debug-level message.

        Debug messages are typically not shown in production unless explicitly enabled.

        Args:
            message: The message to log

        """
        self.logger.debug(message)

    def info(self, message: str) -> None:
        """Log an informational message.

        Informational messages document normal operation progress.

        Args:
            message: The message to log

        Example:
            >>> logger.info("Database initialized")

        """
        self.logger.info(message)

    def warning(self, message: str) -> None:
        """Log a warning-level message.

        Warnings indicate potentially problematic situations that don't prevent operation.

        Args:
            message: The message to log

        Example:
            >>> logger.warning("Memory usage is high")

        """
        self.logger.warning(message)

    def error(self, message: str) -> None:
        """Log an error-level message.

        Errors indicate serious problems, though the system may continue to operate.

        Args:
            message: The message to log

        Example:
            >>> logger.error("Compaction failed: disk full")

        """
        self.logger.error(message)

    def critical(self, message: str) -> None:
        """Log a critical-level message.

        Critical messages indicate the most severe problems that may require immediate attention.

        Args:
            message: The message to log

        Example:
            >>> logger.critical("Database corruption detected")

        """
        self.logger.critical(message)


def get_logger() -> Logger:
    """Get the singleton Logger instance.

    Convenience function for obtaining the logger without explicitly calling Logger().

    Returns:
        The singleton Logger instance

    Example:
        >>> logger = get_logger()
        >>> logger.info("Starting operation")

    """
    return Logger()
