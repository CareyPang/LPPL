'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/scen-style.js'), 'utf8');
const context = vm.createContext({ window: {} });
vm.runInContext(source, context);

function draw(secondary) {
  const strokes = [];
  let dash = [];
  const ctx = {
    beginPath() {},
    moveTo() {},
    lineTo() {},
    stroke() { strokes.push({ color: this.strokeStyle, width: this.lineWidth, dash: [...dash] }); },
    fillRect() {},
    setLineDash(value) { dash = value; },
  };
  context.window.CPSCN.drawRange(ctx, {
    x0: 0, xa: 10, xb: 20, y: 12, secondary,
  });
  return strokes[strokes.length - 1];
}

test('secondary scenario ranges use a lighter dashed style', () => {
  const main = draw(false);
  const secondary = draw(true);

  assert.match(main.color, /rgba\(154,91,0,0\.6\)/);
  assert.match(secondary.color, /rgba\(154,91,0,0\.28\)/);
  assert.deepEqual(secondary.dash, [4, 3]);
  assert.ok(secondary.width < main.width);
});
