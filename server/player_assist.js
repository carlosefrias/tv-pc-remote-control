// Runs inside the channel's web page (via Firefox Marionette) about once a second.
// Goal: the TV shows only the video player, full screen, playing, with sound.
// arguments[0] = {elapsed: seconds since the channel page was requested, clicks: clicks done so far,
//                 inFrame: true when running inside the player's iframe (see fullscreen.py)}
// Returns a status object; if it contains `click: [x, y]` the server performs a
// real mouse click there (used for "click to play" players). If the page has no
// <video> but has a player iframe, `frame` is that iframe element: the server then
// runs this same script inside it (Marionette can enter cross-origin frames).

var opts = arguments[0] || {};
var PLAYER_HOSTS = /dailymotion|youtube|youtu\.be|vimeo|jwplayer|jwplatform|brightcove|twitch|player|embed|video|live/i;

// Container classes of common web video players. Fullscreening the player's own
// container keeps its controls/subtitles; fullscreening a bare <video> would not.
var KNOWN_PLAYERS = [
  '.jwplayer', '.rmp-container', '.video-js', '.bitmovinplayer-container',
  '.shaka-video-container', '.plyr', '.html5-video-player', '.theoplayer-container',
  '.clappr-player', '.fp-player', '.mejs__container', '.dplayer', '.vjs-player'
].join(',');

function area(el) {
  var r = el.getBoundingClientRect();
  return (r.width > 160 && r.height > 90) ? r.width * r.height : 0;
}

function fill(el) {
  // Fallback when the fullscreen API is refused: stretch the player over the
  // whole viewport (Firefox runs in kiosk mode, so the viewport is the screen).
  if (el.getAttribute('data-tv-fill')) return;
  el.setAttribute('data-tv-fill', '1');
  var decl = {
    position: 'fixed', top: '0', left: '0', right: '0', bottom: '0',
    width: '100vw', height: '100vh', 'max-width': 'none', 'max-height': 'none',
    margin: '0', 'z-index': '2147483647', background: '#000', transform: 'none'
  };
  for (var k in decl) el.style.setProperty(k, decl[k], 'important');
  document.documentElement.style.setProperty('overflow', 'hidden', 'important');
}

var videos = Array.prototype.slice.call(document.querySelectorAll('video'));
var main = null, bestArea = 0;
videos.forEach(function (v) {
  var a = area(v);
  if (a > bestArea) { bestArea = a; main = v; }
});

var fsEl = document.fullscreenElement;
var res = { url: location.href, video: !!main, fullscreen: !!fsEl, playing: false, muted: false };

if (!main) {
  // No <video> in this document: the player may live inside an iframe (e.g. a
  // Dailymotion/YouTube embed). Prefer a frame from a video host, else the biggest.
  var frame = null, frameScore = 0;
  Array.prototype.forEach.call(document.querySelectorAll('iframe'), function (f) {
    var a = area(f);
    if (!a) return;
    var score = a * (PLAYER_HOSTS.test(f.src || '') ? 4 : 1);
    if (score > frameScore) { frameScore = score; frame = f; }
  });
  if (frame && (opts.inFrame || area(frame) > 0.15 * innerWidth * innerHeight)) {
    res.frame = frame;   // the server enters it and runs this script inside
    res.frameSrc = (frame.src || '').slice(0, 80);
    if (!opts.inFrame && !fsEl && opts.elapsed > (PLAYER_HOSTS.test(frame.src || '') ? 3 : 8)) {
      // Fullscreen the whole iframe from the top page.
      var pf = frame.requestFullscreen();
      if (pf && pf.catch) pf.catch(function () { fill(frame); });
      res.action = 'fullscreen-iframe';
    }
  }
  return res;
}

// Find the player container around the main video.
var box = main.closest(KNOWN_PLAYERS);
if (!box) {
  var vr = main.getBoundingClientRect();
  box = main;
  for (var p = main.parentElement; p && p !== document.body; p = p.parentElement) {
    var pr = p.getBoundingClientRect();
    if (Math.abs(pr.width - vr.width) > 4 || Math.abs(pr.height - vr.height) > 4) break;
    box = p;
  }
}

// An ad is playing if another video is running or the player flags an ad *in
// progress* (jw-flag-ads, vjs-ad-playing/-loading, YouTube's ad-showing...).
// Classes that only mean "ads plugin present" (vjs-ad-controls, vjs-ads-ready)
// must not count, or the player would never be started.
var AD_FLAGS = /(^|\s)(jw-flag-ads|[\w-]*ad-(playing|loading|active|showing))(\s|$)/i;
var adPlaying = videos.some(function (v) { return v !== main && !v.paused && v.currentTime > 0; }) ||
  AD_FLAGS.test(String(box.className));
res.ad = adPlaying;
res.player = (box.id ? '#' + box.id : '') + (typeof box.className === 'string' ? '.' + box.className.trim().split(/\s+/)[0] : '');

// 1) Fullscreen the player (inside an iframe the iframe itself is already
//    fullscreen from the top page, so nothing to do here).
if (fsEl && !opts.inFrame && fsEl !== box && !fsEl.contains(main)) {
  // Something else (e.g. an iframe chosen before the real player appeared) is
  // fullscreen: leave it; the next pass fullscreens the player.
  document.exitFullscreen().catch(function () {});
  res.action = 'exit-wrong-fullscreen';
} else if (!fsEl && !opts.inFrame) {
  try {
    var pr2 = box.requestFullscreen();
    if (pr2 && pr2.catch) pr2.catch(function () { fill(box); });
    res.action = 'fullscreen';
  } catch (e) { fill(box); }
}
res.filled = !!box.getAttribute('data-tv-fill');

// 2) Sound on (many sites start muted to get around autoplay rules).
res.playing = !main.paused && !main.ended;
res.muted = main.muted || main.volume === 0;
if (!adPlaying && res.muted) {
  main.muted = false;
  if (main.volume === 0) main.volume = 1;
  res.action = (res.action ? res.action + '+' : '') + 'unmute';
}

// 3) Start playback if the player is waiting for a click.
if (!adPlaying && !res.playing && opts.elapsed > 4) {
  if (main.currentSrc || main.src) {
    var pp = main.play();
    if (pp && pp.catch) pp.catch(function () {});
    res.action = (res.action ? res.action + '+' : '') + 'play';
  }
  // Last resort, once: a real click on the player (only after it is already
  // fullscreen, so the click lands on the player's own play button).
  if (main.currentTime === 0 && opts.elapsed > 8 && !(opts.clicks > 0) && (fsEl || res.filled || opts.inFrame)) {
    var r2 = main.getBoundingClientRect();
    res.click = [Math.round(r2.left + r2.width / 2), Math.round(r2.top + r2.height / 2)];
  }
}
return res;
