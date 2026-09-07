// Every opportunity, grouped simply. Lightweight on purpose — this is a shelf,
// not a pipeline.

import { junoNote, opportunityCard } from "./components.js";
import { api, clear, el, icon } from "./lib.js";

const LANE_EMPTY = {
  all: [
    "Nothing here yet. When you bring me a role — a link or a pasted description — I'll read it and tell you what I think of the fit.",
    "Everything about it then lives in one place, so you're not tracking it in your head.",
  ],
  suggested: ["Nothing waiting on a decision from you right now."],
  interested: ["Nothing saved yet. Roles worth your time land here."],
  applying: ["No applications in progress. When you start one, the drafts and notes stay with the role."],
  interviewing: ["No interviews in motion. When one starts, we'll prepare for it together here."],
  closed: [
    "Nothing closed out yet. When something ends — their decision or yours — it comes here rather than disappearing.",
  ],
};

export async function renderOpportunities(root, nav, { lane = "all" } = {}) {
  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner stack stack-4" });
  page.append(inner);
  clear(root).append(page);

  const data = await api.get("/api/opportunities");
  let active = lane;

  const head = el(
    "div",
    { class: "row" },
    el("h1", { text: "Opportunities" }),
    el("div", { class: "spacer" }),
    el(
      "button",
      { class: "btn", type: "button", onClick: nav.addOpportunity },
      icon("plus", "icon-sm"),
      "Add a role"
    )
  );

  const tabs = el("div", { class: "tabs" });
  const list = el("div", { class: "stack stack-3" });
  inner.append(head, tabs, list);

  function drawTabs() {
    clear(tabs);
    const options = [{ id: "all", label: "All", count: data.total }, ...data.lanes];
    const withRoles = options.filter((option) => option.id !== "all" && option.count > 0);
    // A filter bar holding a single "All" tab is a control that does nothing.
    tabs.style.display = withRoles.length > 1 ? "" : "none";
    for (const option of options) {
      if (option.id !== "all" && option.count === 0 && active !== option.id) continue;
      const tab = el(
        "button",
        {
          class: `tab${option.id === active ? " is-active" : ""}`,
          type: "button",
          onClick: () => {
            active = option.id;
            drawTabs();
            drawList();
          },
        },
        el("span", { text: option.label }),
        option.count ? el("span", { class: "tab-count", text: String(option.count) }) : null
      );
      tabs.append(tab);
    }
  }

  function drawList() {
    clear(list);
    const items =
      active === "all"
        ? data.opportunities
        : data.opportunities.filter((item) => item.lane === active);
    if (!items.length) {
      list.append(
        junoNote(
          LANE_EMPTY[data.total === 0 ? "all" : active] || LANE_EMPTY.all,
          data.total === 0
            ? [
                el("button", {
                  class: "btn btn-primary",
                  type: "button",
                  text: "Add a role",
                  onClick: nav.addOpportunity,
                }),
                el("button", {
                  class: "btn",
                  type: "button",
                  text: "Ask Juno to help me look",
                  onClick: () =>
                    nav.askJuno(
                      "I'm not sure what to look for. Based on what you know about me, what kinds of roles should I be considering?"
                    ),
                }),
              ]
            : []
        )
      );
      return;
    }
    for (const item of items) {
      list.append(opportunityCard(item, { onOpen: nav.openOpportunity }));
    }
  }

  drawTabs();
  drawList();
}
