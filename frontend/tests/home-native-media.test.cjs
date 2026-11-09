'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const HomeMedia = require('../app/home-media.js');
const flush = async () => { for (let n = 0; n < 5; n++) await Promise.resolve(); };

function setup(options = {}) {
  const videos = [], timers = new Map(), decoded = [], blocked = [], errors = [];
  let timerId = 0;
  class Video {
    constructor() {
      this.listeners = new Map(); this.style = {}; this.readyState = 0; this._time = 0;
      this.seeking = false; this.paused = true; this.videoWidth = 1920; this.videoHeight = 1080;
      this.assignments = []; this.plays = 0; this.callbacks = new Map(); this.nextCallback = 0;
      this.playMode = () => Promise.resolve();
    }
    setAttribute() {}
    removeAttribute(name) { delete this[name]; }
    addEventListener(name, callback) { this.listeners.set(name, [...(this.listeners.get(name) || []), callback]); }
    emit(name) { for (const callback of this.listeners.get(name) || []) callback(); }
    load() {}
    remove() { this.removed = true; }
    pause() { this.paused = true; }
    play() { this.plays++; return this.playMode().then(() => { this.paused = false; }); }
    get currentTime() { return this._time; }
    set currentTime(value) { this._time = value; this.assignments.push(value); this.seeking = true; }
    ready() { this.readyState = 1; this.emit('loadedmetadata'); this.readyState = 2; this.emit('loadeddata'); this.emit('canplay'); }
    finishSeek() { this.readyState = 2; this.seeking = false; this.emit('seeked'); }
    requestVideoFrameCallback(callback) { const id = ++this.nextCallback; this.callbacks.set(id, callback); return id; }
    cancelVideoFrameCallback(id) { this.callbacks.delete(id); }
    present(time) {
      this._time = time;
      const entry = this.callbacks.entries().next().value;
      if (entry) { this.callbacks.delete(entry[0]); entry[1](0, { mediaTime: time }); }
    }
  }
  const document = {
    hidden: false, body: { appendChild() {} },
    createElement(name) { assert.equal(name, 'video'); const video = new Video(); videos.push(video); return video; }
  };
  const media = HomeMedia.create({
    document,
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    onFrame(kind, item) { decoded.push({ kind, time: item.time, progress: item.progress, seeking: item.src.seeking, revision: item.revision }); },
    onBlocked(kind) { blocked.push(kind); }, onError(kind) { errors.push(kind); }, ...options
  });
  return { media, videos, decoded, blocked, errors, expire(delay) {
    for (const [id, entry] of [...timers]) if (entry.delay === delay) { timers.delete(id); entry.callback(); }
  } };
}

test('first paint loads only the chosen sea variant; underwater media remains lazy', async () => {
  const { media, videos } = setup({ mobile: true });
  media.setProgress(0); media.start();
  assert.equal(videos.length, 1);
  assert.equal(videos[0].src, 'assets/ocean/sea-mobile.mp4');
  videos[0].ready(); await flush();
  for (let n = 0; n < 20; n++) media.setProgress(0);
  assert.equal(videos.length, 1);
  assert.equal(media.status('dive'), 'idle');
  assert.equal(media.status('under'), 'idle');
  assert.equal(media.getLoop('sea').scene, 'sea');
});

test('the dive decoder warms only after the sea is ready, without starting the underwater loop', async () => {
  const { media, videos, expire } = setup();
  media.start(); expire(250);
  assert.equal(videos.length, 1);
  videos[0].ready(); await flush();
  expire(250);
  assert.equal(videos.length, 2);
  assert.equal(videos[1].src, 'assets/ocean/dive-desktop.mp4');
  videos[1].ready();
  assert.equal(media.getDive().progress, 0);
  assert.equal(videos[1].plays, 0);
  assert.equal(media.status('under'), 'idle');
});

test('a hidden or destroyed page cannot start a delayed decoder warmup', async () => {
  for (const action of ['hide', 'destroy']) {
    const { media, videos, expire } = setup();
    media.start(); videos[0].ready(); await flush();
    if (action === 'hide') media.setHidden(true); else media.destroy();
    expire(250);
    assert.equal(videos.length, 1);
  }
});

