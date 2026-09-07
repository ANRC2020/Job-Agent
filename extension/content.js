(() => {
  if (globalThis.__cloverCompanionLoaded) return;
  globalThis.__cloverCompanionLoaded = true;

  const previousValues = new Map();
  const uploadedFiles = new Map();
  const submittedActions = new Set();
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

  function extractFileFields() {
    return [...document.querySelectorAll("input[type='file']")]
      .filter((element) => visible(element) && !element.disabled)
      .slice(0, 20)
      .map((element, index) => {
        const fieldId = `clover-file-${index}`;
        element.dataset.cloverFileId = fieldId;
        return {
          fieldId,
          label: labelFor(element) || "File upload",
          accept: element.getAttribute("accept") || "",
          hasFile: Boolean(element.files?.length),
          filename: String(element.files?.[0]?.name || "").slice(0, 300),
        };
      });
  }

  function unresolvedRequiredFields() {
    const controls = [...document.querySelectorAll(
      "input[required], textarea[required], select[required], [aria-required='true']"
    )];
    const unresolved = [];
    for (const element of controls) {
      const type = fieldType(element);
      if (!visible(element) || element.disabled || ["hidden", "submit", "button", "image"].includes(type)) {
        continue;
      }
      let complete;
      if (type === "checkbox") {
        complete = element.checked;
      } else if (type === "radio") {
        const name = element.getAttribute("name");
        complete = name
          ? [...document.querySelectorAll(`input[type='radio'][name="${CSS.escape(name)}"]`)]
            .some((candidate) => candidate.checked)
          : element.checked;
      } else if (type === "file") {
        complete = Boolean(element.files?.length);
      } else {
        complete = Boolean(currentValue(element).trim());
      }
      if (!complete) {
        const label = labelFor(element) || "Required field";
        unresolved.push({ label, type, sensitive: sensitive(element, label) });
      }
    }
    return unresolved.slice(0, 30);
  }

  function submitControl() {
    const candidates = [...document.querySelectorAll("button, input[type='submit']")]
      .filter((element) => visible(element) && !element.disabled)
      .map((element) => ({
        element,
        label: normalized(textOf(element) || element.value || element.getAttribute("aria-label")),
      }))
      .filter(({ label }) => label && !/\b(next|continue|save|review|back|cancel|preview)\b/i.test(label));
    const explicit = candidates.filter(({ label }) =>
      /\b(submit|send application|complete application|send)\b/i.test(label)
    );
    const usable = explicit.length ? explicit : candidates.filter(
      ({ element }) => (
        element.type?.toLowerCase() === "submit"
        && Boolean(element.closest("form")?.querySelector("input, textarea, select"))
      )
    );
    return {
      element: usable.length === 1 ? usable[0].element : null,
      label: usable.length === 1 ? usable[0].label : "",
      ambiguous: usable.length > 1,
    };
  }

  function applicationState() {
    const control = submitControl();
    return {
      fileFields: extractFileFields(),
      unresolvedRequired: unresolvedRequiredFields(),
      submit: {
        available: Boolean(control.element),
        ambiguous: control.ambiguous,
        label: control.label,
      },
    };
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
    let posting = null;
    for (const script of document.querySelectorAll("script[type='application/ld+json']")) {
      try {
        const parsed = JSON.parse(script.textContent || "null");
        const candidates = Array.isArray(parsed) ? parsed : [parsed];
        for (const item of candidates) {
          const entries = item?.["@graph"] && Array.isArray(item["@graph"]) ? item["@graph"] : [item];
          for (const entry of entries) {
            if (entry?.["@type"] === "JobPosting") {
              posting ||= entry;
              title ||= normalized(entry.title);
              company ||= normalized(entry.hiringOrganization?.name);
            }
          }
        }
      } catch {
        // Invalid page metadata is ignored.
      }
    }
    const rawLocations = posting?.jobLocation
      ? (Array.isArray(posting.jobLocation) ? posting.jobLocation : [posting.jobLocation])
      : [];
    const locations = rawLocations.map((item) => {
      const address = item?.address;
      if (typeof address === "string") return normalized(address);
      return normalized([
        address?.addressLocality,
        address?.addressRegion,
        address?.addressCountry,
      ].filter(Boolean).join(", "));
    }).filter(Boolean);
    const remote = /telecommute|remote/i.test(String(posting?.jobLocationType || ""));
    const salary = posting?.baseSalary?.value || {};
    return {
      title: title || normalized(document.title),
      company,
      companyWebsite: String(posting?.hiringOrganization?.sameAs || ""),
      location: {
        text: locations.join("; "),
        remote,
        arrangement: remote ? "remote" : "",
      },
      compensation: {
        currency: posting?.baseSalary?.currency || "",
        min: salary.minValue ?? null,
        max: salary.maxValue ?? null,
        period: String(salary.unitText || "").toLowerCase(),
      },
      employmentType: Array.isArray(posting?.employmentType)
        ? posting.employmentType.join(", ")
        : String(posting?.employmentType || ""),
      workplaceType: remote ? "Remote" : "",
      postedAt: String(posting?.datePosted || ""),
      externalId: String(
        typeof posting?.identifier === "object"
          ? posting?.identifier?.value || ""
          : posting?.identifier || ""
      ),
    };
  }

  function capturePage() {
    if (capturedUrl !== location.href) {
      previousValues.clear();
      uploadedFiles.clear();
      submittedActions.clear();
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
      listing: {
        companyWebsite: metadata.companyWebsite,
        location: metadata.location,
        compensation: metadata.compensation,
        employmentType: metadata.employmentType,
        workplaceType: metadata.workplaceType,
        postedAt: metadata.postedAt,
        externalId: metadata.externalId,
      },
      postingText: jobPosting(),
      fields: extractFields(),
      application: applicationState(),
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

  function uploadFile(file) {
    const fields = extractFileFields();
    const preferred = fields.find((field) => /\b(resume|résumé|cv)\b/i.test(field.label))
      || (
        fields.length === 1
        && /\b(upload|attachment|document|file)\b/i.test(fields[0].label)
        && !/\bcover\b/i.test(fields[0].label)
        ? fields[0]
        : null
      );
    if (!preferred) {
      return { uploaded: false, reason: "Clover could not identify one resume upload field." };
    }
    const accepted = preferred.accept.split(",").map((value) => value.trim().toLowerCase()).filter(Boolean);
    const filename = String(file.filename || "resume.pdf");
    const mimeType = String(file.mimeType || "application/octet-stream").toLowerCase();
    const extension = filename.includes(".") ? `.${filename.split(".").pop().toLowerCase()}` : "";
    if (accepted.length && !accepted.some((value) =>
      value === extension
      || value === mimeType
      || (value.endsWith("/*") && mimeType.startsWith(value.slice(0, -1)))
    )) {
      return {
        uploaded: false,
        reason: `This field does not accept ${extension || mimeType} resume files.`,
      };
    }
    const element = [...document.querySelectorAll("[data-clover-file-id]")]
      .find((candidate) => candidate.dataset.cloverFileId === preferred.fieldId);
    if (!element || element.files?.length) {
      return { uploaded: false, reason: "That upload field already contains a file." };
    }
    const bytes = Uint8Array.from(atob(String(file.content || "")), (char) => char.charCodeAt(0));
    const candidate = new File(
      [bytes],
      filename,
      { type: mimeType },
    );
    const transfer = new DataTransfer();
    transfer.items.add(candidate);
    element.files = transfer.files;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.style.outline = "2px solid #5f9f7b";
    element.style.outlineOffset = "2px";
    element.dataset.cloverFilled = "true";
    uploadedFiles.set(preferred.fieldId, element);
    return { uploaded: true, filename: candidate.name, field: preferred.label, canUndo: true };
  }

  function submitApplication(actionId, expectedUrl) {
    const action = String(actionId || "");
    if (!action || submittedActions.has(action)) {
      return { clicked: false, reason: "This submission approval has already been used." };
    }
    const expected = new URL(String(expectedUrl || ""));
    const current = new URL(location.href);
    if (expected.origin !== current.origin || expected.pathname !== current.pathname) {
      return { clicked: false, reason: "The application page changed after review." };
    }
    const unresolved = unresolvedRequiredFields();
    if (unresolved.length) {
      return {
        clicked: false,
        reason: `Complete required fields first: ${unresolved.slice(0, 3).map((item) => item.label).join(", ")}.`,
      };
    }
    const control = submitControl();
    if (!control.element || control.ambiguous) {
      return { clicked: false, reason: "The final submission button is no longer unambiguous." };
    }
    const form = control.element.closest("form");
    if (form && !form.checkValidity()) {
      return { clicked: false, reason: "The application form still has invalid fields." };
    }
    submittedActions.add(action);
    control.element.click();
    return { clicked: true, buttonLabel: control.label };
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
    for (const [id, element] of uploadedFiles.entries()) {
      if (!element?.isConnected) continue;
      const transfer = new DataTransfer();
      element.files = transfer.files;
      element.value = "";
      element.style.outline = "";
      element.style.outlineOffset = "";
      delete element.dataset.cloverFilled;
      uploadedFiles.delete(id);
      restored += 1;
    }
    return { restored };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "PING") {
      sendResponse({ ready: true });
    } else if (message?.type === "CAPTURE_PAGE") {
      sendResponse(capturePage());
    } else if (message?.type === "FILL_FIELDS") {
      sendResponse(fillFields(message.suggestions));
    } else if (message?.type === "UPLOAD_FILE") {
      sendResponse(uploadFile(message.file || {}));
    } else if (message?.type === "SUBMIT_APPLICATION") {
      sendResponse(submitApplication(message.actionId, message.expectedUrl));
    } else if (message?.type === "UNDO_FILL") {
      sendResponse(undoFill());
    }
  });

  addEventListener("pagehide", () => previousValues.clear());
})();
