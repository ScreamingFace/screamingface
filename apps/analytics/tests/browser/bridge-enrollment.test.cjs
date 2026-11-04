const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('conditional enrollment uses its own route and preserves the declined reply', async () => {
  let handler;
  const requests = [], replies = [];
  const parent = {postMessage: (data, origin) => replies.push({data, origin})};
  vm.runInNewContext(fs.readFileSync('src/analytics_service/bridge.js', 'utf8'), {
    allowedParents: ['https://output.example'],
    window: {parent, addEventListener: (_, callback) => {handler = callback;}},
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => ({choice: 'declined', consent_version: '1'})};
    },
    AbortController, TextEncoder, setTimeout, clearTimeout,
  });
  await handler({source: parent, origin: 'https://output.example',
    data: {version: 1, nonce: '0123456789abcdef', command: 'enroll'}});
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/bridge/consent/enroll');
  assert.deepEqual(JSON.parse(requests[0].options.body), {consent_version: '1'});
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(replies[0].data.result.choice, 'declined');
  assert.equal(replies[0].origin, 'https://output.example');
});
