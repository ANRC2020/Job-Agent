// Clover's shell: four places to be, one conversation running through all of them.

import { openAddSheet } from "./add-opportunity.js";
import { api, clear, cloverMark, el, icon, junoMark } from "./lib.js";
import { renderHome } from "./view-home.js";
import { renderJuno } from "./view-juno.js";
import { renderOnboarding } from "./view-onboarding.js";
import { renderOpportunities } from "./view-opportunities.js";
import { renderOpportunity } from "./view-opportunity.js";
import { renderProfile } from "./view-profile.js";
import { openSettings } from "./view-settings.js";

const NAV = [
  { id: "home", label: "Home", icon: "home" },
  { id: "juno", label: "Juno", icon: "juno" },
  { id: "opportunities", label: "Opportunities", icon: "briefcase" },
  { id: "profile", label: "Profile", icon: "person" },
];

const shell = document.getElementById("app");
const stage = el("div", { class: "main" });
const view = el("div", { class: "view" });
const notice = el("div", { style: "display: none" });
const applicationNotice = el("div", {
  class: "application-modal-host",
  style: "display: none",
});
const navItems = new Map();
const applicationDrafts = new Map();
let renderedRunnerKey = "";
let openCount = 0;
let handoff = null;

const nav = {
  go(route) {
    const target = `#/${route}`;
    if (window.location.hash === target) render();
    else window.location.hash = target;
  },
  openOpportunity(id, flash) {
    handoff = flash ? { flash } : null;
    const target = `#/opportunity/${id}`;
    if (window.location.hash === target) render();
    else window.location.hash = target;
  },
  askJuno(prompt) {
    handoff = { prompt };
    if (window.location.hash === "#/juno") render();
    else window.location.hash = "#/juno";
  },
  addOpportunity() {
    openAddSheet(nav);
  },
  refreshCounts,
};

function navButton(item) {
  const count = el("span", { class: "nav-count" });
  const button = el(
    "button",
    { class: "nav-item", type: "button", onClick: () => nav.go(item.id) },
    icon(item.icon),
    el("span", { text: item.label }),
    count
  );
  navItems.set(item.id, { button, count });
  return button;
}

function buildShell() {
  shell.className = "app";
  const sidebar = el(
    "div",
    { class: "sidebar" },
    el("div", { class: "brand" }, cloverMark(24), el("span", { class: "brand-name", text: "Clover" })),
    ...NAV.map(navButton),
    el("div", { class: "sidebar-spacer" }),
    el(
      "button",
      { class: "nav-item", type: "button", onClick: openSettings },
      icon("gear"),
      el("span", { text: "Settings" })
    )
  );
  clear(stage).append(notice, applicationNotice, view);
  clear(shell).append(sidebar, stage);
}

function setActive(route) {
  for (const [id, entry] of navItems) {
    entry.button.classList.toggle("is-active", id === route);
  }
}

async function refreshCounts() {
  try {
    const data = await api.get("/api/opportunities");
    openCount = data.opportunities.filter((item) => item.stage !== "closed").length;
  } catch {
    openCount = 0;
  }
  const entry = navItems.get("opportunities");
  if (entry) entry.count.textContent = openCount ? String(openCount) : "";
}

// --- is Juno awake yet -------------------------------------------------

let attempts = 0;
let watching = false;

function publishReadiness(state) {
  const ready = Boolean(state?.ready);
  document.documentElement.dataset.junoReady = ready ? "true" : "false";
  window.dispatchEvent(new CustomEvent("juno-readiness", { detail: state || { ready: false } }));
}

function showNotice(state) {
  clear(notice);
  // A block slot, so the banner inside spans the width instead of shrinking to
  // fit its own text as a flex item would.
  notice.style.display = "block";
  const actions = el("div", { class: "row" });
  if (state.recovery) {
    const button = el("button", {
      class: "btn",
      type: "button",
      text: state.recovery.label,
      onClick: async () => {
        button.disabled = true;
        button.textContent = "Working on it…";
        try {
          await api.post(`/api/engine/${state.recovery.action}`, {});
        } finally {
          attempts = 0;
          button.disabled = false;
          watchReadiness();
        }
      },
    });
    actions.append(button);
  }
  const progress = state.download;
  const percentage = Number.isFinite(Number(progress?.percent))
    ? Math.max(0, Math.min(100, Number(progress.percent)))
    : null;
  const meter = progress?.active
    ? el(
        "div",
        { class: "model-download stack", style: "gap: 5px" },
        el(
          "div",
          {
            class: `model-download-track${percentage === null ? " is-indeterminate" : ""}`,
            role: "progressbar",
            "aria-label": "Downloading Juno",
            "aria-valuemin": "0",
            "aria-valuemax": "100",
            "aria-valuenow": percentage === null ? null : String(Math.round(percentage)),
          },
          el("div", {
            class: "model-download-fill",
            style: percentage === null ? null : `width: ${percentage}%`,
          })
        ),
        el("div", {
          class: "small muted",
          text: percentage === null
            ? (progress.detail || "Preparing the download…")
            : `${Math.round(percentage)}% downloaded`,
        })
      )
    : null;
  notice.append(
    el(
      "div",
      { class: "notice" },
      icon("clock", "icon-sm"),
      el(
        "div",
        { class: "stack", style: "gap: 2px" },
        el("strong", { text: state.headline }),
        state.detail ? el("div", { class: "small muted", text: state.detail }) : null,
        meter
      ),
      el("div", { class: "spacer" }),
      actions
    )
  );
}

