/* Adaptive background quality. Content and controls always retain CSS resolution. */
(function (root) {
  'use strict';
  function create(options = {}) {
    const fps = options.mobile ? 30 : 60;
    const levels = [
      { cloud: 1, particleStride: 1, fps, scale: 1 },
      { cloud: .65, particleStride: 2, fps, scale: 1 },
      { cloud: .45, particleStride: 3, fps: 30, scale: 1 },
      { cloud: .45, particleStride: 3, fps: 30, scale: .8 }
    ];
    let level = 0, slow = 0, stable = 0, longFrames = 0;
    return {
      get level() { return level; },
      get settings() { return levels[level]; },
      reset() { slow = stable = longFrames = 0; },
      sample(elapsed) {
        // Startup, suspended tabs and isolated long tasks are not sustained GPU load.
        if (!Number.isFinite(elapsed) || elapsed <= 0) {
          slow = stable = longFrames = 0;
          return false;
        }
        // Ignore one-off pauses, but do not mistake sustained <4fps for a suspended tab.
        if (elapsed > 250) {
          if (++longFrames < 3) { slow = stable = 0; return false; }
          elapsed = 250;
        } else longFrames = 0;
        const budget = 1000 / levels[level].fps;
        if (elapsed > budget * 1.65) {
          slow += elapsed;
          stable = 0;
        } else {
          slow = Math.max(0, slow - elapsed);
          stable = elapsed <= budget * 1.15 ? stable + elapsed : 0;
        }
        const next = slow >= 2500 ? Math.min(3, level + 1)
          : stable >= 12000 ? Math.max(0, level - 1) : level;
        if (next === level) return false;
        level = next;
        slow = stable = 0;
        return true;
      }
    };
  }
  if (typeof module === 'object' && module.exports) module.exports = { create };
  else root.HomeQuality = { create };
})(typeof window === 'object' ? window : globalThis);
