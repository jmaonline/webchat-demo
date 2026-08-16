/*
 * Bookly Support — embeddable chat widget loader.
 *
 * Drop this on ANY website with a single line:
 *   <script src="https://<your-bookly-app>.onrender.com/embed.js" async></script>
 *
 * It injects a floating chat bubble (bottom-right) via an iframe, so the
 * widget's styling is fully isolated from the host page's CSS — nothing
 * here can clash with or be broken by the site it's embedded on, and
 * vice versa. The iframe is resized between "just the bubble" and "open
 * chat panel" size via postMessage from the page it loads (/embed on the
 * Bookly backend).
 */
(function () {
  // Figure out our own origin from this <script> tag's src, so the
  // loader doesn't need any hardcoded configuration.
  var thisScript = document.currentScript;
  if (!thisScript) {
    var scripts = document.getElementsByTagName('script');
    thisScript = scripts[scripts.length - 1];
  }
  var origin;
  try {
    origin = new URL(thisScript.src).origin;
  } catch (e) {
    console.error('[bookly-embed] Could not determine backend origin from script src.');
    return;
  }

  var CLOSED_SIZE = { width: '92px', height: '92px' };
  var OPEN_SIZE = { width: '412px', height: '592px' };

  var iframe = document.createElement('iframe');
  iframe.src = origin + '/embed';
  iframe.title = 'Bookly Support Chat';
  iframe.setAttribute('allowtransparency', 'true');
  iframe.style.cssText = [
    'position: fixed',
    'right: 24px',
    'bottom: 24px',
    'width: ' + CLOSED_SIZE.width,
    'height: ' + CLOSED_SIZE.height,
    'border: none',
    'background: transparent',
    'z-index: 2147483000', // stay on top of virtually anything the host page has
    'transition: width 0.18s ease, height 0.18s ease',
    'color-scheme: light',
  ].join(';');

  window.addEventListener('load', function () {
    document.body.appendChild(iframe);
  });
  // In case 'load' already fired before this script ran.
  if (document.readyState === 'complete') {
    document.body.appendChild(iframe);
  }

  window.addEventListener('message', function (event) {
    if (event.origin !== origin) return; // only trust our own /embed page
    var data = event.data;
    if (!data || data.source !== 'bookly-widget' || data.type !== 'resize') return;

    var size = data.open ? OPEN_SIZE : CLOSED_SIZE;
    iframe.style.width = size.width;
    iframe.style.height = size.height;
  });
})();
