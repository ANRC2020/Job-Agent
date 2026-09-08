"""Visible, constrained browser automation for job applications."""

from __future__ import annotations

import copy
import difflib
import json
import os
import platform
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from job_agent.documents import document_file
from job_agent.application_forms import (
    approve_application_submission,
    cancel_application_submission,
    complete_application_submission,
    confirm_application_received,
    record_application_sent,
    request_application_submission,
    sanitize_page,
    suggest_fields,
)
from job_agent.application_answers import (
    cached_answers,
    quick_answers,
    remember_answers,
    remember_user_answers,
)
from job_agent.storage import DEFAULT_PERSON_ID, app_data_dir

MANAGED_CONNECTION_ID = "clover-managed-browser"


def _browser_executable() -> str | None:
    system = platform.system()
    candidates: list[Path] = []
    if system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    elif system == "Windows":
        roots = [
            Path(value)
            for value in (
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            )
            if value
        ]
        for root in roots:
            candidates.extend(
                [
                    root / "Google/Chrome/Application/chrome.exe",
                    root / "Microsoft/Edge/Application/msedge.exe",
                    root / "BraveSoftware/Brave-Browser/Application/brave.exe",
                ]
            )
    else:
        for name in ("google-chrome", "microsoft-edge", "brave-browser", "chromium"):
            resolved = shutil.which(name)
            if resolved:
                candidates.append(Path(resolved))
    return next((str(path) for path in candidates if path.is_file()), None)

