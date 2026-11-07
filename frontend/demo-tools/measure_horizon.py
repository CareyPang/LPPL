"""Measure a connected waterline from retained dive frames; never alter the footage.

Outputs numeric render geometry only. The source sun/glare columns are bridged;
they must not be mistaken for holes through which the old sky can show.
Run from the existing analysis environment with Pillow, NumPy and SciPy.
"""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, gaussian_filter1d

FRONTEND = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 32, 128


def main():
    html = (FRONTEND / "home.html").read_text(encoding="utf-8")
    reference = json.loads(re.search(r"const HZ_TAB=(\[.*?\]);", html)[1])
    rows, hashes = [], {}
    for index in range(120):
        path = FRONTEND / "assets/dive/h" / f"{index + 1:03}.webp"
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        pixels = np.asarray(Image.open(path).resize((480, 270)), dtype=float)
        # Warm, connected sky above cool water, measured offline, not per-pixel runtime holes.
        signal = gaussian_filter(.65*pixels[:, :, 0] + .35*pixels[:, :, 1]
                                 - .45*pixels[:, :, 2], (1.5, 4))
        water = signal < 65
        contour = np.argmax(water, axis=0).astype(float)
        contour[~water.any(axis=0)] = 270
        x = np.arange(480)
        reliable = (x < 288) | (x > 456)
        contour = np.interp(x, x[reliable], contour[reliable])
        contour = gaussian_filter1d(contour, 6) / 270
        # The far horizon is flat before the near wave enters the skyline.
        blend = np.clip((index - 35) / 30, 0, 1)
        plane = reference[index] / 1000 if index < len(reference) else 0
        contour = plane*(1-blend) + contour*blend
        rows.append(np.interp(np.linspace(0, 479, WIDTH), x, contour))
    rows = gaussian_filter1d(np.asarray(rows), .6, axis=0, mode="nearest")
    rows = np.clip(rows, 0, 1)
    # Fully submerged rows and a separate sea-loop row are explicit.
    data = np.zeros((HEIGHT, WIDTH))
    data[:120] = rows
    data[-1] = .4296
    values = np.rint(data * 65535).astype(int).tolist()
    source = """/* Generated numeric waterline geometry; see demo-tools/measure_horizon.py. */
(function(root){
  'use strict';
  const width=32,height=128;
  const rows=DATA;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  function index(item){
    if(item.scene==='sea') return 127;
    if(item.scene==='under'||item.scene==='deep') return 126;
    return clamp((item.progress||0)*240,0,125);
  }
  function at(item,x){
    const row=index(item),a=Math.floor(row),b=Math.min(127,a+1),t=row-a;
    const col=clamp(x,0,1)*31,c=Math.floor(col),d=Math.min(31,c+1),u=col-c;
    return ((rows[a][c]*(1-u)+rows[a][d]*u)*(1-t)+(rows[b][c]*(1-u)+rows[b][d]*u)*t)/65535;
  }
  function pixels(){
    const bytes=new Uint8Array(width*height*4);
    rows.forEach((row,y)=>row.forEach((v,x)=>{const i=(y*width+x)*4;bytes[i]=v>>8;bytes[i+1]=v&255;bytes[i+3]=255;}));
    return bytes;
  }
  const api={width,height,index,at,pixels};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.HomeHorizon=api;
})(typeof window==='object'?window:globalThis);
""".replace("DATA", json.dumps(values, separators=(",", ":")))
    (FRONTEND / "app/home-horizon.js").write_text(source, encoding="utf-8", newline="\n")
    (FRONTEND / "assets/ocean/horizon-provenance.json").write_text(json.dumps({
        "purpose": "connected waterline geometry; no media pixels changed",
        "width": WIDTH, "height": HEIGHT, "source_frames_sha256": hashes,
        "geometry_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "limits": "Derived for this retained footage only; remeasure if the clip changes."
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Measured {len(hashes)} source frames into {WIDTH}x{HEIGHT} geometry")


if __name__ == "__main__":
    main()
