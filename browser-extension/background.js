// ONE Ghost Agent -- background service worker.
//
// Long-polls ONE's own local server (127.0.0.1:8000, never anything
// remote) for pending commands and carries them out using real Chrome tab
// APIs in Vineet's own browser -- no separate automation profile, no
// CAPTCHA triggers, inherits his real logged-in session. This exists
// because the old approach (a Playwright-driven, separate, cookie-less
// Chrome profile) is what triggered most of play_video's crash history:
// YouTube/Google treat a fresh unauthenticated automation browser very
// differently from Vineet's real one.
//
// The server's /poll endpoint itself blocks for up to ~20s waiting for a
// command before returning empty, so re-issuing the fetch immediately on
// each response gives near-instant delivery without needing sub-minute
// chrome.alarms (which Chrome doesn't reliably allow below 1 minute).

const SERVER = "http://127.0.0.1:8000";

let loopRunning = false;

async function pollOnce() {
  let data;
  try {
    const res = await fetch(`${SERVER}/v1/ghost-agent/extension/poll`);
    if (!res.ok) return;
    data = await res.json();
  } catch (err) {
    // ONE server not running right now -- quietly keep retrying, no error UI.
    return;
  }
  for (const cmd of data.commands || []) {
    handleCommand(cmd);
  }
}

async function reportResult(id, success, detail) {
  try {
    await fetch(`${SERVER}/v1/ghost-agent/extension/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, success, detail: String(detail || "") }),
    });
  } catch (err) {
    // best effort -- play_video.py has its own timeout on the ONE side.
  }
}

async function handleCommand(cmd) {
  if (cmd.type === "open_video") {
    try {
      const tab = await chrome.tabs.create({ url: cmd.url, active: true });
      await chrome.windows.update(tab.windowId, { focused: true });
      reportResult(cmd.id, true, "opened");
    } catch (err) {
      reportResult(cmd.id, false, err && err.message);
    }
  } else if (cmd.type === "add_bookmark") {
    try {
      await chrome.bookmarks.create({ title: cmd.title, url: cmd.url });
      reportResult(cmd.id, true, "bookmarked");
    } catch (err) {
      reportResult(cmd.id, false, err && err.message);
    }
  }
}

async function pollLoop() {
  if (loopRunning) return;
  loopRunning = true;
  try {
    // Runs "forever" -- each iteration is one long-poll HTTP request, which
    // keeps this service worker alive for its duration. The gap between
    // one request finishing and the next starting is a single microtask,
    // not enough idle time for Chrome to suspend the worker.
    while (true) {
      await pollOnce();
    }
  } finally {
    loopRunning = false;
  }
}

// Safety net: if the service worker got suspended/killed and lost the
// running loop (e.g. after a period with the ONE server unreachable),
// this fires at least once a minute to restart it. chrome.alarms is the
// one thing guaranteed to wake a terminated MV3 service worker.
chrome.alarms.create("ghost-agent-poll-watchdog", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "ghost-agent-poll-watchdog") pollLoop();
});

chrome.runtime.onStartup.addListener(pollLoop);
chrome.runtime.onInstalled.addListener(pollLoop);
pollLoop();
