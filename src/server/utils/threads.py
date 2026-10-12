"""
Утилиты для фоновых потоков.
"""

import logging

logger = logging.getLogger(__name__)


def run_logged(target, *args, **kwargs):
    """
    Выполнить функцию потока, записав любое исключение в лог с traceback.

    Поток, запущенный через threading.Thread без обработчика, молча теряет
    исключение (оно попадает лишь в stderr) — пользователь видит «запущено»,
    а в логе приложения ничего нет.
    """
    try:
        target(*args, **kwargs)
    except Exception:
        logger.exception(
            "Ошибка в фоновом потоке %s", getattr(target, "__name__", repr(target))
        )
