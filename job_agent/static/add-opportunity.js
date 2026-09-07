// Adding a role. The default path is handing it to Juno and letting her do the
// reading; typing it in yourself is the fallback, not the main event.

import { api, autoGrow, el, junoMark } from "./lib.js";

export function openAddSheet(nav) {
  const overlay = el("div", { class: "overlay" });
  const close = () => overlay.remove();

  const paste = el("textarea", {
    class: "field-input",
    rows: 8,
    placeholder: "Paste the job link, or the whole description…",
  });
  autoGrow(paste);

  const hand = el("button", {
    class: "btn btn-primary btn-block",
    type: "submit",
    text: "Give it to Juno",
    disabled: true,
  });
  paste.addEventListener("input", () => {
    hand.disabled = !paste.value.trim();
  });

  const manual = el("div", { class: "stack stack-3", style: "display: none" });
  const role = el("input", { type: "text", placeholder: "Role title" });
  const company = el("input", { type: "text", placeholder: "Company" });
  const url = el("input", { type: "url", placeholder: "Link (optional)" });
  const saveError = el("div", { class: "small", style: "color: var(--amber)" });
  manual.append(
    el("div", { class: "field" }, el("label", { text: "Role" }), role),
    el("div", { class: "field" }, el("label", { text: "Company" }), company),
    el("div", { class: "field" }, el("label", { text: "Link" }), url),
    el("button", {
      class: "btn btn-block",
      type: "button",
      text: "Save it",
      onClick: async () => {
        if (!role.value.trim()) {
          saveError.textContent = "A role title is enough to start.";
          return;
        }
        try {
          const result = await api.post("/api/opportunities", {
            role: role.value.trim(),
            company: company.value.trim(),
            sourceUrl: url.value.trim(),
            jobDescription: paste.value.trim(),
            stage: "interested",
          });
          close();
          nav.openOpportunity(result.id);
        } catch (problem) {
          saveError.textContent = problem.message;
        }
      },
    }),
    saveError
  );

  const toggle = el("button", {
    class: "btn btn-quiet btn-block",
    type: "button",
    text: "I'd rather type it in myself",
    onClick: () => {
      const showing = manual.style.display !== "none";
      manual.style.display = showing ? "none" : "flex";
      toggle.textContent = showing ? "I'd rather type it in myself" : "Hide the fields";
      if (!showing) role.focus();
    },
  });

  const form = el(
    "form",
    {
      class: "stack stack-3",
      onSubmit: (event) => {
        event.preventDefault();
        const text = paste.value.trim();
        if (!text) return;
        close();
        nav.askJuno(
          `Here's a role I'm considering. Take a look and tell me honestly what you think of the fit, ` +
            `then save it with your reasoning.\n\n${text}`
        );
      },
    },
    paste,
    hand
  );

  const drawer = el(
    "div",
    { class: "drawer stack stack-4" },
    el(
      "div",
      { class: "row", style: "align-items: flex-start; gap: 12px" },
      junoMark(true),
      el(
        "div",
        { class: "stack", style: "gap: 3px" },
        el("h2", { text: "Add a role" }),
        el("div", { class: "small muted", text: "I'll read it and tell you what I actually think." })
      )
    ),
    form,
    el("hr", { class: "divider" }),
    toggle,
    manual,
    el("button", { class: "btn btn-quiet btn-block", type: "button", text: "Never mind", onClick: close })
  );

  overlay.append(drawer);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape") close();
    },
    { once: true }
  );

  document.body.append(overlay);
  requestAnimationFrame(() => paste.focus());
}
