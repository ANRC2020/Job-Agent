const DEFAULT_PORT = 8765;
const PROBE_PORTS = [DEFAULT_PORT, ...Array.from({ length: 15 }, (_, index) => 8785 + index)];

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  chrome.alarms.create("clover-status", { periodInMinutes: 0.5 });
  await updateBadge();
});

chrome.runtime.onStartup.addListener(updateBadge);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "clover-status") updateBadge();
});

chrome.tabs.onActivated.addListener(() => broadcastPageChanged());
chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url) broadcastPageChanged();
});

function broadcastPageChanged() {
  chrome.runtime.sendMessage({ type: "PAGE_CHANGED" }).catch(() => {});
}

async function state() {
  return chrome.storage.local.get(["cloverBaseUrl", "cloverToken"]);
}

async function probeBaseUrl() {
  const saved = await state();
  const candidates = [
    saved.cloverBaseUrl,
    ...PROBE_PORTS.map((port) => `http://127.0.0.1:${port}`),
  ].filter(Boolean);
  for (const baseUrl of [...new Set(candidates)]) {
    try {
      const response = await fetch(`${baseUrl}/api/extension/status`, {
        cache: "no-store",
        signal: AbortSignal.timeout(1200),
      });
      if (response.ok) {
        await chrome.storage.local.set({ cloverBaseUrl: baseUrl });
        return baseUrl;
      }
    } catch {
      // Try the next local port.
    }
  }
  throw new Error("Clover is not running. Open the Clover desktop app first.");
}

async function cloverRequest(path, { method = "GET", body, authenticated = true } = {}) {
  const saved = await state();
  const baseUrl = saved.cloverBaseUrl || await probeBaseUrl();
  const headers = { "Content-Type": "application/json" };
  if (authenticated) {
    if (!saved.cloverToken) throw new Error("Pair this extension from Clover Settings first.");
    headers.Authorization = `Bearer ${saved.cloverToken}`;
  }
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(180000),
    });
  } catch {
    await chrome.storage.local.remove("cloverBaseUrl");
    throw new Error("Clover could not be reached. Make sure the desktop app is open.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // Keep the response fallback below.
  }
  if (response.status === 401) {
    await chrome.storage.local.remove("cloverToken");
  }
  if (!response.ok) throw new Error(payload.error || "Clover could not complete that request.");
  return payload;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) throw new Error("There is no active web page to inspect.");
  return tab;
}

function originPattern(url) {
  const parsed = new URL(url);
  if (!["http:", "https:"].includes(parsed.protocol)) return null;
  if (["127.0.0.1", "localhost", "::1"].includes(parsed.hostname)) return null;
  return `${parsed.protocol}//${parsed.host}/*`;
}

async function hasSiteAccess(selectedTab = null) {
  const tab = selectedTab || await activeTab();
  const origin = originPattern(tab.url);
  if (!origin) return { allowed: false, origin: null, unsupported: true, url: tab.url };
  return {
    allowed: await chrome.permissions.contains({ origins: [origin] }),
    origin,
    url: tab.url,
  };
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "PING" });
  } catch {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
  }
}

async function capturePage(selectedTab = null) {
  const tab = selectedTab || await activeTab();
  const access = await hasSiteAccess(tab);
  if (!access.allowed) {
    return {
      needsPermission: !access.unsupported,
      unsupported: Boolean(access.unsupported),
      origin: access.origin,
      url: tab.url,
    };
  }
  await ensureContentScript(tab.id);
  return chrome.tabs.sendMessage(tab.id, { type: "CAPTURE_PAGE" });
}

async function sendToPage(message, selectedTab = null) {
  const tab = selectedTab || await activeTab();
  await ensureContentScript(tab.id);
  return chrome.tabs.sendMessage(tab.id, message);
}

function submissionSessionKey(actionId) {
  return `cloverSubmission:${String(actionId || "")}`;
}

