(() => {
  if (globalThis.__cloverCompanionLoaded) return;
  globalThis.__cloverCompanionLoaded = true;

  const previousValues = new Map();
  let capturedUrl = location.href;
  const BLOCKED_TYPES = new Set([
    "password", "hidden", "file", "submit", "reset", "button", "image",
    "checkbox", "radio",
  ]);
  const SENSITIVE = /\b(password|passcode|credit|debit|card number|cvv|cvc|bank|routing|social security|ssn|national id|government id|passport|driver.?s license|race|ethnicity|gender|sex|sexual orientation|disability|veteran|religion|date of birth|birth date|medical|health)\b/i;

  function visible(element) {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function normalized(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function textOf(element) {
    return element?.innerText ?? element?.textContent ?? "";
  }

  function labelFor(element) {
    const explicit = element.id
      ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
      : null;
    const wrapping = element.closest("label");
    const labelledBy = (element.getAttribute("aria-labelledby") || "")
      .split(/\s+/)
      .filter(Boolean)
      .map((id) => textOf(document.getElementById(id)))
      .filter(Boolean)
      .join(" ");
    const nearby = element.parentElement?.querySelector(
      ":scope > label, :scope > legend, :scope > .label, :scope > [class*='label']"
    );
    return normalized(
      textOf(explicit)
      || textOf(wrapping)
      || element.getAttribute("aria-label")
      || labelledBy
      || textOf(nearby)
      || element.getAttribute("placeholder")
      || element.getAttribute("name")
    ).slice(0, 500);
  }

  function fieldType(element) {
    if (element instanceof HTMLTextAreaElement) return "textarea";
    if (element instanceof HTMLSelectElement) return "select";
    if (element.isContentEditable) return "contenteditable";
    return String(element.getAttribute("type") || "text").toLowerCase();
  }

  function sensitive(element, label) {
    const text = [
      label,
      element.getAttribute("name"),
      element.getAttribute("id"),
      element.getAttribute("autocomplete"),
      element.getAttribute("placeholder"),
    ].join(" ");
    return SENSITIVE.test(text);
  }

  function currentValue(element) {
    return element.isContentEditable ? normalized(textOf(element)) : String(element.value || "");
  }

  function extractFields() {
    const candidates = [...document.querySelectorAll("input, textarea, select, [contenteditable='true']")];
    const fields = [];
    candidates.forEach((element, index) => {
      const type = fieldType(element);
      const label = labelFor(element);
      if (!visible(element) || element.disabled || element.readOnly || BLOCKED_TYPES.has(type)) return;
      if (sensitive(element, label)) return;
      const fieldId = `clover-field-${index}`;
      element.dataset.cloverFieldId = fieldId;
      fields.push({
        fieldId,
        label,
        name: element.getAttribute("name") || "",
        type,
        required: Boolean(element.required || element.getAttribute("aria-required") === "true"),
        maxLength: Number(element.maxLength > 0 ? element.maxLength : 0),
        currentValue: currentValue(element),
        options: element instanceof HTMLSelectElement
          ? [...element.options].map((option) => normalized(option.textContent)).filter(Boolean)
          : [],
        sensitive: false,
      });
    });
    return fields;
  }

  function jobPosting() {
    const roots = [
      document.querySelector("[itemtype*='JobPosting']"),
      document.querySelector("main"),
      document.querySelector("article"),
      document.body,
    ].filter(Boolean);
    return normalized(textOf(roots[0])).slice(0, 30000);
  }

  function jobMetadata() {
    let title = normalized(textOf(document.querySelector("h1")));
    let company = "";
    for (const script of document.querySelectorAll("script[type='application/ld+json']")) {
      try {
        const parsed = JSON.parse(script.textContent || "null");
        const candidates = Array.isArray(parsed) ? parsed : [parsed];
        for (const item of candidates) {
          const entries = item?.["@graph"] && Array.isArray(item["@graph"]) ? item["@graph"] : [item];
          for (const entry of entries) {
            if (entry?.["@type"] === "JobPosting") {
              title ||= normalized(entry.title);
              company ||= normalized(entry.hiringOrganization?.name);
            }
          }
        }
      } catch {
        // Invalid page metadata is ignored.
      }
    }
    return {
      title: title || normalized(document.title),
      company,
    };
  }

  function capturePage() {
    if (capturedUrl !== location.href) {
      previousValues.clear();
      document.querySelectorAll("[data-clover-filled]").forEach((element) => {
        element.style.outline = "";
        element.style.outlineOffset = "";
        delete element.dataset.cloverFilled;
      });
      capturedUrl = location.href;
    }
    const metadata = jobMetadata();
    return {
      url: location.href,
      title: metadata.title,
      company: metadata.company,
      postingText: jobPosting(),
      fields: extractFields(),
      capturedAt: new Date().toISOString(),
    };
  }

  function setFrameworkValue(element, value) {
    if (element.isContentEditable) {
      element.textContent = value;
    } else if (element instanceof HTMLSelectElement) {
      const option = [...element.options].find(
        (item) => normalized(item.value).toLowerCase() === normalized(value).toLowerCase()
          || normalized(item.textContent).toLowerCase() === normalized(value).toLowerCase()
      );
      if (!option) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(element, option.value);
    } else {
      const prototype = element instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (!setter) return false;
      setter.call(element, value);
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function fillFields(suggestions) {
    let filled = 0;
    let skipped = 0;
    for (const suggestion of suggestions || []) {
      const id = String(suggestion.fieldId || "");
      const element = [...document.querySelectorAll("[data-clover-field-id]")]
        .find((candidate) => candidate.dataset.cloverFieldId === id);
      if (!element || currentValue(element).trim() || sensitive(element, labelFor(element))) {
        skipped += 1;
        continue;
      }
      previousValues.set(id, {
        value: currentValue(element),
        outline: element.style.outline,
        outlineOffset: element.style.outlineOffset,
      });
      if (!setFrameworkValue(element, String(suggestion.value || ""))) {
        previousValues.delete(id);
        skipped += 1;
        continue;
      }
      element.style.outline = "2px solid #5f9f7b";
      element.style.outlineOffset = "2px";
      element.dataset.cloverFilled = "true";
      filled += 1;
    }
    return { filled, skipped, canUndo: previousValues.size > 0 };
  }

  function undoFill() {
    let restored = 0;
    for (const [id, previous] of previousValues.entries()) {
      const element = [...document.querySelectorAll("[data-clover-field-id]")]
        .find((candidate) => candidate.dataset.cloverFieldId === id);
      if (!element) continue;
      setFrameworkValue(element, previous.value);
      element.style.outline = previous.outline;
      element.style.outlineOffset = previous.outlineOffset;
      delete element.dataset.cloverFilled;
      restored += 1;
    }
    previousValues.clear();
    return { restored };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "PING") {
      sendResponse({ ready: true });
    } else if (message?.type === "CAPTURE_PAGE") {
      sendResponse(capturePage());
    } else if (message?.type === "FILL_FIELDS") {
      sendResponse(fillFields(message.suggestions));
    } else if (message?.type === "UNDO_FILL") {
      sendResponse(undoFill());
    }
  });

  addEventListener("pagehide", () => previousValues.clear());
})();
