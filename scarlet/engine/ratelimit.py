import threading
import time


class RateLimiter:
    """Balde de fichas compartilhado por todas as conexões. rate=0 significa sem limite."""

    def __init__(self, rate=0):
        self._lock = threading.Lock()
        self.rate = 0
        self._tokens = 0.0
        self._last = time.monotonic()
        self.set_rate(rate)

    def set_rate(self, rate):
        with self._lock:
            self.rate = max(0, int(rate or 0))
            self._tokens = min(self._tokens, float(self.rate))
            self._last = time.monotonic()

    def consume(self, n, stop_event=None):
        while True:
            with self._lock:
                rate = self.rate
                if rate <= 0:
                    return
                now = time.monotonic()
                # Capacidade de 1/4 de segundo: evita rajadas grandes depois de uma pausa.
                self._tokens = min(rate / 4.0, self._tokens + (now - self._last) * rate)
                self._last = now
                if self._tokens > 0:
                    self._tokens -= n
                    return
                wait = -self._tokens / rate + 0.001
            wait = min(wait, 0.25)
            if stop_event is not None:
                if stop_event.wait(wait):
                    return
            else:
                time.sleep(wait)
