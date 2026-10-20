"""Bounded browser transport. Kernel operations enqueue; cookies stay in the browser."""

import json
import os
import queue
import threading
import time
from uuid import UUID

from screamingface._analytics.endpoint import analytics_origin
from screamingface._analytics.ports import Consent, Event

_SCRIPT = r"""(async () => {
  const command = COMMAND, batch = BATCH;
  const origin = new URL(ANALYTICS_ORIGIN).origin;
  const frame = document.createElement('iframe');
  frame.hidden = true;
  frame.referrerPolicy = 'no-referrer';
  let listener, timer, expired = false;
  const work = async () => {
    await new Promise((resolve, reject) => {
      frame.onload = resolve;
      frame.onerror = reject;
      frame.src = origin + '/bridge/consent?parent_origin=' + encodeURIComponent(location.origin);
      document.body.appendChild(frame);
    });
    async function request(command, batch) {
      if (expired) throw Error('expired');
      return await new Promise((resolve, reject) => {
        const nonce = crypto.randomUUID();
        listener = event => {
          const data = event.data;
          if (event.source !== frame.contentWindow || event.origin !== origin ||
              !data || data.version !== 1 || data.nonce !== nonce ||
              data.command !== command) return;
          window.removeEventListener('message', listener);
          listener = null;
          if (data.error) reject(Error('unavailable')); else resolve(data.result);
        };
        window.addEventListener('message', listener);
        frame.contentWindow.postMessage({version:1, nonce, command,
          ...(command === 'events' ? {batch} : {})}, origin);
      });
    }
    return await request(command, batch);
  };
  try {
    return await Promise.race([work(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(Error('timeout')), TIMEOUT_MS);
    })]);
  } catch { return {choice:'unknown', unavailable:true}; }
  finally {
    expired = true;
    clearTimeout(timer);
    if (listener) window.removeEventListener('message', listener);
    frame.remove();
  }
})()"""


def exchange(command: str, event: Event | None = None, *, timeout_sec: float = 2) -> dict:
    from google.colab import output  # type: ignore[import-not-found]

    batch = (
        {"schema_version": 1, "consent_version": "1", "consent_granted": True, "events": [event]}
        if event is not None
        else None
    )
    script = _SCRIPT.replace("COMMAND", json.dumps(command)).replace("BATCH", json.dumps(batch))
    script = script.replace("ANALYTICS_ORIGIN", json.dumps(analytics_origin()))
    script = script.replace("TIMEOUT_MS", str(max(1, int(timeout_sec * 900))))
    return output.eval_js(script, timeout_sec=timeout_sec)


class ColabBridge:
    def __init__(self) -> None:
        self._state = Consent()
        self._generation = 0
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self.pending = False

    def read(self) -> Consent:
        with self._lock:
            return self._state

    def clear(self) -> None:
        # A coordinator session change drops events, not pending consent setup.
        with self._lock:
            kept = []
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item[1] != "events":
                    kept.append(item)
            for item in kept:
                self._queue.put_nowait(item)

    def control(self, command: str) -> None:
        with self._lock:
            if command == "state" and self.pending:
                return
            self._generation += 1
            self._state = Consent()
            self.pending = True
            self._drain()
            self._enqueue(command, None)

    def stop(self, *, persist: bool) -> None:
        with self._lock:
            self._generation += 1
            self._state = Consent("declined")
            self.pending = False
            self._drain()
            if persist:
                self.pending = True
                self._enqueue("decline", None)

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def emit(self, event: Event) -> None:
        with self._lock:
            if self._state.choice == "accepted" and len(json.dumps(event).encode()) <= 4096:
                self._enqueue("events", event.copy())

    def _enqueue(self, command: str, event: Event | None) -> None:
        try:
            self._queue.put_nowait((self._generation, command, event))
        except queue.Full:
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, daemon=True, name="sf-colab-analytics"
            )
            self._worker.start()

    def _run(self) -> None:
        while True:
            generation, command, event = self._queue.get()
            with self._lock:
                if generation != self._generation:
                    continue
            state = self._dispatch(generation, command, event)
            with self._lock:
                if generation != self._generation:
                    continue
                if state is not None:
                    self._state = state
                if command != "events":
                    self.pending = False
            if command == "state" and state is not None and state.choice == "unknown":
                from screamingface._analytics.prompt import NOTICE

                print(NOTICE)

    def _allowed(self, generation: int, command: str, event: Event | None) -> bool:
        from screamingface import analytics
        from screamingface._analytics.wiring import coordinator

        with self._lock:
            if generation != self._generation:
                return False
        dnt = os.getenv("DO_NOT_TRACK", "").strip().lower()
        if dnt not in {"", "0", "false", "no", "off"} or (
            command != "decline" and analytics._disabled()
        ):
            return False
        return event is None or coordinator().accepts(event)

    def _dispatch(self, generation: int, command: str, event: Event | None) -> Consent | None:
        steps = {
            "state": ("state", "id"),
            "accept": ("accept", "id"),
            "reset": ("decline", "accept", "id"),
        }.get(command, (command,))
        deadline = time.monotonic() + 2
        try:
            result = self._steps(generation, steps, event, deadline)
            return self._parse(result) if command != "events" or result.get("unavailable") else None
        except Exception:
            # Optional browser infrastructure must never kill product execution.
            return Consent()

    def _steps(self, generation: int, steps: tuple, event: Event | None, deadline: float) -> dict:
        result = {}
        for step in steps:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._allowed(generation, step, event):
                return {"unavailable": True}
            # Every exchange sends exactly one browser command. A late consent
            # response cannot start ID creation without this fresh consent check.
            result = exchange(step, event, timeout_sec=remaining)
            expected = "declined" if step == "decline" else "accepted"
            if result.get("consent_version") != "1" or result.get("choice") != expected:
                return result
        return result

    @staticmethod
    def _parse(result: dict) -> Consent:
        choice = result.get("choice")
        if result.get("consent_version") != "1" or choice != "accepted":
            return Consent(
                "declined"
                if choice == "declined" and result.get("consent_version") == "1"
                else "unknown"
            )
        if choice == "accepted" and result.get("id_scope") == "browser":
            value = result.get("persistent_id")
            if isinstance(value, str) and str(UUID(value)) == value and UUID(value).version == 4:
                return Consent("accepted", value)
        return Consent()


_instance: ColabBridge | None = None
_pid = os.getpid()


def bridge() -> ColabBridge:
    global _instance, _pid
    if _instance is None or _pid != os.getpid():
        _instance, _pid = ColabBridge(), os.getpid()
    return _instance
