// Input: a JSON array of full Git blob IDs. Output: browser-decoded chart hashes.
'use strict';
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { once } = require('node:events');
const fs = require('node:fs');
const { Readable } = require('node:stream');
const { pipeline } = require('node:stream/promises');

async function readBatch(stream, ids) {
  const results = {};
  let index = 0;
  let header = '';
  let body = null;
  let filled = 0;
  for await (const chunk of stream) {
    let offset = 0;
    while (offset < chunk.length) {
      if (index >= ids.length) throw new Error('unexpected Git batch output');
      const id = ids[index];
      if (body === null) {
        const newline = chunk.indexOf(10, offset);
        const end = newline < 0 ? chunk.length : newline;
        header += chunk.toString('ascii', offset, end);
        if (header.length > 128) throw new Error('invalid Git batch header');
        if (newline < 0) break;
        const fields = header.split(' ');
        if (fields.length !== 3 || fields[0] !== id || fields[1] !== 'blob' ||
            !/^(0|[1-9]\d*)$/.test(fields[2])) {
          throw new Error('expected pinned Git blob ' + id);
        }
        body = Buffer.allocUnsafe(Number(fields[2]));
        header = '';
        filled = 0;
        offset = newline + 1;
      } else if (filled < body.length) {
        const count = Math.min(body.length - filled, chunk.length - offset);
        chunk.copy(body, filled, offset, offset + count);
        filled += count;
        offset += count;
      } else {
        if (chunk[offset++] !== 10) throw new Error('missing Git blob terminator');
        const objectHash = createHash(id.length === 40 ? 'sha1' : 'sha256')
          .update('blob ' + body.length + '\0').update(body).digest('hex');
        if (objectHash !== id) throw new Error('Git blob digest mismatch: ' + id);
        // Response.json() decodes UTF-8, strips an initial BOM and parses in JS.
        // Serialize the resulting value exactly as the chart verification code does.
        const decoded = JSON.parse(new TextDecoder().decode(body));
        results[id] = createHash('sha256').update(JSON.stringify(decoded), 'utf8').digest('hex');
        index++;
        body = null;
      }
    }
  }
  if (index !== ids.length || header || body !== null) throw new Error('truncated Git batch output');
  return results;
}

async function main() {
  const repo = process.argv[2];
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  if (!repo || !Array.isArray(input) ||
      input.some(id => typeof id !== 'string' || !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(id))) {
    throw new Error('expected a repository and an array of full Git object IDs');
  }
  const ids = [...new Set(input)];
  if (!ids.length) {
    process.stdout.write('{}');
    return;
  }
  const git = spawn('git', ['-C', repo, '--no-replace-objects', 'cat-file', '--batch'], {
    stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true,
  });
  try {
    const [[code], , result] = await Promise.all([
      once(git, 'close'),
      pipeline(Readable.from([ids.join('\n') + '\n']), git.stdin),
      readBatch(git.stdout, ids),
    ]);
    if (code !== 0) throw new Error('git cat-file failed: ' + code);
    process.stdout.write(JSON.stringify(result));
  } finally {
    if (git.exitCode === null) git.kill();
  }
}

main().catch(error => {
  process.stderr.write(error.message + '\n');
  process.exitCode = 1;
});
