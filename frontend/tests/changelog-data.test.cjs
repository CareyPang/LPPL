const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

test('changelog history uses the static data adapter without GitHub API fetches', () => {
  const page = fs.readFileSync(path.join(__dirname, '..', 'changelog.html'), 'utf8');
  const adapter = fs.readFileSync(path.join(__dirname, '..', 'app', 'lppl-data.js'), 'utf8');

  assert.doesNotMatch(page, /api\.github\.com|raw\.githubusercontent\.com/);
  assert.match(page, /LPPL\.changelog\(\)/);
  assert.match(adapter, /changelog\s*=\s*\(\)\s*=>\s*opt\('changelog\.json'\)/);
});
