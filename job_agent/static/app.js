// Clover's shell: four places to be, one conversation running through all of them.

import { openAddSheet } from "./add-opportunity.js";
import { api, clear, cloverMark, el, icon } from "./lib.js";
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
const navItems = new Map();
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
  clear(stage).append(notice, view);
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