async function watchReadiness() {
  if (watching) return;
  watching = true;
  while (true) {
    let state;
    try {
      state = await api.get(`/api/readiness?attempts=${attempts}`);
    } catch {
      state = null;
    }
    if (state?.ready) {
      publishReadiness(state);
      notice.style.display = "none";
      clear(notice);
      watching = false;
      return;
    }
    if (state) {
      publishReadiness(state);
      showNotice(state);
    } else {
      publishReadiness({ ready: false });
    }
    attempts += 1;
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
}

function applicationQuestionForm(state, refresh) {
  const questions = (state.unresolved || []).filter((item) => item.fieldId);
  if (!questions.length) return null;
  const controls = new Map();
  const feedback = el("div", { class: "small warning" });
  const form = el("form", {
    class: "stack stack-3 application-questions",
    onSubmit: async (event) => {
      event.preventDefault();
      const answers = [...controls.entries()]
        .map(([fieldId, control]) => ({
          fieldId,
          value: String(control.value || "").trim(),
        }))
        .filter((item) => item.value);
      if (!answers.length) {
        feedback.textContent = "Answer at least one question to continue.";
        return;
      }
      const button = form.querySelector("button[type='submit']");
      button.disabled = true;
      button.textContent = "Adding your answers…";
      try {
        await api.post("/api/browser/answers", { answers });
        for (const answer of answers) applicationDrafts.delete(answer.fieldId);
        refresh();
      } catch (problem) {
        feedback.textContent = problem.message;
        button.disabled = false;
        button.textContent = "Continue application";
      }
    },
  });
  form.append(
    el("div", { class: "eyebrow", text: "Juno needs your answer" }),
    el("div", {
      class: "small muted",
      text: "Answer here and Juno will add it to the application. Nothing is submitted without your approval.",
    })
  );
  for (const [index, question] of questions.entries()) {
    const controlId = `global-application-question-${index}`;
    const options = question.options || [];
    let control;
    if (options.length) {
      control = el(
        "select",
        {
          id: controlId,
          class: "field-input",
          onChange: (event) => applicationDrafts.set(question.fieldId, event.target.value),
        },
        el("option", { value: "", text: "Choose an answer…" }),
        options.map((option) =>
          el("option", {
            value: option,
            text: option,
            selected: applicationDrafts.get(question.fieldId) === option,
          })
        )
      );
    } else {
      control = el(question.type === "textarea" ? "textarea" : "input", {
        id: controlId,
        class: "field-input",
        type: question.type === "number" ? "number" : "text",
        rows: question.type === "textarea" ? "3" : null,
        onInput: (event) => applicationDrafts.set(question.fieldId, event.target.value),
      });
      control.value = applicationDrafts.get(question.fieldId) || "";
    }
    controls.set(question.fieldId, control);
    form.append(
      el(
        "label",
        { class: "stack stack-2 application-question", for: controlId },
        el("strong", {
          class: question.sensitive ? "warning" : "",
          text: `${question.label}${question.optional ? " (optional)" : ""}`,
        }),
        control,
        question.sensitive
          ? el("span", { class: "small warning", text: "Only you can answer this." })
          : null
      )
    );
  }
  form.append(
    feedback,
    el(
      "div",
      { class: "actions" },
      el("button", {
        class: "btn btn-primary",
        type: "submit",
        text: "Continue application",
      }),
      el("button", {
        class: "btn",
        type: "button",
        text: "Open application details",
        onClick: () => nav.openOpportunity(state.opportunityId),
      }),
      questions.some((question) => question.optional)
        ? el("button", {
            class: "btn",
            type: "button",
            text: "Skip optional questions",
            onClick: async () => {
              await api.post("/api/browser/questions/skip", {
                fieldIds: questions
                  .filter((question) => question.optional)
                  .map((question) => question.fieldId),
              });
              refresh();
            },
          })
        : null
    )
  );
  return form;
}

async function refreshApplicationNotice() {
  try {
    const state = await api.get("/api/browser/status");
    const runnerKey = JSON.stringify([
      state.opportunityId,
      state.phase,
      (state.unresolved || []).map((item) => [
        item.fieldId,
        item.options,
      ]),
      state.submission?.actionId || "",
    ]);
    if (
      !state.running ||
      ["closed", "completed", "loading", "watching", "preparing", "navigating"].includes(state.phase)
    ) {
      applicationNotice.style.display = "none";
      clear(applicationNotice);
      renderedRunnerKey = "";
      return;
    }
    if (runnerKey === renderedRunnerKey && applicationNotice.style.display !== "none") {
      return;
    }
    const refresh = async (path, payload = {}) => {
      await api.post(path, payload);
      refreshApplicationNotice();
    };
    const questionForm =
      state.phase === "needs_input"
        ? applicationQuestionForm(state, refreshApplicationNotice)
        : null;
    const actions = el("div", { class: "actions" });
    if (state.phase === "ready_to_submit") {
      actions.append(
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "Continue to submission approval",
          onClick: () => refresh("/api/browser/submission/request"),
        }),
        el("button", {
          class: "btn",
          type: "button",
          text: "Review application first",
          onClick: () => nav.openOpportunity(state.opportunityId),
        })
      );
    }
    const actionId = state.submission?.actionId;
    if (state.phase === "awaiting_approval" && actionId) {
      actions.append(
        el("button", {
          class: "btn btn-primary",
          type: "button",
          text: "Submit application now",
          onClick: () => refresh("/api/browser/submission/approve", { actionId }),
        }),
        el("button", {
          class: "btn",
          type: "button",
          text: "Cancel",
          onClick: () => refresh("/api/browser/submission/cancel", { actionId }),
        })
      );
    }
    if (!questionForm && !actions.childElementCount) {
      actions.append(
        el("button", {
          class: "btn",
          type: "button",
          text: "Open application details",
          onClick: () => nav.openOpportunity(state.opportunityId),
        })
      );
    }
    clear(applicationNotice).append(
      el(
        "div",
        { class: "application-modal stack stack-4", role: "dialog", "aria-modal": "true" },
        el(
          "div",
          { class: "row", style: "align-items: flex-start" },
          junoMark(true),
          el(
            "div",
            { class: "stack", style: "gap: 2px" },
            el("strong", { text: "Juno needs you" }),
            el("div", {
              class: "small muted",
              text: "I paused the application so we can handle this together.",
            })
          )
        ),
        questionForm ||
          el("div", { class: "eyebrow", text: "Application runner" }),
        questionForm ? null : el("strong", { text: state.message }),
        questionForm ? null : actions
      )
    );
    renderedRunnerKey = runnerKey;
    applicationNotice.style.display = "flex";
  } catch {
    applicationNotice.style.display = "none";
    renderedRunnerKey = "";
  }
}