CAPTURE_SCRIPT = r"""
() => {
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  document.querySelectorAll("[data-clover-field-id]").forEach((el) => {
    delete el.dataset.cloverFieldId;
  });
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  const labelFor = (el) => {
    const explicit = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    return clean(explicit?.textContent || el.closest("label")?.textContent ||
      el.getAttribute("aria-label") || el.getAttribute("placeholder") ||
      el.getAttribute("name"));
  };
  const currentValue = (el) => {
    if (el.getAttribute("role") === "combobox") {
      const control = el.closest("[class*='control']");
      const selected = control?.querySelector(
        "[class*='single-value'], [class*='multi-value']"
      );
      if (selected) return clean(selected.textContent);
    }
    return clean(el.value ?? el.textContent);
  };
  const sensitive = (el, label) => /\b(password|passcode|credit|debit|card number|cvv|cvc|bank|routing|social security|ssn|national id|government id|passport|driver.?s license|race|racial|ethnic|ethnicity|hispanic|transgender|gender|sex|sexual orientation|disability|veteran|religion|date of birth|birth date|medical|health)\b/i
    .test(`${label} ${el.name || ""} ${el.autocomplete || ""}`);
  const fields = [];
  [...document.querySelectorAll("input, textarea, select, [contenteditable='true']")].forEach((el, index) => {
    const type = el.tagName === "SELECT" ? "select" :
      el.tagName === "TEXTAREA" ? "textarea" :
      el.isContentEditable ? "textarea" : clean(el.type || "text").toLowerCase();
    const label = labelFor(el);
    if (!visible(el) || el.disabled || el.readOnly || el.getAttribute("aria-hidden") === "true" ||
        ["hidden", "password", "file", "submit", "reset", "button", "image", "checkbox", "radio"].includes(type) ||
        sensitive(el, label)) return;
    const fieldId = `clover-field-${index}`;
    el.dataset.cloverFieldId = fieldId;
    fields.push({
      fieldId, label, name: el.name || "", type,
      required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
      maxLength: Number(el.maxLength > 0 ? el.maxLength : 0),
      currentValue: currentValue(el),
      options: el.tagName === "SELECT"
        ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean)
        : [],
      sensitive: false,
    });
  });
  const fileFields = [...document.querySelectorAll("input[type='file']")]
    .filter((el) => !el.disabled)
    .slice(0, 20)
    .map((el, index) => {
      const fieldId = `clover-file-${index}`;
      el.dataset.cloverFileId = fieldId;
      return {
        fieldId,
        label: clean(`${labelFor(el)} ${el.id || ""} ${el.name || ""}`) || "File upload",
        accept: el.accept || "",
        hasFile: Boolean(el.files?.length), filename: String(el.files?.[0]?.name || ""),
      };
    });
  const unresolvedRequired = [];
  const unresolvedKeys = new Set();
  [...document.querySelectorAll("input[required], textarea[required], select[required], [aria-required='true']")]
    .forEach((el, index) => {
    const type = el.tagName === "SELECT" ? "select" :
      el.tagName === "TEXTAREA" ? "textarea" :
      clean(el.type || el.tagName).toLowerCase();
    if (!visible(el) || el.disabled || el.getAttribute("aria-hidden") === "true" ||
        ["hidden", "submit", "button", "image"].includes(type)) return;
    const key = type === "radio" && el.name ? `radio:${el.name}` : `control:${index}`;
    if (unresolvedKeys.has(key)) return;
    unresolvedKeys.add(key);
    let complete = Boolean(currentValue(el));
    if (type === "checkbox") complete = el.checked;
    if (type === "radio") {
      complete = el.name
        ? [...document.querySelectorAll(`input[type='radio'][name="${CSS.escape(el.name)}"]`)].some((item) => item.checked)
        : el.checked;
    }
    if (type === "file") complete = Boolean(el.files?.length);
    if (!complete) {
      const group = type === "radio" && el.name
        ? [...document.querySelectorAll(`input[type='radio'][name="${CSS.escape(el.name)}"]`)]
        : [el];
      const fieldId = el.dataset.cloverFieldId || `clover-question-${index}`;
      group.forEach((item) => { item.dataset.cloverFieldId = fieldId; });
      const fieldset = el.closest("fieldset");
      const label = clean(fieldset?.querySelector("legend")?.textContent) ||
        labelFor(el) || "Required field";
      let options = el.tagName === "SELECT"
        ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean)
        : type === "radio"
          ? group.map((item) => labelFor(item)).filter(Boolean)
          : [];
      if (!options.length && el.getAttribute("role") === "combobox" &&
          /^(are|can|could|did|do|does|have|has|is|was|were|will|would)\b/i.test(label)) {
        options = ["Yes", "No"];
      }
      unresolvedRequired.push({
        fieldId, label, type, options,
        sensitive: sensitive(el, label),
      });
    }
  });
  const optionalQuestions = [];
  const optionalKeys = new Set();
  [...document.querySelectorAll("input, textarea, select, [contenteditable='true']")]
    .forEach((el, index) => {
    const type = el.tagName === "SELECT" ? "select" :
      el.tagName === "TEXTAREA" ? "textarea" :
      el.isContentEditable ? "textarea" : clean(el.type || "text").toLowerCase();
    if (!visible(el) || el.disabled || el.readOnly ||
        el.required || el.getAttribute("aria-required") === "true" ||
        el.getAttribute("aria-hidden") === "true" ||
        ["hidden", "password", "file", "submit", "reset", "button", "image"].includes(type)) return;
    const fieldset = el.closest("fieldset");
    const label = clean(fieldset?.querySelector("legend")?.textContent) ||
      labelFor(el) || "Optional question";
    if (!sensitive(el, label)) return;
    const key = type === "radio" && el.name ? `radio:${el.name}` : `control:${index}`;
    if (optionalKeys.has(key)) return;
    optionalKeys.add(key);
    const group = type === "radio" && el.name
      ? [...document.querySelectorAll(`input[type='radio'][name="${CSS.escape(el.name)}"]`)]
      : [el];
    let complete = Boolean(currentValue(el));
    if (type === "checkbox") complete = el.checked;
    if (type === "radio") complete = group.some((item) => item.checked);
    if (complete) return;
    const fieldId = el.dataset.cloverFieldId || `clover-optional-${index}`;
    group.forEach((item) => { item.dataset.cloverFieldId = fieldId; });
    const options = el.tagName === "SELECT"
      ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean)
      : type === "radio"
        ? group.map((item) => labelFor(item)).filter(Boolean)
        : [];
    optionalQuestions.push({
      fieldId, label, type, options,
      sensitive: true, optional: true,
    });
  });
  const buttons = [...document.querySelectorAll("button, input[type='submit'], input[type='button'], a[role='button']")]
    .filter((el) => visible(el) && !el.disabled)
    .map((el) => ({ element: el, label: clean(el.textContent || el.value || el.getAttribute("aria-label")) }))
    .filter((item) => item.label);
  const explicitSubmit = buttons.filter((item) =>
    /\b(submit|send application|complete application|send)\b/i.test(item.label) &&
    !/\b(next|continue|save|review|back|cancel|preview)\b/i.test(item.label));
  const finalButtons = explicitSubmit.length ? explicitSubmit : buttons.filter((item) =>
    item.element.type?.toLowerCase() === "submit" &&
    Boolean(item.element.closest("form")?.querySelector("input, textarea, select")) &&
    !/\b(next|continue|save|review|back|cancel|preview)\b/i.test(item.label));
  const continueButtons = buttons.filter((item) =>
    /^(next|continue|save and continue|review application)$/i.test(item.label));
  document.querySelectorAll("[data-clover-submit], [data-clover-continue]").forEach((el) => {
    delete el.dataset.cloverSubmit;
    delete el.dataset.cloverContinue;
  });
  if (finalButtons.length === 1) finalButtons[0].element.dataset.cloverSubmit = "true";
  if (continueButtons.length === 1) continueButtons[0].element.dataset.cloverContinue = "true";
  const receiptText = clean(
    [...document.querySelectorAll("h1, h2, [role='alert'], [role='status']")]
      .map((el) => el.textContent).join(" ") +
    " " + (document.querySelector("main")?.textContent || "")
  ).slice(0, 5000);
  const receiptFromUrl = /\b(thank.?you|confirmation|application.?submitted|success)\b/i
    .test(location.pathname + location.search);
  const receiptFromText = /\b(thank you for (?:applying|your application)|application (?:has been )?(?:received|submitted)|we(?:'ve| have) received your application|successfully submitted|application complete)\b/i
    .test(receiptText);
  return {
    url: location.href,
    title: clean(document.querySelector("h1")?.textContent || document.title),
    company: clean(document.querySelector("[data-company], .company, .company-name")?.textContent),
    postingText: clean((document.querySelector("main, article") || document.body).textContent).slice(0, 30000),
    fields,
    application: {
      fileFields,
      unresolvedRequired: unresolvedRequired.slice(0, 30),
      optionalQuestions: optionalQuestions.slice(0, 20),
      receipt: {
        detected: receiptFromUrl || receiptFromText,
        source: receiptFromUrl ? "url" : receiptFromText ? "page" : "",
      },
      submit: {
        available: finalButtons.length === 1,
        ambiguous: finalButtons.length > 1,
        label: finalButtons.length === 1 ? finalButtons[0].label : "",
      },
    },
    navigation: {
      available: continueButtons.length === 1,
      ambiguous: continueButtons.length > 1,
      label: continueButtons.length === 1 ? continueButtons[0].label : "",
    },
    listing: {},
    capturedAt: new Date().toISOString(),
  };
}
"""

