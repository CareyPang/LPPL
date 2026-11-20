'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const { execFileSync, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const script = path.resolve(__dirname, '../../scripts/archive_chart_digests.cjs');

function repoFor(t) {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'lppl-chart-digest-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));
  execFileSync('git', ['init', '--quiet', repo]);
  return repo;
}

function store(repo, text) {
  return execFileSync('git', ['-C', repo, 'hash-object', '-w', '--stdin'], {
    input: Buffer.from(text, 'utf8'), encoding: 'utf8',
  }).trim();
}

function call(repo, ids) {
  return spawnSync(process.execPath, [script, repo], { input: JSON.stringify(ids), encoding: 'utf8' });
}

test('pinned blob digests match Response.json / Web Crypto for archived price values', async t => {
  const repo = repoFor(t);
  const samples = [
    '\uFEFF{ "10":0.000001, "2": 1e-7, "zero":-0.0, "上海":"金价", "surrogate":"\\ud800", "v":1, "v":2 }\r\n',
    '{ "large": 9007199254740993, "series": [' + '1.23000,'.repeat(25000) + '0] }',
    '{"a":2.0}',
    '{ "a": 2 }\n',
  ];
  const ids = samples.map(text => store(repo, text));
  const command = call(repo, [...ids, ids[0]]);
  assert.equal(command.status, 0, command.stderr);
  const result = JSON.parse(command.stdout);
  assert.deepEqual(Object.keys(result), ids);
  for (const [index, sample] of samples.entries()) {
    const decoded = await new Response(Buffer.from(sample, 'utf8')).json();
    const digest = await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(decoded)));
    assert.equal(result[ids[index]], Buffer.from(digest).toString('hex'));
  }
  assert.equal(result[ids[2]], result[ids[3]]);
});

test('missing blobs, invalid JSON, and non-OID refs cannot produce a partial index', t => {
  const repo = repoFor(t);
  const valid = store(repo, '{"ok":true}');
  const invalid = store(repo, '{oops}');
  assert.equal(call(repo, []).stdout, '{}');
  for (const id of [invalid, '0'.repeat(40), 'HEAD']) {
    const command = call(repo, [valid, id]);
    assert.notEqual(command.status, 0);
    assert.equal(command.stdout, '');
  }
});
