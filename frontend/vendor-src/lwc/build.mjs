import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const packageRoot = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(packageRoot, '../..');
const outputRoot = join(frontendRoot, 'vendor/lppl-lwc/1');
const bundlePath = join(outputRoot, 'lppl-lwc.js');
const packageFile = readFileSync(join(packageRoot, 'package.json'), 'utf8');
const packageJson = JSON.parse(packageFile);
const lock = JSON.parse(readFileSync(join(packageRoot, 'package-lock.json'), 'utf8'));

mkdirSync(outputRoot, { recursive: true });
await build({
  entryPoints: [join(packageRoot, 'entry.mjs')],
  outfile: bundlePath,
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['es2020'],
  minify: true,
  legalComments: 'none',
});

function resolveLockedDependency(fromPath, name) {
  const parts = fromPath.split('/');
  for (let length = parts.length; length >= 0; length -= 1) {
    const candidate = [...parts.slice(0, length), 'node_modules', ...name.split('/')].join('/');
    if (lock.packages[candidate]) return candidate;
  }
  throw new Error(`Missing locked runtime dependency ${name} from ${fromPath}`);
}

const runtimePackages = new Set();
function includeRuntimePackage(packagePath) {
  if (runtimePackages.has(packagePath)) return;
  runtimePackages.add(packagePath);
  const item = lock.packages[packagePath];
  if (!item) throw new Error(`Missing locked runtime package ${packagePath}`);
  for (const name of Object.keys(item.dependencies || {})) {
    includeRuntimePackage(resolveLockedDependency(packagePath, name));
  }
}
for (const name of Object.keys(packageJson.dependencies)) {
  includeRuntimePackage(`node_modules/${name}`);
}

const licenseSections = [];
const noticeSections = [
  'This distribution includes Lightweight Charts 5.2.1, copyright TradingView, Inc., and official TradingView Lightweight Charts plugins. The chart attribution logo is enabled.',
];
for (const packagePath of [...runtimePackages].sort()) {
  const packageDir = join(packageRoot, packagePath);
  const metadata = JSON.parse(readFileSync(join(packageDir, 'package.json'), 'utf8'));
  const files = new Set(readdirSync(packageDir));
  const licenseName = ['LICENSE', 'LICENSE.md', 'LICENSE.txt'].find(file => files.has(file));
  const label = `${metadata.name}@${metadata.version}`;
  if (licenseName) {
    licenseSections.push(`${label}\n\n${readFileSync(join(packageDir, licenseName), 'utf8').trim()}`);
  } else {
    licenseSections.push(`${label}\n\nLicense declared: ${metadata.license || 'unspecified'}; no license text was included in the package archive.`);
  }
  const noticeName = ['NOTICE', 'NOTICE.md', 'NOTICE.txt'].find(file => files.has(file));
  if (noticeName) {
    noticeSections.push(`${label}\n\n${readFileSync(join(packageDir, noticeName), 'utf8').trim()}`);
  }
}
writeFileSync(join(outputRoot, 'LICENSE'), `${licenseSections.join('\n\n---\n\n')}\n`);
writeFileSync(join(outputRoot, 'NOTICE'), `${noticeSections.join('\n\n---\n\n')}\n`);

const lockedPackages = Object.entries(lock.packages)
  .filter(([path, item]) => path && item.version)
  .map(([path, item]) => ({
    path,
    version: item.version,
    integrity: item.integrity || null,
  }));
const bundle = readFileSync(bundlePath);
const manifest = {
  buildCommand: 'npm --prefix frontend/vendor-src/lwc run build',
  packages: lockedPackages,
  bundle: {
    path: 'frontend/vendor/lppl-lwc/1/lppl-lwc.js',
    sha256: createHash('sha256').update(bundle).digest('hex'),
  },
};
writeFileSync(join(outputRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