FILL_SCRIPT = r"""
(suggestions) => {
  let filled = 0;
  let skipped = 0;
  const setValue = (el, value) => {
    if (el.tagName === "SELECT") {
      const option = [...el.options].find((item) =>
        String(item.textContent || "").trim().toLowerCase() === String(value).trim().toLowerCase() ||
        String(item.value || "").trim().toLowerCase() === String(value).trim().toLowerCase());
      if (!option) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set.call(el, option.value);
    } else if (el.isContentEditable) {
      el.textContent = value;
    } else {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value")?.set.call(el, value);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  };
  for (const suggestion of suggestions || []) {
    const el = [...document.querySelectorAll("[data-clover-field-id]")]
      .find((item) => item.dataset.cloverFieldId === suggestion.fieldId);
    if (!el || String(el.value || el.textContent || "").trim() || !setValue(el, String(suggestion.value || ""))) {
      skipped += 1;
      continue;
    }
    el.style.outline = "2px solid #5f9f7b";
    el.style.outlineOffset = "2px";
    filled += 1;
  }
  return { filled, skipped };
}
"""

COMBOBOX_IDS_SCRIPT = r"""
() => [...document.querySelectorAll("[data-clover-field-id][role='combobox']")]
  .map((element) => element.dataset.cloverFieldId)
"""

CHOICE_FILL_SCRIPT = r"""
(answers) => {
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
  const labelFor = (el) => {
    const explicit = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    return clean(explicit?.textContent || el.closest("label")?.textContent ||
      el.getAttribute("aria-label") || el.value);
  };
  const handled = [];
  let filled = 0;
  let skipped = 0;
  for (const answer of answers || []) {
    const controls = [...document.querySelectorAll("[data-clover-field-id]")]
      .filter((item) => item.dataset.cloverFieldId === answer.fieldId);
    const type = clean(controls[0]?.type);
    if (!["radio", "checkbox"].includes(type)) continue;
    handled.push(answer.fieldId);
    const wanted = clean(answer.value);
    if (type === "radio") {
      const control = controls.find((item) =>
        labelFor(item) === wanted || clean(item.value) === wanted);
      if (!control) {
        skipped += 1;
        continue;
      }
      control.click();
      filled += 1;
      continue;
    }
    const checked = ["yes", "true", "1", "checked"].includes(wanted);
    if (controls[0].checked !== checked) controls[0].click();
    filled += 1;
  }
  return { handled, filled, skipped };
}
"""


