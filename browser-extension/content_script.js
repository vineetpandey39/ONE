// ONE Ghost Agent -- content script, runs on youtube.com pages.
//
// Auto-clicks any "Skip Ad" button the instant it becomes clickable, so
// Vineet never has to click it himself. Runs as a native content script
// (a MutationObserver watching the real DOM) instead of Playwright's old
// poll-every-1.5s query_selector loop -- reacts to the button appearing
// rather than waiting for the next poll tick, and has no thread-safety
// concerns since it's just normal page JS.

const SKIP_SELECTORS = [
  ".ytp-skip-ad-button",
  ".ytp-ad-skip-button",
  ".ytp-ad-skip-button-modern",
  "button.ytp-ad-skip-button-slot",
];

function trySkip() {
  for (const selector of SKIP_SELECTORS) {
    const el = document.querySelector(selector);
    if (el && el.offsetParent !== null) {
      el.click();
      return true;
    }
  }
  return false;
}

const observer = new MutationObserver(() => {
  trySkip();
});

observer.observe(document.documentElement, { childList: true, subtree: true });

// Cover the case where an ad's skip button is already present at load time
// (observer only reacts to future DOM changes) and the brief window right
// after a SPA navigation between videos where YouTube swaps the player
// without a full page reload.
trySkip();
setInterval(trySkip, 1000);
