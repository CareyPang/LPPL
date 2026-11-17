'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const bundlePath = path.join(__dirname, '..', 'vendor', 'lppl-lwc', '1', 'lppl-lwc.js');
const manifest = require('../vendor/lppl-lwc/1/manifest.json');

test('committed LWC bundle matches its manifest and contains one 5.2.1 core', () => {
  const bundle = fs.readFileSync(bundlePath);
  const sha256 = createHash('sha256').update(bundle).digest('hex');

  assert.equal(sha256, manifest.bundle.sha256);
  assert.equal((bundle.toString('utf8').match(/5\.2\.1/g) || []).length, 1);
});