@dataclass
class _Command:
    action: Callable[[], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class ManagedBrowser:
    def __init__(self) -> None:
        self._commands: queue.Queue[_Command] = queue.Queue()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._opportunity_id = ""
        self._last_signature = ""
        self._skipped_optional_questions: set[str] = set()
        self._receipt_started_at = 0.0
        self._state: dict[str, Any] = {
            "running": False,
            "phase": "closed",
            "message": "No application is open.",
        }

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return copy.deepcopy(self._state)

    def _set(self, **values: Any) -> None:
        with self._state_lock:
            self._state.update(values)

    def _ensure_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="clover-browser", daemon=True)
        self._thread.start()

    def _call(self, action: Callable[[], Any], timeout: float = 120) -> Any:
        self._ensure_thread()
        command = _Command(action)
        self._commands.put(command)
        if not command.done.wait(timeout):
            raise TimeoutError("Clover's application browser took too long to respond.")
        if command.error:
            raise command.error
        return command.result

    def _run(self) -> None:
        while True:
            try:
                command = self._commands.get(timeout=0.75)
            except queue.Empty:
                try:
                    if self.status().get("phase") == "awaiting_receipt":
                        self._check_receipt()
                    else:
                        self._tick()
                except Exception as exc:  # noqa: BLE001
                    self._set(phase="error", message=f"Application runner paused: {exc}")
                continue
            try:
                command.result = command.action()
            except BaseException as exc:  # noqa: BLE001
                command.error = exc
                if self.status().get("running"):
                    self._set(
                        phase="error",
                        message=f"Application runner paused: {exc}",
                    )
            finally:
                command.done.set()

    def start(self, url: str, opportunity_id: str) -> dict[str, Any]:
        return self._call(lambda: self._start(url, opportunity_id))

    def _start(self, url: str, opportunity_id: str) -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            raise ValueError("A valid application URL is required.")
        if self._context is None:
            from playwright.sync_api import sync_playwright

            executable = _browser_executable()
            if executable is None:
                raise RuntimeError(
                    "Clover needs Google Chrome, Microsoft Edge, or Brave to run guided applications."
                )
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            profile = app_data_dir() / "application-browser"
            profile.mkdir(parents=True, exist_ok=True)
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(profile),
                    executable_path=executable,
                    headless=False,
                    no_viewport=True,
                )
            except Exception:
                self._playwright.stop()
                self._playwright = None
                raise
            self._context.on("close", self._browser_closed)
        self._page = self._context.pages[-1] if self._context.pages else self._context.new_page()
        self._opportunity_id = opportunity_id
        self._last_signature = ""
        self._skipped_optional_questions.clear()
        self._receipt_started_at = 0.0
        self._set(
            running=True,
            phase="loading",
            message="Opening the application in Clover's browser…",
            opportunityId=opportunity_id,
            url=url,
            unresolved=[],
            reviewFields=[],
            submission=None,
            timing={},
        )
        self._page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._page.bring_to_front()
        self._set(phase="watching", message="Juno is reading this application step.")
        return self.status()

    def prepare(self) -> dict[str, Any]:
        return self._call(self._prepare_now)

    def _prepare_now(self) -> dict[str, Any]:
        self._last_signature = ""
        self._set(phase="watching", message="Juno is checking the current application step.")
        self._tick(force=True)
        return self.status()

    def answer_questions(self, answers: Any) -> dict[str, Any]:
        return self._call(lambda: self._answer_questions(answers))

    def _answer_questions(self, answers: Any) -> dict[str, Any]:
        if not isinstance(answers, list) or not answers:
            raise ValueError("Answer at least one application question.")
        current = self._capture()
        questions = {
            str(item.get("fieldId") or ""): item
            for item in [
                *(current.get("application", {}).get("unresolvedRequired") or []),
                *(current.get("application", {}).get("optionalQuestions") or []),
            ]
            if item.get("fieldId")
            and str(item.get("label") or "") not in self._skipped_optional_questions
        }
        accepted: list[dict[str, str]] = []
        for raw in answers[:30]:
            if not isinstance(raw, dict):
                continue
            field_id = str(raw.get("fieldId") or "")
            value = str(raw.get("value") or "").strip()[:4_000]
            if field_id not in questions or not value:
                continue
            accepted.append({"fieldId": field_id, "value": value})
        if not accepted:
            raise ValueError("Those questions changed. Refresh the application and try again.")

        self._set(phase="preparing", message="Adding your answers to the application.")
        choice_result = self._page.evaluate(CHOICE_FILL_SCRIPT, accepted)
        handled = set(choice_result.get("handled") or [])
        regular = [item for item in accepted if item["fieldId"] not in handled]
        question_fields = [
            {
                "fieldId": field_id,
                "label": str(question.get("label") or ""),
                "type": str(question.get("type") or "text"),
                "currentValue": "",
            }
            for field_id, question in questions.items()
        ]
        fill_result = self._fill_suggestions(regular, question_fields)
        filled = int(choice_result.get("filled") or 0) + int(fill_result.get("filled") or 0)
        if not filled:
            raise ValueError("Clover could not match those answers to the application controls.")
        remember_user_answers(question_fields, accepted, DEFAULT_PERSON_ID)
        self._last_signature = ""
        self._page.wait_for_timeout(250)
        self._set(phase="watching", message="Juno is checking the application with your answers.")
        self._tick(force=True)
        return self.status()

    def skip_optional_questions(self, field_ids: Any) -> dict[str, Any]:
        return self._call(lambda: self._skip_optional_questions(field_ids))

    def _skip_optional_questions(self, field_ids: Any) -> dict[str, Any]:
        if not isinstance(field_ids, list) or not field_ids:
            raise ValueError("Choose at least one optional question to skip.")
        current = self._capture()
        optional = {
            str(item.get("fieldId") or ""): str(item.get("label") or "")
            for item in current.get("application", {}).get("optionalQuestions") or []
        }
        for field_id in field_ids[:20]:
            label = optional.get(str(field_id or ""))
            if label:
                self._skipped_optional_questions.add(label)
        self._last_signature = ""
        self._set(phase="watching", message="Juno is continuing without those optional answers.")
        self._tick(force=True)
        return self.status()

    def _hydrate_question_options(self, questions: list[dict[str, Any]]) -> None:
        combobox_ids = set(self._page.evaluate(COMBOBOX_IDS_SCRIPT))
        for question in questions:
            field_id = str(question.get("fieldId") or "")
            if question.get("options") or field_id not in combobox_ids:
                continue
            locator = self._page.locator(f"[data-clover-field-id={json.dumps(field_id)}]")
            try:
                locator.click(timeout=2_000)
                self._page.wait_for_timeout(400)
                controls = locator.get_attribute("aria-controls", timeout=1_000)
                if controls:
                    options = self._page.locator(
                        f"[id={json.dumps(controls)}] [role='option']"
                    ).all_inner_texts()
                    question["options"] = [
                        str(option).strip() for option in options[:30] if str(option).strip()
                    ]
                locator.press("Escape", timeout=1_000)
            except Exception:  # noqa: BLE001 - a free-text fallback remains available
                try:
                    locator.press("Escape", timeout=1_000)
                except Exception:
                    pass

    def _capture(self) -> dict[str, Any]:
        if self._page is None or self._page.is_closed():
            raise RuntimeError("The application browser is closed.")
        return self._page.evaluate(CAPTURE_SCRIPT)

    def _browser_closed(self, *_args: Any) -> None:
        self._context = None
        self._page = None
        self._set(running=False, phase="closed", message="The application browser was closed.")

    @staticmethod
    def _signature(raw: dict[str, Any]) -> str:
        contract = {
            "url": raw.get("url"),
            "fields": [
                (item.get("fieldId"), item.get("currentValue"))
                for item in raw.get("fields") or []
            ],
            "unresolved": raw.get("application", {}).get("unresolvedRequired"),
            "optionalQuestions": raw.get("application", {}).get("optionalQuestions"),
            "navigation": raw.get("navigation"),
            "submit": raw.get("application", {}).get("submit"),
        }
        return json.dumps(contract, sort_keys=True)

    def _fill_suggestions(
        self,
        suggestions: list[dict[str, Any]],
        fields: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        if not suggestions:
            return {"filled": 0, "skipped": 0}
        fields = fields or self._capture().get("fields") or []
        labels_by_id = {
            str(field.get("fieldId") or ""): str(field.get("label") or "")
            for field in fields
        }
        combobox_ids = set(self._page.evaluate(COMBOBOX_IDS_SCRIPT))
        regular = [
            item for item in suggestions if str(item.get("fieldId") or "") not in combobox_ids
        ]
        result = self._page.evaluate(FILL_SCRIPT, regular)
        filled = int(result.get("filled") or 0)
        skipped = int(result.get("skipped") or 0)
        for suggestion in suggestions:
            original_id = str(suggestion.get("fieldId") or "")
            if original_id not in combobox_ids:
                continue
            label = labels_by_id.get(original_id, "")
            current = self._capture()
            current_fields = [
                *(current.get("fields") or []),
                *(current.get("application", {}).get("unresolvedRequired") or []),
                *(current.get("application", {}).get("optionalQuestions") or []),
            ]
            current_comboboxes = set(self._page.evaluate(COMBOBOX_IDS_SCRIPT))
            field_id = next(
                (
                    str(field.get("fieldId") or "")
                    for field in current_fields
                    if str(field.get("label") or "") == label
                    and str(field.get("fieldId") or "") in current_comboboxes
                ),
                "",
            )
            if not field_id:
                skipped += 1
                continue
            locator = self._page.locator(f"[data-clover-field-id={json.dumps(field_id)}]")
            target = str(suggestion.get("value") or "").strip()
            try:
                if locator.count() != 1 or locator.input_value(timeout=1_000).strip():
                    skipped += 1
                    continue
                words = re.findall(r"[A-Za-z0-9]+", target)
                search_terms = [target]
                if len(words) > 1:
                    search_terms.extend(
                        [" ".join(words[:-1]), " ".join(words[:2]), words[0]]
                    )
                labels: list[str] = []
                options = None
                for search_term in dict.fromkeys(term for term in search_terms if term):
                    locator.click(timeout=3_000)
                    locator.press("ControlOrMeta+A", timeout=1_000)
                    locator.press("Backspace", timeout=1_000)
                    locator.type(search_term, delay=10, timeout=3_000)
                    self._page.wait_for_timeout(700)
                    controls = locator.get_attribute("aria-controls", timeout=1_000)
                    options = (
                        self._page.locator(
                            f"[id={json.dumps(controls)}] [role='option']"
                        )
                        if controls
                        else self._page.locator("[role='option']:visible")
                    )
                    labels = [option.strip() for option in options.all_inner_texts()[:100]]
                    if labels:
                        break
                normalized_target = re.sub(r"\W+", " ", target.casefold()).strip()

                def score(label: str) -> float:
                    normalized = re.sub(r"\W+", " ", label.casefold()).strip()
                    if normalized == normalized_target:
                        return 1.0
                    if "degree" in labels_by_id.get(original_id, "").casefold():
                        degree_levels = {
                            "associate",
                            "bachelor",
                            "master",
                            "doctor",
                            "phd",
                        }
                        target_level = next(
                            (level for level in degree_levels if level in normalized_target),
                            "",
                        )
                        option_level = next(
                            (level for level in degree_levels if level in normalized),
                            "",
                        )
                        if target_level and target_level == option_level:
                            return 1.0
                    if normalized_target in normalized or normalized in normalized_target:
                        return 0.9
                    return difflib.SequenceMatcher(None, normalized_target, normalized).ratio()

                ranked = sorted(
                    ((score(label), index) for index, label in enumerate(labels)),
                    reverse=True,
                )
                if options is None or not ranked or ranked[0][0] < 0.55:
                    locator.press("Escape", timeout=1_000)
                    locator.press("ControlOrMeta+A", timeout=1_000)
                    locator.press("Backspace", timeout=1_000)
                    skipped += 1
                    continue
                options.nth(ranked[0][1]).click(timeout=3_000)
                filled += 1
            except Exception:  # noqa: BLE001 - one custom control must not stop the form
                try:
                    locator.press("Escape", timeout=1_000)
                    locator.press("ControlOrMeta+A", timeout=1_000)
                    locator.press("Backspace", timeout=1_000)
                except Exception:
                    pass
                skipped += 1
        return {"filled": filled, "skipped": skipped}

    def _tick(self, force: bool = False) -> None:
        if not self.status().get("running") or self._page is None or self._page.is_closed():
            return
        if self.status().get("phase") not in {"watching", "loading", "needs_input"} and not force:
            return
        raw = self._capture()
        signature = self._signature(raw)
        if signature == self._last_signature and not force:
            return
        self._page.wait_for_timeout(400)
        settled = self._capture()
        if self._signature(settled) != signature:
            self._last_signature = ""
            self._set(
                phase="watching",
                message="Waiting for the application form to finish loading.",
                url=settled["url"],
            )
            return
        raw = settled
        signature = self._signature(raw)
        self._last_signature = signature
        self._set(phase="preparing", message="Juno is filling answers she can verify.", url=raw["url"])
        started = time.monotonic()
        uploaded = self._upload_resume(raw)
        if uploaded:
            self._page.wait_for_timeout(900)
            raw = self._capture()
        quick = quick_answers(raw.get("fields") or [], DEFAULT_PERSON_ID)
        quick_result = {"filled": 0, "skipped": 0}
        if quick:
            quick_result = self._fill_suggestions(quick, raw.get("fields") or [])
        remaining = self._capture()
        model_warning = ""
        try:
            suggestions = suggest_fields(
                remaining,
                person_id=DEFAULT_PERSON_ID,
                opportunity_id=self._opportunity_id or None,
            ).get("suggestions") or []
        except ValueError as exc:
            suggestions = []
            model_warning = str(exc)
        safe = [
            item
            for item in suggestions
            if float(item.get("confidence") or 0) >= 0.7
            and item.get("source") in {"resume", "memory", "opportunity", "inferred"}
        ]
        review = [item for item in suggestions if item not in safe]
        remember_answers(remaining.get("fields") or [], safe, DEFAULT_PERSON_ID)
        juno_result = {"filled": 0, "skipped": 0}
        if safe:
            juno_result = self._fill_suggestions(safe, remaining.get("fields") or [])
        self._page.wait_for_timeout(250)
        current = self._capture()
        if current["application"]["unresolvedRequired"] and quick:
            retry_quick = quick_answers(current.get("fields") or [], DEFAULT_PERSON_ID)
            if retry_quick:
                retry_result = self._fill_suggestions(
                    retry_quick,
                    current.get("fields") or [],
                )
                quick_result["filled"] += int(retry_result.get("filled") or 0)
                quick_result["skipped"] += int(retry_result.get("skipped") or 0)
                self._page.wait_for_timeout(250)
                current = self._capture()
        question_fields = [
            *current["application"]["unresolvedRequired"],
            *(current["application"].get("optionalQuestions") or []),
        ]
        remembered = cached_answers(question_fields, DEFAULT_PERSON_ID)
        if remembered:
            remembered_result = self._fill_suggestions(remembered, question_fields)
            quick_result["filled"] += int(remembered_result.get("filled") or 0)
            quick_result["skipped"] += int(remembered_result.get("skipped") or 0)
            self._page.wait_for_timeout(250)
            current = self._capture()
        self._last_signature = self._signature(current)
        timing = {
            "elapsedMs": int((time.monotonic() - started) * 1000),
            "quickFilled": int(quick_result.get("filled") or 0),
            "junoFilled": int(juno_result.get("filled") or 0),
            "resumeUploaded": uploaded,
            "modelWarning": model_warning,
        }
        unresolved = current["application"]["unresolvedRequired"]
        optional = [
            item
            for item in current["application"].get("optionalQuestions") or []
            if str(item.get("label") or "") not in self._skipped_optional_questions
        ]
        questions = [*unresolved, *optional]
        if questions:
            self._hydrate_question_options(questions)
            self._set(
                phase="needs_input",
                message=(
                    "Juno filled the verified basics, but could not prepare the remaining questions. "
                    "Answer the remaining questions here in Clover."
                    if model_warning
                    else (
                        "Juno needs your answers below before she can continue."
                        if unresolved
                        else "Juno filled everything she can. Answer or skip these optional personal questions."
                    )
                ),
                unresolved=questions,
                reviewFields=review,
                url=current["url"],
                timing=timing,
            )
            return
        submit = current["application"]["submit"]
        if submit["available"] or submit["ambiguous"]:
            message = (
                "The application is ready. Review it first if you want, or continue to submission approval."
                if submit["available"]
                else "More than one possible submit button was found. Please review the page."
            )
            self._set(
                phase="ready_to_submit",
                message=message,
                unresolved=[],
                reviewFields=review,
                url=current["url"],
                timing=timing,
            )
            return
        navigation = current.get("navigation") or {}
        if navigation.get("available"):
            self._set(
                phase="navigating",
                message=f"Continuing with {navigation['label']}…",
                timing=timing,
            )
            before_navigation = self._signature(current)
            self._page.locator("[data-clover-continue='true']").click()
            self._page.wait_for_timeout(700)
            advanced = self._capture()
            if self._signature(advanced) == before_navigation:
                self._last_signature = before_navigation
                self._set(
                    phase="needs_input",
                    message="Continue did not advance the page. Please review this step in Chrome.",
                    url=advanced["url"],
                    timing=timing,
                )
                return
            self._last_signature = ""
            self._set(
                phase="watching",
                message="Juno is reading the next application step.",
                url=advanced["url"],
                timing=timing,
            )
            return
        self._set(
            phase="needs_input",
            message="Juno filled what she could. Review the page in Chrome to continue.",
            unresolved=[],
            reviewFields=review,
            url=current["url"],
            timing=timing,
        )

    def _upload_resume(self, raw: dict[str, Any]) -> bool:
        candidates = [
            item
            for item in raw.get("application", {}).get("fileFields") or []
            if not item.get("hasFile") and "cover" not in str(item.get("label") or "").lower()
        ]
        preferred = next(
            (item for item in candidates if any(word in item["label"].lower() for word in ("resume", "résumé", "cv"))),
            candidates[0] if len(candidates) == 1 else None,
        )
        if preferred is None:
            return False
        stored = document_file(kind="resume", person_id=DEFAULT_PERSON_ID)
        if stored is None:
            return False
        self._page.locator(
            f"[data-clover-file-id={json.dumps(preferred['fieldId'])}]"
        ).set_input_files(
            {
                "name": stored["filename"],
                "mimeType": stored["mimeType"],
                "buffer": stored["data"],
            }
        )
        return True

    def request_submission(self) -> dict[str, Any]:
        return self._call(self._request_submission)

    def _request_submission(self) -> dict[str, Any]:
        result = request_application_submission(
            self._capture(),
            person_id=DEFAULT_PERSON_ID,
            connection_id=MANAGED_CONNECTION_ID,
            opportunity_id=self._opportunity_id or None,
        )
        self._set(submission=result, phase="awaiting_approval", message=result["explanation"])
        return result

    def submit(self, action_id: str) -> dict[str, Any]:
        return self._call(lambda: self._submit(action_id))

    def _submit(self, action_id: str) -> dict[str, Any]:
        approval = approve_application_submission(
            action_id,
            self._capture(),
            person_id=DEFAULT_PERSON_ID,
            connection_id=MANAGED_CONNECTION_ID,
        )
        control = self._page.locator("[data-clover-submit='true']")
        if control.count() != 1:
            complete_application_submission(action_id, succeeded=False)
            raise ValueError("The final submit button changed. Review the application again.")
        control.click()
        complete_application_submission(action_id, succeeded=True)
        self._set(
            phase="awaiting_receipt",
            message="Juno is confirming that the employer received the application.",
            submission={**(self.status().get("submission") or {}), **approval},
        )
        self._receipt_started_at = time.monotonic()
        self._page.wait_for_timeout(800)
        self._check_receipt()
        return self.status()

    def cancel_submission(self, action_id: str) -> dict[str, Any]:
        return self._call(lambda: self._cancel_submission(action_id))

    def _cancel_submission(self, action_id: str) -> dict[str, Any]:
        result = cancel_application_submission(action_id, person_id=DEFAULT_PERSON_ID)
        self._set(phase="ready_to_submit", message="Submission cancelled. Nothing was sent.", submission=None)
        return result

    def confirm_receipt(self, action_id: str) -> dict[str, Any]:
        return self._call(lambda: self._confirm_receipt(action_id))

    def _check_receipt(self) -> None:
        state = self.status()
        action_id = str((state.get("submission") or {}).get("actionId") or "")
        if state.get("phase") != "awaiting_receipt" or not action_id:
            return
        current = None
        try:
            current = self._capture()
            self._set(url=current["url"])
        except Exception:  # noqa: BLE001 - submission completion does not depend on an open tab
            pass
        detected = bool(
            current
            and current.get("application", {}).get("receipt", {}).get("detected")
        )
        if not detected and time.monotonic() - self._receipt_started_at < 8:
            return
        result = (
            confirm_application_received(
                action_id,
                current,
                person_id=DEFAULT_PERSON_ID,
                connection_id=MANAGED_CONNECTION_ID,
                confirmed_by_user=False,
            )
            if detected
            else record_application_sent(action_id, person_id=DEFAULT_PERSON_ID)
        )
        self._set(
            phase="completed",
            message=(
                "Application received and marked as applied."
                if detected
                else "Application submitted and marked as applied."
            ),
            submission=None,
            receipt=result,
        )

    def _confirm_receipt(self, action_id: str) -> dict[str, Any]:
        result = confirm_application_received(
            action_id,
            self._capture(),
            person_id=DEFAULT_PERSON_ID,
            connection_id=MANAGED_CONNECTION_ID,
        )
        self._set(phase="completed", message="Application marked as applied.", submission=None)
        return result

    def close(self) -> dict[str, Any]:
        return self._call(self._close)

    def _close(self) -> dict[str, Any]:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        self._set(running=False, phase="closed", message="No application is open.")
        return self.status()


managed_browser = ManagedBrowser()
