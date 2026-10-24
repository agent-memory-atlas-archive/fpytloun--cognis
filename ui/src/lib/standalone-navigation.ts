/** Exit an installed-app preview without depending on window.close(). */
export function standaloneCloseHandler(browser: Window, referrer: string): (() => void) | null {
  const installed = browser.matchMedia('(display-mode: standalone)').matches
    || browser.matchMedia('(display-mode: minimal-ui)').matches
    || (browser.navigator as Navigator & { standalone?: boolean }).standalone === true;
  if (!installed) return null;
  return () => {
    let fromApp = false;
    try {
      const previous = new URL(referrer);
      fromApp = previous.origin === browser.location.origin
        && !previous.pathname.startsWith('/api/');
    } catch {
      // A direct app launch has no referrer; return to app home.
    }
    if (fromApp && browser.history.length > 1) browser.history.back();
    else browser.location.assign('/');
  };
}
