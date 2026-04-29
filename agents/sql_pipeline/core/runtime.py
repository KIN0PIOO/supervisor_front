import threading


_STOP_EVENT = threading.Event()


def request_stop() -> None:
    _STOP_EVENT.set()


def clear_stop() -> None:
    _STOP_EVENT.clear()


def is_stop_requested() -> bool:
    return _STOP_EVENT.is_set()
