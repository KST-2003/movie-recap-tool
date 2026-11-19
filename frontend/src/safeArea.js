/** The system bars in pixels: status bar on top, gesture / home bar at the bottom (0 on the web, and on phones that have none).
 *  They come from the --safe-top / --safe-bottom variables (see index.css and native.js), which can hold expressions such as
 *  max(env(...), var(...)); a hidden probe element lets the browser resolve them to real pixels. Used for things drawn with position: fixed
 *  by script (dropdown menus), which must not reach under the status bar. */
export function safeInsets() {
  try {
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;visibility:hidden;pointer-events:none;padding-top:var(--safe-top,0px);padding-bottom:var(--safe-bottom,0px)';
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    const top = parseFloat(cs.paddingTop) || 0;
    const bottom = parseFloat(cs.paddingBottom) || 0;
    probe.remove();
    return { top, bottom };
  } catch (e) {
    return { top: 0, bottom: 0 };
  }
}
