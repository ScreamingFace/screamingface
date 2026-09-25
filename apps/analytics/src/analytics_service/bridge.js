/* FEATURE: narrow, bounded transport for the Colab parent. No analytics SDK or storage JS. */
(() => {
  'use strict';
  let active = null;
  let generation = 0;
  const commands = new Set(['state', 'accept', 'decline', 'id', 'events']);
  function valid(message) {
    if (!message || typeof message !== 'object' || Array.isArray(message)) return false;
    const keys = message.command === 'events' ? ['version', 'nonce', 'command', 'batch'] :
      ['version', 'nonce', 'command'];
    return Object.keys(message).length === keys.length && keys.every(k => Object.hasOwn(message, k)) &&
      message.version === 1 && typeof message.nonce === 'string' &&
      /^[a-zA-Z0-9_-]{16,128}$/.test(message.nonce) && commands.has(message.command);
  }
  function requestFor(message) {
    switch (message.command) {
      case 'state': return ['/bridge/consent/state', null];
      case 'accept': return ['/bridge/consent', {choice:'accepted', consent_version:'1'}];
      case 'decline': return ['/bridge/consent', {choice:'declined', consent_version:'1'}];
      case 'id': return ['/bridge/id', {}];
      case 'events': return ['/bridge/id/events', message.batch];
    }
  }
  window.addEventListener('message', async event => {
    if (event.source !== window.parent || !allowedParents.includes(event.origin) ||
        !valid(event.data)) return;
    const message = event.data;
    const reply = data => event.source.postMessage({version:1, nonce:message.nonce,
      command:message.command, ...data}, event.origin);
    if (active && message.command !== 'decline') { reply({error:'busy'}); return; }
    // INVARIANT: decline invalidates late responses and clears this frame's pending send.
    if (active) active.abort();
    const current = ++generation;
    const controller = new AbortController();
    active = controller;
    const timer = setTimeout(() => controller.abort(), 2000);
    try {
      const [path, body] = requestFor(message);
      const serialized = body === null ? undefined : JSON.stringify(body);
      if (serialized && new TextEncoder().encode(serialized).length > 65536) throw Error('size');
      const response = await fetch(path, {method:body === null ? 'GET' : 'POST',
        credentials:'same-origin', cache:'no-store', redirect:'error',
        referrerPolicy:'no-referrer', signal:controller.signal,
        headers:body === null ? {} : {'Content-Type':'application/json'}, body:serialized});
      if (!response.ok) throw Error('unavailable');
      const result = await response.json();
      if (current === generation && !controller.signal.aborted) reply({result});
    } catch {
      if (current === generation) reply({error:'unavailable'});
    } finally {
      clearTimeout(timer);
      if (current === generation) active = null;
    }
  });
})();