async function updateBadge() {
  try {
    const saved = await state();
    const status = await cloverRequest("/api/extension/status", {
      authenticated: Boolean(saved.cloverToken),
    });
    const ready = status.readiness?.ready;
    await chrome.action.setBadgeText({ text: ready ? "" : "…" });
    await chrome.action.setBadgeBackgroundColor({ color: ready ? "#3c7658" : "#9b7640" });
  } catch {
    await chrome.action.setBadgeText({ text: "!" });
    await chrome.action.setBadgeBackgroundColor({ color: "#9b554d" });
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handle = async () => {
    switch (message?.type) {
      case "STATUS": {
        const saved = await state();
        const status = await cloverRequest("/api/extension/status", {
          authenticated: Boolean(saved.cloverToken),
        });
        return { ...status, hasToken: Boolean(saved.cloverToken) };
      }
      case "PAIR": {
        const payload = await cloverRequest("/api/extension/pair", {
          method: "POST",
          authenticated: false,
          body: {
            code: message.code,
            name: "Clover Browser Companion",
            extensionId: chrome.runtime.id,
          },
        });
        await chrome.storage.local.set({ cloverToken: payload.token });
        await updateBadge();
        return { paired: true };
      }
      case "UNPAIR":
        await chrome.storage.local.remove("cloverToken");
        await updateBadge();
        return { paired: false };
      case "SITE_ACCESS":
        return hasSiteAccess();
      case "CAPTURE_PAGE":
        return capturePage();
      case "ANALYZE_PAGE":
        return cloverRequest("/api/extension/analyze", {
          method: "POST",
          body: { page: message.page, question: message.question || "" },
        });
      case "SUGGEST_FIELDS":
        return cloverRequest("/api/extension/suggest-fields", {
          method: "POST",
          body: { page: message.page, instructions: message.instructions || "" },
        });
      case "SAVE_OPPORTUNITY":
        return cloverRequest("/api/extension/save-opportunity", {
          method: "POST",
          body: { page: message.page },
        });
      case "FILL_FIELDS":
        return sendToPage({ type: "FILL_FIELDS", suggestions: message.suggestions || [] });
      case "UPLOAD_RESUME": {
        const file = await cloverRequest("/api/extension/application-document?kind=resume");
        return sendToPage({ type: "UPLOAD_FILE", file });
      }
      case "REQUEST_SUBMISSION": {
        const tab = await activeTab();
        const page = await capturePage(tab);
        const review = await cloverRequest("/api/extension/submission/request", {
          method: "POST",
          body: { page },
        });
        await chrome.storage.session.set({
          [submissionSessionKey(review.actionId)]: { tabId: tab.id },
        });
        return review;
      }
      case "CANCEL_SUBMISSION": {
        const result = await cloverRequest("/api/extension/submission/cancel", {
          method: "POST",
          body: { actionId: message.actionId },
        });
        await chrome.storage.session.remove(submissionSessionKey(message.actionId));
        return result;
      }
      case "CONFIRM_SUBMISSION": {
        const key = submissionSessionKey(message.actionId);
        const stored = (await chrome.storage.session.get(key))[key];
        const tab = await activeTab();
        if (!stored || stored.tabId !== tab.id) {
          throw new Error("Return to the application tab and review it again before submitting.");
        }
        const page = await capturePage(tab);
        const approval = await cloverRequest("/api/extension/submission/approve", {
          method: "POST",
          body: { actionId: message.actionId, page },
        });
        await chrome.storage.session.remove(key);
        let submitted;
        try {
          submitted = await sendToPage({
            type: "SUBMIT_APPLICATION",
            actionId: approval.actionId,
            expectedUrl: approval.expectedUrl,
          }, tab);
        } catch (error) {
          await cloverRequest("/api/extension/submission/complete", {
            method: "POST",
            body: { actionId: approval.actionId, succeeded: false },
          }).catch(() => {});
          throw error;
        }
        await cloverRequest("/api/extension/submission/complete", {
          method: "POST",
          body: { actionId: approval.actionId, succeeded: Boolean(submitted?.clicked) },
        });
        if (!submitted?.clicked) {
          throw new Error(submitted?.reason || "The application could not be submitted.");
        }
        return submitted;
      }
      case "UNDO_FILL":
        return sendToPage({ type: "UNDO_FILL" });
      default:
        throw new Error("Unknown browser companion request.");
    }
  };
  handle().then(
    (result) => sendResponse({ ok: true, result }),
    (error) => sendResponse({ ok: false, error: error.message || String(error) }),
  );
  return true;
});
