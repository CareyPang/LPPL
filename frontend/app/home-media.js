/* Native ocean playback. Scroll seeks are serialized; only the latest target is decoded next. */
(function (root) {
  'use strict';
  const CLIPS = { sea: { frames: 193 }, dive: { frames: 241 }, under: { frames: 169 } };
  const FPS = 24;
  const clamp = value => Math.min(1, Math.max(0, Number(value) || 0));
  const sourceName = name => name === 'deep' ? 'under' : name;

  function create(options = {}) {
    const doc = options.document || root.document;
    const reduced = !!options.reducedMotion;
    const variant = options.mobile ? 'mobile' : 'desktop';
    const base = options.basePath || 'assets/ocean/';
    const records = new Map();
    const waiters = [];
    let hidden = !!doc.hidden, destroyed = false, started = false, active = null;
    let requestedProgress = 0, requestedFrame = 0;
    const timer = options.setTimeout || root.setTimeout.bind(root);
    const untimer = options.clearTimeout || root.clearTimeout.bind(root);

    function item(record, scene = record.kind) {
      if (!record.ready || record.failed || record.video.seeking || record.video.readyState < 2) return null;
      return {
        key: 'ocean-' + record.kind, src: record.video,
        w: record.video.videoWidth, h: record.video.videoHeight,
        live: true, revision: record.revision, scene, time: record.frameTime,
        progress: record.kind === 'dive' ? clamp(record.frameTime / ((CLIPS.dive.frames - 1) / FPS)) : undefined
      };
    }
    function settle(value) { for (const resolve of waiters.splice(0)) resolve(value); }
    function armLoadTimeout(record) {
      untimer(record.loadTimer);
      if (destroyed || hidden || record.failed || record.ready) return;
      record.loadTimer = timer(() => {
        if (!hidden) fail(record, new Error('Ocean media timed out'));
      }, options.loadTimeout || 15000);
    }
    function armSeekTimeout(record) {
      untimer(record.seekTimer);
      if (destroyed || hidden || record.failed || !record.inFlight) return;
      record.seekTimer = timer(() => {
        if (!hidden) fail(record, new Error('Ocean seek timed out'));
      }, options.seekTimeout || 5000);
    }
    function fail(record, error) {
      if (record.failed || destroyed) return;
      record.failed = true; record.status = 'failed'; record.inFlight = false;
      untimer(record.loadTimer); untimer(record.seekTimer);
      record.video.pause();
      if (record.callback !== null && record.video.cancelVideoFrameCallback) record.video.cancelVideoFrameCallback(record.callback);
      record.callback = null;
      if (record.kind === 'dive') settle(null);
      if (options.onError) options.onError(record.kind, error);
    }
    function capture(record, mediaTime) {
      const video = record.video;
      if (destroyed || record.failed || video.readyState < 2 || video.seeking) return;
      const time = Number.isFinite(mediaTime) ? mediaTime : Math.round(video.currentTime * FPS) / FPS;
      const changed = !record.ready || Math.abs(time - record.frameTime) > .001;
      if (changed) {
        record.frameTime = time; record.revision++;
      }
      record.ready = true;
      if (!record.blocked) record.status = 'ready';
      untimer(record.loadTimer);
      // Consumers may snapshot this decoded frame before the next coalesced seek mutates the video.
      if (changed && options.onFrame) options.onFrame(record.kind, item(record));
      if (!record.notified) {
        record.notified = true;
        if (options.onReady) options.onReady(record.kind, item(record));
      }
    }
    function watchFrames(record) {
      const video = record.video;
      if (destroyed || hidden || record.failed || record.callback !== null || !video.requestVideoFrameCallback) return;
      record.callback = video.requestVideoFrameCallback((now, metadata) => {
        record.callback = null; capture(record, metadata.mediaTime); watchFrames(record);
      });
    }
    function play(record, gesture = false) {
      if (destroyed || hidden || record.failed || !record.ready || sourceName(active) !== record.kind || record.playPending) return;
      if (record.blocked && !gesture) return;
      if (!record.video.paused) return;
      record.playPending = true;
      let promise;
      try { promise = record.video.play(); }
      catch (error) { promise = Promise.reject(error); }
      Promise.resolve(promise).then(() => {
        record.playPending = false;
        // A play promise can settle after the tab was hidden or the active scene changed.
        if (destroyed || hidden || record.failed || sourceName(active) !== record.kind) record.video.pause();
        else { record.blocked = false; record.status = 'ready'; }
      }, error => {
        record.playPending = false;
        if (destroyed || hidden || record.failed || sourceName(active) !== record.kind) { record.video.pause(); return; }
        if (error && error.name === 'NotSupportedError') { fail(record, error); return; }
        record.blocked = true; record.status = 'blocked';
        if (options.onBlocked) options.onBlocked(record.kind, error);
      });
    }
    function seekLatest(record) {
      const video = record.video;
      // Wait for the first decoded image before seeking. Seeking at metadata-only readiness
      // can interrupt first-frame loading on some media pipelines.
      if (destroyed || hidden || record.failed || record.inFlight || video.readyState < 2) return;
      const time = requestedFrame / FPS;
      if (!video.seeking && Math.abs(video.currentTime - time) < 1 / (FPS * 2)) {
        if (video.readyState >= 2) { capture(record); settle(item(record)); }
        return;
      }
      record.inFlight = true;
      record.targetFrame = requestedFrame;
      armSeekTimeout(record);
      try { video.currentTime = time; }
      catch (error) { fail(record, error); }
    }
    function ensure(name) {
      const kind = sourceName(name);
      if (destroyed || reduced || !CLIPS[kind]) return null;
      if (records.has(kind)) return records.get(kind);
      const video = doc.createElement('video');
      video.muted = true; video.defaultMuted = true; video.playsInline = true;
      video.loop = kind !== 'dive'; video.preload = 'auto'; video.tabIndex = -1;
      video.setAttribute('playsinline', ''); video.setAttribute('aria-hidden', 'true');
      video.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;pointer-events:none;';
      const record = {
        kind, video, ready: false, failed: false, blocked: false, status: 'loading',
        revision: 0, frameTime: 0, callback: null, inFlight: false, playPending: false
      };
      records.set(kind, record);
      video.addEventListener('loadedmetadata', () => { if (kind === 'dive') seekLatest(record); });
      video.addEventListener('loadeddata', () => {
        if (kind === 'dive') {
          seekLatest(record);
          if (!record.inFlight) capture(record);
        } else { capture(record); play(record); }
        watchFrames(record);
      });
      video.addEventListener('canplay', () => { capture(record); if (kind !== 'dive') play(record); });
      video.addEventListener('seeked', () => {
        untimer(record.seekTimer); record.inFlight = false; capture(record);
        if (kind === 'dive') seekLatest(record);
      });
      video.addEventListener('timeupdate', () => { if (!video.requestVideoFrameCallback) capture(record); });
      video.addEventListener('error', () => fail(record, video.error || new Error('Ocean media unavailable')));
      if (doc.body) doc.body.appendChild(video);
      armLoadTimeout(record);
      video.src = base + kind + '-' + variant + '.mp4';
      video.load();
      return record;
    }

    const api = {
      start() {
        if (destroyed || reduced) return;
        started = true;
        if (!hidden) api.setLoop('sea');
      },
      setProgress(progress) {
        requestedProgress = clamp(progress);
        const frame = Math.round(requestedProgress * (CLIPS.dive.frames - 1));
        const changed = frame !== requestedFrame;
        requestedFrame = frame;
        if (destroyed || reduced || hidden) return;
        if (!changed && records.has('dive')) return;
        // Opening at the sea surface does not compete with the first sea playback.
        if (!records.has('dive') && !changed && frame === 0) return;
        const record = ensure('dive');
        if (record && !record.failed) seekLatest(record);
      },
      seek(progress) {
        if (destroyed || reduced) return Promise.resolve(null);
        const promise = new Promise(resolve => waiters.push(resolve));
        requestedProgress = clamp(progress); requestedFrame = Math.round(requestedProgress * (CLIPS.dive.frames - 1));
        if (!hidden) {
          const record = ensure('dive');
          if (record.failed) settle(null); else seekLatest(record);
        }
        return promise;
      },
      setLoop(name) {
        if (destroyed || reduced) return;
        const previous = active;
        active = name === 'sea' || name === 'under' || name === 'deep' ? name : null;
        for (const record of records.values()) if (record.kind !== sourceName(active)) record.video.pause();
        if (active && !hidden) {
          const record = ensure(active);
          if (record.blocked && previous !== active && options.onBlocked) options.onBlocked(record.kind);
          play(record);
        }
      },
      getDive() { const record = records.get('dive'); return record ? item(record) : null; },
      getLoop(name) { const record = records.get(sourceName(name)); return record ? item(record, name) : null; },
      status(name) { return reduced ? 'disabled' : records.get(sourceName(name))?.status || 'idle'; },
      setHidden(value) {
        hidden = !!value;
        for (const record of records.values()) {
          if (hidden) {
            record.video.pause();
            untimer(record.loadTimer); untimer(record.seekTimer);
            if (record.callback !== null && record.video.cancelVideoFrameCallback) record.video.cancelVideoFrameCallback(record.callback);
            record.callback = null;
          } else {
            armLoadTimeout(record); armSeekTimeout(record); watchFrames(record);
          }
        }
        if (!hidden && !destroyed && !reduced) {
          if (!active && started && !records.size) active = 'sea';
          if (active) api.setLoop(active);
          if (records.has('dive') || requestedProgress > 0 || waiters.length) {
            const record = ensure('dive');
            if (record.failed) settle(null); else seekLatest(record);
          }
        }
      },
      resume() {
        if (destroyed || reduced || hidden || !active) return false;
        const record = ensure(active);
        if (record.failed || !record.ready || record.playPending) return false;
        record.blocked = false; play(record, true);
        return record.playPending || !record.video.paused;
      },
      destroy() {
        destroyed = true;
        for (const record of records.values()) {
          untimer(record.loadTimer); untimer(record.seekTimer);
          if (record.callback !== null && record.video.cancelVideoFrameCallback) record.video.cancelVideoFrameCallback(record.callback);
          record.video.pause(); record.video.removeAttribute('src'); record.video.load(); record.video.remove();
        }
        settle(null);
      }
    };
    return api;
  }
  if (typeof module === 'object' && module.exports) module.exports = { create };
  else root.HomeMedia = { create };
})(typeof window === 'object' ? window : globalThis);