test('scroll seeks serialize work and coalesce all pending requests to the latest decoded target', async () => {
  const { media, videos, decoded } = setup();
  const first = media.seek(.1), video = videos[0];
  video.ready();
  const second = media.seek(.2), last = media.seek(.8);
  assert.deepEqual(video.assignments, [1]);
  assert.equal(media.getDive(), null);
  video.finishSeek();
  assert.deepEqual(video.assignments, [1, 8]);
  assert.equal(media.getDive(), null, 'A mutable video is not exposed while the next seek is in flight');
  assert.deepEqual(decoded.map(frame => [frame.progress, frame.seeking]), [[.1, false]], 'A stable frame is delivered before starting the next seek');
  video.finishSeek();
  const result = await Promise.all([first, second, last]);
  assert.ok(result.every(item => item.progress === .8));
  assert.equal(media.getDive().progress, .8);
  assert.deepEqual(decoded.map(frame => frame.progress), [.1, .8]);
  for (let n = 0; n < 20; n++) media.setProgress(.8);
  assert.deepEqual(video.assignments, [1, 8], 'An unchanged scroll frame must not seek again');
});

test('the first scroll seek waits for a decoded frame rather than interrupting metadata loading', async () => {
  const { media, videos } = setup(); const pending = media.seek(.5), video = videos[0];
  video.readyState = 1; video.emit('loadedmetadata');
  assert.deepEqual(video.assignments, []);
  video.readyState = 2; video.emit('loadeddata');
  assert.deepEqual(video.assignments, [5]);
  video.finishSeek(); assert.equal((await pending).progress, .5);
});

test('a presented-frame revision changes only when the decoded video frame changes', async () => {
  const { media, videos } = setup(); media.start(); videos[0].ready(); await flush();
  const revision = media.getLoop('sea').revision;
  videos[0].present(0);
  assert.equal(media.getLoop('sea').revision, revision);
  videos[0].present(1 / 24);
  assert.equal(media.getLoop('sea').revision, revision + 1);
});

test('deep aliases the same underwater decoder and preserves its playback position', async () => {
  const { media, videos } = setup(); media.setLoop('under');
  videos[0].ready(); await flush(); videos[0].present(2);
  media.setLoop('deep');
  assert.equal(videos.length, 1);
  assert.equal(videos[0].src, 'assets/ocean/under-desktop.mp4');
  assert.equal(media.getLoop('deep').scene, 'deep');
  assert.equal(media.getLoop('deep').time, 2);
  assert.deepEqual(videos[0].assignments, []);
});

test('autoplay rejection retains a decoded still and retries only on explicit resume', async () => {
  const { media, videos, blocked } = setup(); media.start();
  videos[0].playMode = () => Promise.reject(Object.assign(new Error('Blocked'), { name: 'NotAllowedError' }));
  videos[0].ready(); await flush();
  assert.equal(media.status('sea'), 'blocked');
  assert.ok(media.getLoop('sea'));
  for (let n = 0; n < 10; n++) media.setLoop('sea');
  assert.equal(videos[0].plays, 1);
  assert.deepEqual(blocked, ['sea']);
  videos[0].playMode = () => Promise.resolve(); media.resume(); await flush();
  assert.equal(media.status('sea'), 'ready');
  assert.equal(videos[0].paused, false);
});

test('resume reports no-op without an active loop, and re-entering a blocked scene renews its control once', async () => {
  const { media, videos, blocked } = setup(); media.start();
  videos[0].playMode = () => Promise.reject(Object.assign(new Error('Blocked'), { name: 'NotAllowedError' }));
  videos[0].ready(); await flush(); media.setLoop(null);
  assert.equal(media.resume(), false);
  media.setLoop('sea');
  for (let n = 0; n < 10; n++) media.setLoop('sea');
  assert.deepEqual(blocked, ['sea', 'sea']);
  assert.equal(videos[0].plays, 1);
  videos[0].playMode = () => Promise.resolve();
  assert.equal(media.resume(), true); await flush();
  assert.equal(media.status('sea'), 'ready');
});

