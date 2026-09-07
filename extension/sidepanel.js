const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [element.id, element]),
);
let page = null;
let permissionOrigin = null;
let captureTimer = null;
let junoReady = false;
let paired = false;

async function message(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...extra });
  if (!response?.ok) throw new Error(response?.error || "Clover did not respond.");
  return response.result;
}

function show(element, visible = true) {
  element.classList.toggle("hidden", !visible);
}

function notice(text = "", error = false) {
  elements.notice.textContent = text;
  elements.notice.classList.toggle("error", error);
}

function busy(button, value) {
  button.dataset.busy = value ? "true" : "false";
  button.disabled = value;
}

function setConnected(connected, ready = false) {
  elements.connection.textContent = connected ? (ready ? "Ready" : "Starting") : "Not paired";
}

function applyJunoGate() {
  elements.analyze.disabled = !junoReady || elements.analyze.dataset.busy === "true";
  elements.fill.disabled = !junoReady || elements.fill.dataset.busy === "true";
  elements.question.disabled = !junoReady;
  const chatButton = elements["chat-form"].querySelector("button");
  chatButton.disabled = !junoReady || chatButton.dataset.busy === "true";
}

async function refreshStatus({ capturePage = false } = {}) {
  try {
    const status = await message("STATUS");
    const wasPaired = paired;
    paired = Boolean(status.paired && status.hasToken);
    junoReady = Boolean(status.readiness?.ready);
    setConnected(paired, Boolean(status.readiness?.ready));
    show(elements.pairing, !paired);
    if (paired && (capturePage || !wasPaired)) await capture();
    applyJunoGate();
    if (paired && !junoReady) {
      notice("Juno is downloading. Analysis and answer generation will unlock automatically.");
    }
  } catch (error) {
    paired = false;
    junoReady = false;
    applyJunoGate();
    setConnected(false);
    show(elements.pairing);
    notice(error.message, true);
  }
}

async function capture() {
  try {
    const result = await message("CAPTURE_PAGE");
    if (result.needsPermission || result.unsupported) {
      permissionOrigin = result.origin;
      page = null;
      show(elements.permission);
      elements["permission-title"].textContent = result.unsupported
        ? "Open a public job page"
        : "Let Juno read this site?";
      elements["permission-copy"].textContent = result.unsupported
        ? "Clover does not inspect browser-internal pages or local web apps."
        : "Clover reads the active page only while you use this panel. Access is granted per site.";
      show(elements["allow-site"], !result.unsupported);
      show(elements["page-card"], false);
      show(elements["application-card"], false);
      show(elements["chat-card"], false);
      notice("Page access stays limited to this site.");
      return;
    }
    page = result;
    permissionOrigin = null;
    show(elements.permission, false);
    show(elements["page-card"]);
    show(elements["chat-card"]);
    elements["page-title"].textContent = page.title || "Untitled page";
    const details = [page.company, `${page.fields?.length || 0} safe fields`].filter(Boolean);
    elements["page-meta"].textContent = details.join(" · ");
    show(elements["application-card"], Boolean(page.fields?.length));
    elements["field-count"].textContent = `${page.fields?.length || 0} safe application fields`;
    notice("This capture is temporary unless you save the opportunity.");
  } catch (error) {
    notice(error.message, true);
  }
}

async function withButton(button, action) {
  busy(button, true);
  notice("Juno is working…");
  try {
    await action();
  } catch (error) {
    notice(error.message, true);
  } finally {
    busy(button, false);
    applyJunoGate();
  }
}

elements["pair-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  withButton(elements["pair-submit"], async () => {
    await message("PAIR", { code: elements["pair-code"].value });
    elements["pair-code"].value = "";
    notice("Browser paired.");
    await refreshStatus({ capturePage: true });
  });
});

elements["allow-site"].addEventListener("click", async () => {
  if (!permissionOrigin) return;
  try {
    const allowed = await chrome.permissions.request({ origins: [permissionOrigin] });
    if (!allowed) {
      notice("Clover cannot inspect this site without page access.", true);
      return;
    }
    await capture();
  } catch (error) {
    notice(error.message, true);
  }
});

elements.analyze.addEventListener("click", () => {
  if (!junoReady) return;
  withButton(elements.analyze, async () => {
    const result = await message("ANALYZE_PAGE", { page });
    elements.response.textContent = result.content;
    show(elements["response-card"]);
    notice("Analysis uses this page temporarily.");
  });
});

elements.save.addEventListener("click", () => {
  withButton(elements.save, async () => {
    const result = await message("SAVE_OPPORTUNITY", { page });
    notice(`Saved ${result.title || page.title} to Clover.`);
  });
});

elements.fill.addEventListener("click", () => {
  if (!junoReady) return;
  withButton(elements.fill, async () => {
    const generated = await message("SUGGEST_FIELDS", {
      page,
      instructions: elements["fill-instructions"].value,
    });
    if (!generated.suggestions?.length) {
      notice(generated.skipped || "Juno did not find any grounded answers to fill.");
      return;
    }
    const result = await message("FILL_FIELDS", { suggestions: generated.suggestions });
    show(elements.undo, Boolean(result.canUndo));
    notice(`Filled ${result.filled} fields. Review every answer before submitting.`);
    await capture();
  });
});

elements.undo.addEventListener("click", async () => {
  try {
    const result = await message("UNDO_FILL");
    show(elements.undo, false);
    notice(`Restored ${result.restored} fields.`);
    await capture();
  } catch (error) {
    notice(error.message, true);
  }
});

elements["chat-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  const question = elements.question.value.trim();
  if (!question || !page || !junoReady) return;
  withButton(elements["chat-form"].querySelector("button"), async () => {
    const result = await message("ANALYZE_PAGE", { page, question });
    elements.response.textContent = result.content;
    show(elements["response-card"]);
    elements.question.value = "";
    notice("Page chat is not added to durable conversation history.");
  });
});

chrome.runtime.onMessage.addListener((incoming) => {
  if (incoming?.type !== "PAGE_CHANGED") return;
  clearTimeout(captureTimer);
  captureTimer = setTimeout(capture, 500);
});

applyJunoGate();
refreshStatus({ capturePage: true });
setInterval(() => refreshStatus(), 2500);
