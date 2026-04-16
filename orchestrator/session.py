from collections import deque


class Session:
    def __init__(self, max_turns: int = 10):
        self._history: deque = deque(maxlen=max_turns * 2)

    def append(self, user_msg: str, assistant_msg: str):
        self._history.extend([
            {"role": "user",      "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ])

    def get_history(self) -> list:
        return list(self._history)

    def clear(self):
        self._history.clear()
