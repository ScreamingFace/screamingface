"""Bounded browser transport. Kernel operations enqueue; cookies stay in the browser."""

import json
import os
import queue
import threading
import time
from dataclasses import replace
from uuid import UUID

from screamingface._analytics.endpoint import analytics_origin
from screamingface._analytics.ports import Consent, Event

BRIDGE_TIMEOUT = 5.0

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
  } catch (error) {
    return {choice:'unknown', unavailable:true,
      reason:error?.message === 'timeout' ? 'timeout' : 'unavailable'};
  }
  finally {
    expired = true;
    clearTimeout(timer);
    if (listener) window.removeEventListener('message', listener);
    frame.remove();
  }
})()"""


def exchange(
    command: str, event: Event | None = None, *, timeout_sec: float = BRIDGE_TIMEOUT
) -> dict:
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


class _ExchangeFailure(Exception):
    def __init__(self, reason: str, stage: str) -> None:
        self.reason, self.stage = reason, stage


class _ExchangeCancelled(Exception):
    pass


class ColabBridge:
    def __init__(self) -> None:
        self._state = Consent()
        self._generation = 0
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._worker: threading.Thread | None = None
        self.pending = False
        self._setup_generation: int | None = None
        self._notice_shown = False
        self._setup_attempts = 0
        self._last_error: str | None = None
        self._last_error_stage: str | None = None

    def read(self) -> Consent:
        with self._lock:
            return self._state

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "last_error": self._last_error,
                "last_error_stage": self._last_error_stage,
                "setup_attempts": self._setup_attempts,
            }

    def ensure_setup(self) -> None:
        from screamingface import analytics

        with self._lock:
            if not self.pending and self._state.choice == "unknown" and not analytics._disabled():
                self.control("setup")

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
            if command == "setup":
                self._setup_generation = self._generation
                self._setup_attempts += 1
            self._state = Consent()
            self.pending = True
            self._drain()
            self._enqueue(command, None)
            self._changed.notify_all()

    def setup_pending(self) -> bool:
        return self.setup_token() is not None

    def setup_token(self) -> int | None:
        with self._lock:
            if self.pending and self._setup_generation == self._generation:
                return self._generation
            return None

    def wait_for_generation(self, generation: int) -> None:
        with self._changed:
            if self.setup_token() == generation:
                self.wait_for_setup()

    def wait_for_setup(self) -> None:
        """Share the current attempt; each evaluation waits at most five seconds."""
        with self._changed:
            generation = self._setup_generation
            if not self.pending or generation != self._generation:
                return
            finished = self._changed.wait_for(
                lambda: generation != self._generation or not self.pending, timeout=BRIDGE_TIMEOUT
            )
            if not finished:
                self.expire_setup(generation)

    def expire_setup(self, generation: int | None = None, *, reason: str = "timeout") -> None:
        with self._changed:
            selected = self._setup_generation if generation is None else generation
            if self.pending and selected == self._setup_generation == self._generation:
                # INVARIANT: a late setup reply cannot enroll a timed-out kernel.
                self._record_error(self._generation, "setup", reason, "wait")
                self._generation += 1
                self._state = Consent()
                self.pending = False
                self._drain()
                self._changed.notify_all()

    def accept(self) -> None:
        """Confirm explicit opt-in within five seconds, including queue delay."""
        with self._changed:
            self.control("accept")
            generation = self._generation
            finished = self._changed.wait_for(
                lambda: generation != self._generation or not self.pending, timeout=BRIDGE_TIMEOUT
            )
            if not finished:
                # WHY: a timed-out opt-in must not silently enable tracking later.
                self._record_error(generation, "accept", "timeout", "wait")
                self._generation += 1
                self._state = Consent()
                self.pending = False
                self._drain()
                self._changed.notify_all()

    def stop(self, *, persist: bool) -> None:
        with self._lock:
            self._generation += 1
            self._state = Consent("declined")
            self.pending = False
            self._drain()
            if persist:
                self.pending = True
                self._enqueue("decline", None)
            self._changed.notify_all()

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def emit(self, event: Event) -> None:
        with self._lock:
            if self._state.choice == "accepted":
                if len(json.dumps(event).encode()) > 4096:
                    self._record_error(self._generation, "events", "event_too_large", "queue")
                else:
                    self._enqueue("events", event.copy())

    def _enqueue(self, command: str, event: Event | None) -> None:
        try:
            self._queue.put_nowait((self._generation, command, event))
        except queue.Full:
            self._record_error(self._generation, command, "queue_full", "queue")
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._run, daemon=True, name="sf-colab-analytics"
            )
            try:
                self._worker.start()
            except Exception:
                self._record_error(self._generation, command, "worker_unavailable", "worker")
                if command != "decline":
                    self._state = Consent()
                self._generation += 1
                self.pending = False
                self._drain()
                self._changed.notify_all()

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
                self._apply(generation, command, state)
                self._changed.notify_all()

    def _apply(self, generation: int, command: str, state: Consent | None) -> None:
        from screamingface import analytics

        if state is not None:
            if state.choice == "accepted" and analytics._disabled():
                state = Consent()
            if command != "decline":
                self._state = (
                    replace(state, revision=generation) if state.choice == "accepted" else state
                )
            if command == "events":
                # INVARIANT: discard queued events from an uncertain consent period.
                self._generation += 1
                self._drain()
        if command != "events":
            self.pending = False

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
        deadline = time.monotonic() + BRIDGE_TIMEOUT
        try:
            result = (
                self._setup(generation, deadline)
                if command == "setup"
                else self._steps(generation, steps, event, deadline)
            )
            return self._response(generation, command, result)
        except _ExchangeCancelled:
            return None
        except _ExchangeFailure as exc:
            self._record_error(generation, command, exc.reason, exc.stage)
        except Exception:
            # Optional browser infrastructure must never kill product execution.
            self._record_error(generation, command, "unavailable", "response")
        return Consent()

    def _record_error(self, generation: int, command: str, reason: str, stage: str) -> None:
        with self._lock:
            if generation == self._generation:
                prefix = "delivery" if command == "events" else command
                self._last_error, self._last_error_stage = f"{prefix}_{reason}", stage

    def _response(self, generation: int, command: str, result: dict) -> Consent | None:
        if command == "events" and result.get("status") == "upstream_accepted":
            state = None
        else:
            state = self._parse(result)
            if state.choice == "unknown":
                stage = "events" if command == "events" else "id"
                self._record_error(generation, command, "invalid_response", stage)
                return state
        with self._lock:
            if generation == self._generation:
                self._last_error = self._last_error_stage = None
        return state

    def _setup(self, generation: int, deadline: float) -> dict:
        from screamingface._analytics.prompt import show_notice

        result = self._steps(generation, ("state",), None, deadline)
        if result.get("consent_version") != "1" or result.get("unavailable"):
            return result
        if result.get("choice") == "unknown" and self._allowed(generation, "enroll", None):
            if not self._notice_shown:
                show_notice("colab")
                self._notice_shown = True
            result = self._steps(generation, ("enroll", "id"), None, deadline)
        elif result.get("choice") == "accepted":
            result = self._steps(generation, ("id",), None, deadline)
        return result

    def _steps(self, generation: int, steps: tuple, event: Event | None, deadline: float) -> dict:
        result = {}
        for step in steps:
            remaining = deadline - time.monotonic()
            if not self._allowed(generation, step, event):
                raise _ExchangeCancelled()
            if remaining <= 0:
                raise _ExchangeFailure("timeout", step)
            # Every exchange sends exactly one browser command. A late consent
            # response cannot start ID creation without this fresh consent check.
            result = self._exchange(step, event, remaining)
            if time.monotonic() > deadline:
                raise _ExchangeFailure("timeout", step)
            self._validate_reply(step, result)
            expected = "declined" if step == "decline" else "accepted"
            if result.get("consent_version") != "1" or result.get("choice") != expected:
                return result
        return result

    @staticmethod
    def _validate_reply(step: str, result: dict) -> None:
        if step == "events":
            return
        choices = (
            {"accepted", "declined", "unknown"} if step == "state" else {"accepted", "declined"}
        )
        choice = result.get("choice")
        if (
            result.get("consent_version") != "1"
            or not isinstance(choice, str)
            or choice not in choices
        ):
            raise _ExchangeFailure("invalid_response", step)
        if step == "id" and result.get("choice") == "accepted":
            if ColabBridge._parse(result).choice != "accepted":
                raise _ExchangeFailure("invalid_response", step)
        if step == "decline" and choice != "declined":
            raise _ExchangeFailure("invalid_response", step)

    @staticmethod
    def _exchange(step: str, event: Event | None, remaining: float) -> dict:
        try:
            result = exchange(step, event, timeout_sec=remaining)
        except Exception as exc:
            reason = "timeout" if isinstance(exc, TimeoutError) else "unavailable"
            raise _ExchangeFailure(reason, step) from None
        if not isinstance(result, dict):
            raise _ExchangeFailure("invalid_response", step)
        if result.get("unavailable"):
            reason = "timeout" if result.get("reason") == "timeout" else "unavailable"
            raise _ExchangeFailure(reason, step)
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
        value = result.get("persistent_id")
        if result.get("id_scope") == "browser" and isinstance(value, str):
            try:
                parsed = UUID(value)
                if str(parsed) == value and parsed.version == 4:
                    return Consent("accepted", value)
            except ValueError:
                pass
        return Consent()


_instance: ColabBridge | None = None
_pid = os.getpid()


def bridge() -> ColabBridge:
    global _instance, _pid
    if _instance is None or _pid != os.getpid():
        _instance, _pid = ColabBridge(), os.getpid()
    return _instance
