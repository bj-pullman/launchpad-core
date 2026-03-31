import json
import queue
import threading
from collections import defaultdict


_subscribers: dict[str, set[queue.Queue]] = defaultdict(set)
_lock = threading.Lock()


def subscribe(department_name: str) -> queue.Queue:
    q = queue.Queue()
    with _lock:
        _subscribers[department_name].add(q)
    return q


def unsubscribe(department_name: str, q: queue.Queue):
    with _lock:
        subscribers = _subscribers.get(department_name)
        if not subscribers:
            return

        subscribers.discard(q)

        if not subscribers:
            _subscribers.pop(department_name, None)


def publish_department_update(department_name: str):
    payload = json.dumps(
        {
            "type": "department_updated",
            "department": department_name,
        }
    )

    with _lock:
        subscribers = list(_subscribers.get(department_name, set()))

    for q in subscribers:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass