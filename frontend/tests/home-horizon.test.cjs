'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const horizon=require('../app/home-horizon.js');
const root=path.join(__dirname,'..');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');

test('waterline geometry is traceable to the retained media frames, not a changed video',()=>{
  const evidence=JSON.parse(fs.readFileSync(path.join(root,'assets/ocean/horizon-provenance.json')));
  assert.equal(Object.keys(evidence.source_frames_sha256).length,120);
  for(const [name,expected] of Object.entries(evidence.source_frames_sha256)){
    assert.equal(hash(fs.readFileSync(path.join(root,'assets/dive/h',name))),expected,name);
  }
  assert.equal(hash(fs.readFileSync(path.join(root,'app/home-horizon.js'))),evidence.geometry_sha256);
});

test('the near wave keeps its curved crest instead of being sliced by one mean horizon',()=>{
  const item={scene:'dive',progress:89/240};
  const left=horizon.at(item,.05),middle=horizon.at(item,.5),right=horizon.at(item,.95);
  assert.ok(left>.16&&left<.22);
  assert.ok(middle>.29&&middle<.35);
  assert.ok(right>.28&&right<.34);
  assert.ok(middle-left>.09,'Sky coverage ends at different heights across the near wave');
});

test('the last sky strip leaves through the frame edge continuously, and underwater rows are empty',()=>{
  let previous=1;
  for(let frame=109;frame<=121;frame+=.25){
    const largest=Math.max(...Array.from({length:32},(_,i)=>horizon.at({scene:'dive',progress:frame/240},i/31)));
    assert.ok(largest<=previous+.002);
    assert.ok(previous===1||Math.abs(largest-previous)<.012);
    previous=largest;
  }
  assert.equal(previous,0);
  for(const scene of ['under','deep'])for(const x of [0,.25,.5,.75,1])assert.equal(horizon.at({scene},x),0);
});

test('GPU packed geometry and Canvas geometry agree across rows and columns',()=>{
  const bytes=horizon.pixels();
  assert.equal(bytes.length,horizon.width*horizon.height*4);
  for(let row=0;row<128;row++)for(let x=0;x<32;x++){
    const item=row===127?{scene:'sea'}:row===126?{scene:'under'}:{scene:'dive',progress:row/240};
    const offset=(row*32+x)*4,value=(bytes[offset]*256+bytes[offset+1])/65535;
    assert.ok(Math.abs(horizon.at(item,x/31)-value)<1e-8);
  }
});