function watchApplicationRunner() {
  refreshApplicationNotice();
  window.setInterval(refreshApplicationNotice, 1500);
}

// --- routing -----------------------------------------------------------

function parseRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [name, id] = raw.split("/");
  return { name: name || "home", id: id || "" };
}

async function render() {
  const { name, id } = parseRoute();
  const context = handoff || {};
  handoff = null;
  setActive(name === "opportunity" ? "opportunities" : name);
  try {
    if (name === "juno") await renderJuno(view, nav, context);
    else if (name === "opportunities") await renderOpportunities(view, nav, context);
    else if (name === "opportunity" && id) await renderOpportunity(view, nav, { id, ...context });
    else if (name === "profile") await renderProfile(view, nav);
    else await renderHome(view, nav);
  } catch (problem) {
    clear(view).append(
      el(
        "div",
        { class: "page" },
        el(
          "div",
          { class: "page-inner stack stack-3" },
          el("h1", { text: "That didn't load" }),
          el("div", { class: "lead", text: problem.message }),
          el("button", { class: "btn", type: "button", text: "Try again", onClick: render })
        )
      )
    );
  }
}

async function boot() {
  const bootstrap = await api.get("/api/bootstrap");
  publishReadiness(bootstrap.readiness);
  if (!bootstrap.onboarding.complete) {
    shell.className = "";
    renderOnboarding(shell, {
      onDone: () => {
        window.location.hash = "#/home";
        start();
      },
    });
    return;
  }
  start();
}

function start() {
  buildShell();
  window.addEventListener("hashchange", render);
  render();
  refreshCounts();
  watchReadiness();
  watchApplicationRunner();
}

boot().catch((problem) => {
  shell.className = "";
  clear(shell).append(
    el(
      "div",
      { class: "page-inner stack stack-3" },
      el("h1", { text: "Clover couldn't start" }),
      el("div", { class: "lead", text: problem.message })
    )
  );
});
