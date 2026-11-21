/*
 * Chromecast-Web custom Cast Web Receiver (CAF v3, plain ES2017, no build step).
 *
 * Playback is CAF's own (PlayerManager + the <video class="castMediaElement">); this file
 * only (1) tunes the playback config for flaky live HLS, (2) keeps the LOAD semantics the
 * backend relies on (hlsSegmentFormat / hlsVideoSegmentFormat, tracks, live edge) and
 * (3) draws a TV UI from PlayerManager events. It never reloads media itself: after a
 * playback error the backend re-LOADs live streams; we only show "reconnecting" meanwhile.
 * See docs/CUSTOM_RECEIVER.md.
 */
'use strict';

(function () {
  // ---------------------------------------------------------------- tunables
  // Documented in docs/CUSTOM_RECEIVER.md ("Playback settings").
  var AUTO_RESUME_SECONDS = 8;        // buffered seconds needed to (re)start after a stall
  var SEGMENT_RETRY_LIMIT = 6;        // retries of a failed segment request (CAF default 3)
  var MANIFEST_TIMEOUT_MS = 10000;    // per playlist/manifest request
  var SEGMENT_TIMEOUT_MS = 15000;     // per media segment request
  var OVERLAY_MS = 5000;              // overlay auto-hide while playing
  var SLOW_LOADING_MS = 5000;         // "slow connection" after this much buffering
  var ERROR_GIVE_UP_MS = 60000;       // error screen -> idle screen if no new LOAD arrives

  // ---------------------------------------------------------------- strings (en / it)
  var IT = /^it\b/i.test(navigator.language || '');
  var T = IT ? {
    loading: 'Caricamento…',
    slow: 'Connessione lenta, sto ancora caricando…',
    error: 'Stream interrotto, riconnessione…',
    live: 'LIVE',
    ready: 'Pronto per trasmettere',
    hint: 'Apri Chromecast Web da un browser qualsiasi per iniziare a trasmettere',
    status: 'Chromecast Web'
  } : {
    loading: 'Loading…',
    slow: 'Slow connection, still loading…',
    error: 'Stream interrupted, reconnecting…',
    live: 'LIVE',
    ready: 'Ready to cast',
    hint: 'Open Chromecast Web from any browser to start casting',
    status: 'Chromecast Web'
  };
  document.documentElement.lang = IT ? 'it' : 'en';

  // ---------------------------------------------------------------- dom helpers
  var body = document.body;
  function $(id) { return document.getElementById(id); }
  var el = {
    still: $('still'), clock: $('clock'),
    stageTitle: $('stage-title'), stageStatus: $('stage-status'), hint: $('hint'),
    art: $('art'), liveText: $('live-text'), title: $('title'),
    barFill: $('bar-fill'), pos: $('pos'), dur: $('dur')
  };
  var APP_NAME = 'Chromecast Web';
  var mediaTitle = '';
  el.stageTitle.textContent = APP_NAME;
  el.stageStatus.textContent = T.ready;
  el.hint.textContent = T.hint;
  el.liveText.textContent = T.live;

  function log(event, details) {
    // one line per event, key=value details (visible in chrome://inspect)
    var parts = ['receiver', event];
    Object.keys(details || {}).forEach(function (k) { parts.push(k + '=' + details[k]); });
    console.info(parts.join(' '));
  }

  function fmt(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    sec = Math.floor(sec);
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var mm = h ? String(m).padStart(2, '0') : String(m);
    return (h ? h + ':' : '') + mm + ':' + String(s).padStart(2, '0');
  }

  // ---------------------------------------------------------------- state
  var state = 'idle';     // idle | loading | playing | paused | error | image
  var isLive = false;
  var isImage = false;
  var slowTimer = null, overlayTimer = null, tickTimer = null, errorTimer = null;

  function clear(t) { if (t) clearTimeout(t); return null; }

  function setState(next, why) {
    if (next === state) return;
    log('state', { from: state, to: next, why: why || '-' });
    state = next;
    body.dataset.state = next;
    slowTimer = clear(slowTimer);
    errorTimer = clear(errorTimer);
    body.classList.remove('slow');
    // the branded stage: app name + "ready" when idle, the media title + its status otherwise
    el.stageTitle.textContent = next === 'idle' ? APP_NAME : (mediaTitle || APP_NAME);
    el.stageStatus.textContent = next === 'error' ? T.error : next === 'loading' ? T.loading : T.ready;
    if (next === 'loading') {
      slowTimer = setTimeout(function () {
        body.classList.add('slow');
        el.stageStatus.textContent = T.slow;
        log('slow_loading', { after_ms: SLOW_LOADING_MS });
      }, SLOW_LOADING_MS);
    } else if (next === 'error') {
      errorTimer = setTimeout(function () { setState('idle', 'no_reload'); }, ERROR_GIVE_UP_MS);
    }
    if (next === 'playing' || next === 'paused') showOverlay();
    else hideOverlay();
    if (next === 'idle' || next === 'image') tickClock();
  }

  // ---------------------------------------------------------------- overlay
  function showOverlay() {
    body.classList.add('overlay');
    overlayTimer = clear(overlayTimer);
    updateProgress();
    if (!tickTimer) tickTimer = setInterval(updateProgress, 1000);
    if (state === 'playing') {
      overlayTimer = setTimeout(hideOverlay, OVERLAY_MS);
    }
  }

  function hideOverlay() {
    overlayTimer = clear(overlayTimer);
    if (state === 'paused') return;  // stays up while paused
    body.classList.remove('overlay');
    if (tickTimer) { clearInterval(tickTimer); tickTimer = null; }
  }

  function updateProgress() {
    if (isLive) return;
    var pos = pm.getCurrentTimeSec() || 0;
    var dur = pm.getDurationSec();
    if (!isFinite(dur) || dur <= 0) {
      el.barFill.style.transform = 'scaleX(0)';
      el.pos.textContent = fmt(pos);
      el.dur.textContent = '';
      return;
    }
    el.barFill.style.transform = 'scaleX(' + Math.min(1, pos / dur).toFixed(4) + ')';
    el.pos.textContent = fmt(pos);
    el.dur.textContent = fmt(dur);
  }

  function setMeta(media) {
    var md = (media && media.metadata) || {};
    var images = md.images || [];
    var title = md.title || '';
    el.title.textContent = title;
    mediaTitle = title;
    if (state === 'loading' || state === 'error') el.stageTitle.textContent = title || APP_NAME;
    if (images.length && images[0].url) el.art.setAttribute('src', images[0].url);
    else el.art.removeAttribute('src');
    isLive = !!media && media.streamType === cast.framework.messages.StreamType.LIVE;
    body.classList.toggle('is-live', isLive);
  }

  // ---------------------------------------------------------------- clock (idle)
  function tickClock() {
    var d = new Date();
    el.clock.textContent = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  }
  setInterval(function () { if (state === 'idle' || state === 'image') tickClock(); }, 10000);
  tickClock();

  // ---------------------------------------------------------------- CAF setup
  var ctx = cast.framework.CastReceiverContext.getInstance();
  var pm = ctx.getPlayerManager();
  var E = cast.framework.events.EventType;

  var playback = new cast.framework.PlaybackConfig();
  playback.autoResumeDuration = AUTO_RESUME_SECONDS;
  playback.segmentRequestRetryLimit = SEGMENT_RETRY_LIMIT;
  playback.manifestRequestHandler = function (req) { req.timeoutInterval = MANIFEST_TIMEOUT_MS; };
  playback.segmentRequestHandler = function (req) { req.timeoutInterval = SEGMENT_TIMEOUT_MS; };

  // LOAD: keep the Default Media Receiver semantics the backend builds (build_play_kwargs).
  // hlsSegmentFormat / hlsVideoSegmentFormat / tracks / textTrackStyle are MediaInformation
  // fields CAF reads natively; also accept them from customData. No currentTime on a LIVE
  // LOAD = CAF starts at the live edge, so currentTime is left untouched.
  pm.setMessageInterceptor(cast.framework.messages.MessageType.LOAD, function (request) {
    var media = request.media || {};
    var cd = Object.assign({}, media.customData || {}, request.customData || {});
    if (!media.hlsSegmentFormat && cd.hlsSegmentFormat) media.hlsSegmentFormat = cd.hlsSegmentFormat;
    if (!media.hlsVideoSegmentFormat && cd.hlsVideoSegmentFormat) media.hlsVideoSegmentFormat = cd.hlsVideoSegmentFormat;
    isImage = /^image\//i.test(media.contentType || '');
    log('load', {
      contentType: media.contentType,
      streamType: media.streamType,
      hlsSegmentFormat: media.hlsSegmentFormat || '-',
      hlsVideoSegmentFormat: media.hlsVideoSegmentFormat || '-',
      tracks: (media.tracks || []).length,
      currentTime: request.currentTime == null ? '-' : request.currentTime
    });
    setMeta(media);
    if (isImage) {
      el.still.src = media.contentId || media.contentUrl || '';
      setState('image', 'load_image');
    } else {
      el.still.removeAttribute('src');
      setState('loading', 'load');
    }
    return request;
  });

  pm.addEventListener(E.BUFFERING, function (e) {
    if (isImage || state === 'error') return;
    if (e.isBuffering) setState('loading', 'buffering');
    else if (state === 'loading') setState(pm.getPlayerState() === 'PAUSED' ? 'paused' : 'playing', 'buffered');
  });

  pm.addEventListener(E.PLAYING, function () {
    if (isImage) return;
    setState('playing', 'playing');
    showOverlay();
  });

  pm.addEventListener(E.PAUSE, function () {
    if (isImage || state === 'error' || state === 'idle') return;
    setState('paused', 'pause');
  });

  pm.addEventListener([E.SEEKING, E.SEEKED], function () {
    if (state === 'playing' || state === 'paused') showOverlay();
  });

  pm.addEventListener(E.ERROR, function (e) {
    log('error', { detailedErrorCode: e.detailedErrorCode, reason: e.reason || '-' });
    if (isImage) return;
    setState('error', 'error');
  });

  pm.addEventListener(E.MEDIA_FINISHED, function (e) {
    log('finished', { endedReason: e.endedReason });
    if (e.endedReason === 'ERROR') { setState('error', 'finished_error'); return; }
    if (isImage && e.endedReason !== 'STOPPED') return;  // keep showing the idle image
    if (e.endedReason === 'END_OF_STREAM' || e.endedReason === 'STOPPED') {
      isImage = false;
      el.still.removeAttribute('src');
      setState('idle', 'finished');
    }
  });

  pm.addEventListener(E.MEDIA_STATUS, function (e) {
    var ms = e.mediaStatus;
    if (!ms) return;
    // a non-fatal ERROR event: playback went on, leave the error screen
    if (state === 'error' && ms.playerState === 'PLAYING' && !isImage) { setState('playing', 'status_playing'); return; }
    if (ms.playerState !== 'IDLE') return;
    // INTERRUPTED = replaced by a new LOAD (the interceptor already switched the screen)
    if (ms.idleReason === 'ERROR') setState('error', 'status_error');
    else if ((ms.idleReason === 'FINISHED' || ms.idleReason === 'CANCELLED') && !isImage) setState('idle', 'status_idle');
  });

  ctx.start({
    playbackConfig: playback,
    statusText: T.status
  });
  log('start', {
    lang: navigator.language,
    autoResumeDuration: AUTO_RESUME_SECONDS,
    segmentRequestRetryLimit: SEGMENT_RETRY_LIMIT,
    manifestTimeoutMs: MANIFEST_TIMEOUT_MS,
    segmentTimeoutMs: SEGMENT_TIMEOUT_MS
  });
})();
