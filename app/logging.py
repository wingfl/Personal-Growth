# -*- coding: utf-8 -*-
"""统一日志：滚动文件 + 可选标准错误输出。

设计约束（见 docs/开发规范.md 与 ADR 系列）：

- 日志只用于**运行诊断**，不是审计。谁改了哪条档案由 `audit_log` 表负责，
  两者不要互相替代。
- **不记录密钥与原文**：对外调用只记长度、条数、耗时、状态码；资料正文、
  提示词全文、令牌一律不进日志（原文属于用户隐私，且可能很长）。
- 默认写到 `<项目>/data/logs/app.log`，单文件 2 MB、保留 5 份，UTF-8。
- 重复调用 `setup_logging()` 不会叠加 handler（幂等）。
"""
import logging
import logging.handlers
import os
import sys

LOGGER_NAME = "growth"
DEFAULT_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "logs")
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5


def get_logger(name=None):
    """取 growth 命名空间下的子 logger。"""
    if not name or name == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    if name.startswith(LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger("%s.%s" % (LOGGER_NAME, name))


def setup_logging(log_dir=None, level="INFO", to_stderr=False, force=False):
    """配置日志，返回根 logger（growth）。

    log_dir 为 None 时用 data/logs；创建目录失败则退回 stderr-only，绝不因为
    日志不可写而让主流程失败。
    """
    logger = logging.getLogger(LOGGER_NAME)
    numeric_level = level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.propagate = False
    if logger.handlers and not force:
        return logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)
    directory = log_dir or DEFAULT_LOG_DIR
    try:
        os.makedirs(directory, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(directory, "app.log"), maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:  # 日志不可写不能影响主流程
        to_stderr = True
        print("警告：日志文件不可写（%s），仅输出到标准错误" % exc, file=sys.stderr)
    if to_stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    if not logger.handlers:  # 极端情况：既无文件也无 stderr
        logger.addHandler(logging.NullHandler())
    return logger
