"""Colab browser transport: one bounded eval_js round trip to the analytics bridge frame."""

import json

from screamingface._analytics.endpoint import analytics_origin
from screamingface._analytics.ports import Event

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
    result = output.eval_js(script, timeout_sec=timeout_sec)
    if result is None:
        # WHY: Colab's eval_js returns None instead of raising when no reply arrives in time,
        # e.g. a background call made after its cell finished. Report it the way the script
        # reports its own timeout, so the bridge records `timeout`, not `invalid_response`.
        return {"choice": "unknown", "unavailable": True, "reason": "timeout"}
    return result
