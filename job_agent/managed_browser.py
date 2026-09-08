"""Visible, constrained browser automation for job applications."""

from __future__ import annotations

import copy
import json
import os
import platform
import queue
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
    request_application_submission,
    sanitize_page,
    suggest_fields,
)
from job_agent.application_answers import quick_answers, remember_answers
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
  const currentValue = (el) => clean(el.value ?? el.textContent);
  const sensitive = (el, label) => /\b(password|passcode|credit|debit|card number|cvv|cvc|bank|routing|social security|ssn|national id|government id|passport|driver.?s license|race|ethnicity|gender|sex|sexual orientation|disability|veteran|religion|date of birth|birth date|medical|health)\b/i
    .test(`${label} ${el.name || ""} ${el.autocomplete || ""}`);
  const fields = [];
  [...document.querySelectorAll("input, textarea, select, [contenteditable='true']")].forEach((el, index) => {
    const type = el.tagName === "SELECT" ? "select" :
      el.tagName === "TEXTAREA" ? "textarea" :
      el.isContentEditable ? "textarea" : clean(el.type || "text").toLowerCase();
    const label = labelFor(el);
    if (!visible(el) || el.disabled || el.readOnly ||
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
  for (const el of document.querySelectorAll("input[required], textarea[required], select[required], [aria-required='true']")) {
    const type = clean(el.type || el.tagName).toLowerCase();
    if (!visible(el) || el.disabled || ["hidden", "submit", "button", "image"].includes(type)) continue;
    let complete = Boolean(currentValue(el));
    if (type === "checkbox") complete = el.checked;
    if (type === "radio") {
      complete = el.name
        ? [...document.querySelectorAll(`input[type='radio'][name="${CSS.escape(el.name)}"]`)].some((item) => item.checked)
        : el.checked;
    }
    if (type === "file") complete = Boolean(el.files?.length);
    if (!complete) {
      const label = labelFor(el) || "Required field";
      unresolvedRequired.push({ label, type, sensitive: sensitive(el, label) });
    }
  }
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
  return {
    url: location.href,
    title: clean(document.querySelector("h1")?.textContent || document.title),
    company: clean(document.querySelector("[data-company], .company, .company-name")?.textContent),
    postingText: clean((document.querySelector("main, article") || document.body).textContent).slice(0, 30000),
    fields,
    application: {
      fileFields,
      unresolvedRequired: unresolvedRequired.slice(0, 30),
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
                    self._tick()
                except Exception as exc:  # noqa: BLE001
                    self._set(phase="error", message=f"Application runner paused: {exc}")
                continue
            try:
                command.result = command.action()
            except BaseException as exc:  # noqa: BLE001
                command.error = exc
            finally:
                command.done.set()

    def start(self, url: str, opportunity_id: str) -> dict[str, Any]:
        return self._call(lambda: self._start(url, opportunity_id))

    def _start(self, url: str, opportunity_id: str) -> dict[str, Any]:
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
        self._set(
            running=True,
            phase="loading",
            message="Opening the application in Clover's browser…",
            opportunityId=opportunity_id,
            url=url,
            unresolved=[],
            reviewFields=[],
            submission=None,
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
            "navigation": raw.get("navigation"),
            "submit": raw.get("application", {}).get("submit"),
        }
        return json.dumps(contract, sort_keys=True)

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
            quick_result = self._page.evaluate(FILL_SCRIPT, quick)
        remaining = self._capture()
        suggestions = suggest_fields(
            remaining,
            person_id=DEFAULT_PERSON_ID,
            opportunity_id=self._opportunity_id or None,
        ).get("suggestions") or []
        safe = [
            item
            for item in suggestions
            if float(item.get("confidence") or 0) >= 0.85
            and item.get("source") in {"resume", "memory"}
        ]
        review = [item for item in suggestions if item not in safe]
        remember_answers(remaining.get("fields") or [], safe, DEFAULT_PERSON_ID)
        juno_result = {"filled": 0, "skipped": 0}
        if safe:
            juno_result = self._page.evaluate(FILL_SCRIPT, safe)
        self._page.wait_for_timeout(250)
        current = self._capture()
        if current["application"]["unresolvedRequired"] and quick:
            retry_quick = quick_answers(current.get("fields") or [], DEFAULT_PERSON_ID)
            if retry_quick:
                retry_result = self._page.evaluate(FILL_SCRIPT, retry_quick)
                quick_result["filled"] += int(retry_result.get("filled") or 0)
                quick_result["skipped"] += int(retry_result.get("skipped") or 0)
                self._page.wait_for_timeout(250)
                current = self._capture()
        self._last_signature = self._signature(current)
        timing = {
            "elapsedMs": int((time.monotonic() - started) * 1000),
            "quickFilled": int(quick_result.get("filled") or 0),
            "junoFilled": int(juno_result.get("filled") or 0),
            "resumeUploaded": uploaded,
        }
        unresolved = current["application"]["unresolvedRequired"]
        if unresolved:
            self._set(
                phase="needs_input",
                message="Please complete the highlighted or sensitive questions in Chrome. Juno will continue automatically.",
                unresolved=unresolved,
                reviewFields=review,
                url=current["url"],
                timing=timing,
            )
            return
        submit = current["application"]["submit"]
        if submit["available"] or submit["ambiguous"]:
            message = (
                "The final application is ready for your review."
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
            message="Confirm once the employer shows a success or receipt page.",
            submission={**(self.status().get("submission") or {}), **approval},
        )
        return self.status()

    def cancel_submission(self, action_id: str) -> dict[str, Any]:
        return self._call(lambda: self._cancel_submission(action_id))

    def _cancel_submission(self, action_id: str) -> dict[str, Any]:
        result = cancel_application_submission(action_id, person_id=DEFAULT_PERSON_ID)
        self._set(phase="ready_to_submit", message="Submission cancelled. Nothing was sent.", submission=None)
        return result

    def confirm_receipt(self, action_id: str) -> dict[str, Any]:
        return self._call(lambda: self._confirm_receipt(action_id))

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
