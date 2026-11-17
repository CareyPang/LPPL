/* Decorative images only. No business requests, model state, or storage. */
(function () {
  'use strict';
  const media = Array.from(document.querySelectorAll('.visual-media'));
  media.forEach(frame => {
    const img = frame.querySelector('img');
    if (!img) return;
    const failed = () => frame.classList.add('art-unavailable');
    img.addEventListener('error', failed);
    img.addEventListener('load', () => { if (img.naturalWidth) frame.classList.remove('art-unavailable'); });
    if (img.complete && !img.naturalWidth) failed();
  });
  const hero = document.querySelector('.hero-art .visual-media');
  if (!hero) return;
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const fine = matchMedia('(hover: hover) and (pointer: fine)');
  let frameId = 0;
  const reset = () => {
    cancelAnimationFrame(frameId);
    frameId = 0;
    hero.style.setProperty('--art-x', '0px');
    hero.style.setProperty('--art-y', '0px');
  };
  hero.addEventListener('pointermove', event => {
    if (motion.matches || !fine.matches || document.hidden) return;
    const bounds = hero.getBoundingClientRect();
    const x = Math.max(-1, Math.min(1, (event.clientX - bounds.left) / bounds.width * 2 - 1));
    const y = Math.max(-1, Math.min(1, (event.clientY - bounds.top) / bounds.height * 2 - 1));
    cancelAnimationFrame(frameId);
    frameId = requestAnimationFrame(() => {
      hero.style.setProperty('--art-x', (x * 5).toFixed(2) + 'px');
      hero.style.setProperty('--art-y', (y * 3).toFixed(2) + 'px');
      frameId = 0;
    });
  }, { passive: true });
  hero.addEventListener('pointerleave', reset);
  motion.addEventListener('change', reset);
  fine.addEventListener('change', reset);
  document.addEventListener('visibilitychange', reset);
})();
