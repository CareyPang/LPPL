// Technical encoding only: retain full 3:2 composition; no generative edits.
// npm install --prefix <external build environment> sharp
// SHARP_MODULE_PATH=<environment>/node_modules/sharp node frontend/scripts/prepare-visual-assets.cjs
const fs = require('node:fs');
const path = require('node:path');
const sharp = require(process.env.SHARP_MODULE_PATH || 'sharp');
const base = path.resolve(__dirname, '../assets/visual-suite');
(async () => {
  const results = [];
  for (const id of ['fx','clock','units','metals','scenario','mortgage','hero']) {
    for (const width of (id === 'hero' ? [640,1536] : [480,960])) {
      const file = `${id}-${width}.webp`;
      await sharp(path.join(base,'masters',`${id}.png`)).resize({width,withoutEnlargement:true}).webp({quality:84,effort:6}).toFile(path.join(base,file));
      results.push({file,bytes:fs.statSync(path.join(base,file)).size,width});
    }
  }
  console.log(JSON.stringify({sharp:sharp.versions.sharp,files:results,total_bytes:results.reduce((n,a)=>n+a.bytes,0)},null,2));
})().catch(error => {console.error(error); process.exitCode=1;});