test('a play promise resolving after the page hides must pause again', async () => {
  const { media, videos } = setup(); media.start();
  let resolvePlay;
  videos[0].playMode = () => new Promise(resolve => { resolvePlay = resolve; });
  videos[0].ready(); media.setHidden(true);
  resolvePlay(); await flush();
  assert.equal(videos[0].paused, true);
});

test('a late play promise cannot overwrite a terminal media failure', async () => {
  const { media, videos } = setup(); media.start();
  let resolvePlay;
  videos[0].playMode = () => new Promise(resolve => { resolvePlay = resolve; });
  videos[0].ready(); videos[0].emit('error');
  resolvePlay(); await flush();
  assert.equal(media.status('sea'), 'failed');
  assert.equal(videos[0].paused, true);
});

test('seek timeout marks failure and completes all coalesced promises', async () => {
  const { media, videos, errors, expire } = setup();
  const a = media.seek(.3); videos[0].ready(); const b = media.seek(.6);
  expire(5000);
  assert.deepEqual(await Promise.all([a, b]), [null, null]);
  assert.equal(media.status('dive'), 'failed');
  assert.deepEqual(errors, ['dive']);
  assert.equal(await media.seek(.7), null, 'Requests after terminal failure must also settle');
});

test('hidden time does not consume load or seek deadlines; visible stalled work still times out', async () => {
  const loading = setup(); loading.media.start(); loading.media.setHidden(true);
  loading.expire(15000);
  assert.equal(loading.media.status('sea'), 'loading');
  loading.media.setHidden(false); loading.expire(15000);
  assert.equal(loading.media.status('sea'), 'failed');

  const seeking = setup(); const pending = seeking.media.seek(.5); seeking.videos[0].ready();
  seeking.media.setHidden(true); seeking.expire(5000); seeking.expire(15000);
  assert.notEqual(seeking.media.status('dive'), 'failed');
  seeking.media.setHidden(false); seeking.expire(5000);
  assert.equal(await pending, null);
  assert.equal(seeking.media.status('dive'), 'failed');
});

test('destroy completes pending seek work and reduced motion never creates video elements', async () => {
  const live = setup(); const pending = live.media.seek(.5); live.media.destroy();
  assert.equal(await pending, null); assert.ok(live.videos[0].removed);
  const reduced = setup({ reducedMotion: true });
  reduced.media.start(); reduced.media.setProgress(.5); reduced.media.setLoop('under');
  assert.equal(await reduced.media.seek(.8), null);
  assert.equal(reduced.videos.length, 0);
  assert.equal(reduced.media.status('sea'), 'disabled');
});

test('shipped video hashes match and MP4 metadata precedes video payload for progressive playback', () => {
  const directory = path.join(__dirname, '..', 'assets', 'ocean');
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json'), 'utf8').replace(/^\uFEFF/, ''));
  assert.equal(manifest.files.length, 6);
  for (const entry of manifest.files) {
    const buffer = fs.readFileSync(path.join(directory, entry.file));
    assert.equal(buffer.length, entry.bytes);
    assert.equal(crypto.createHash('sha256').update(buffer).digest('hex'), entry.sha256);
    const boxes = [];
    for (let offset = 0; offset + 8 <= buffer.length;) {
      const size = buffer.readUInt32BE(offset), type = buffer.toString('ascii', offset + 4, offset + 8);
      assert.ok(size >= 8, 'Each encoded top-level box has a finite size');
      boxes.push(type); offset += size;
    }
    assert.ok(boxes.indexOf('moov') >= 0 && boxes.indexOf('moov') < boxes.indexOf('mdat'), entry.file);
    assert.equal(entry.fps, 24); assert.equal(entry.audio, false);
    if (entry.file.startsWith('dive-')) { assert.equal(entry.frames, 241); assert.equal(entry.gop, 12); }
  }
});
