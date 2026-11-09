#!/usr/bin/env node
/** Validate preserved snapshot JSON using the exact Worker seed validator. */

import fs from 'node:fs/promises';
import process from 'node:process';
import { validateSeedSnapshot } from '../workers/market-context/src/index.js';

const paths = process.argv.slice(2);
if (paths.length < 2) {
  console.error(JSON.stringify({ ready_for_worker_seed: false, error: 'at least two snapshot paths are required' }));
  process.exit(2);
}

const results = [];
for (const path of paths) {
  const raw = await fs.readFile(path, 'utf8');
  const snapshot = JSON.parse(raw);
  const result = await validateSeedSnapshot(snapshot, raw);
  results.push({ path, asof: snapshot.asof, ...result });
}
const ready = results.every((result) => result.ok);
console.log(JSON.stringify({ ready_for_worker_seed: ready, snapshots: results }, null, 2));
process.exit(ready ? 0 : 2);
