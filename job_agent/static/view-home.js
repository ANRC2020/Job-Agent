// Home: where things stand, one honest observation, one thing worth doing.
// Deliberately not a dashboard.

import { junoNote, opportunityCard, progressList } from "./components.js";
import { api, clear, el, icon } from "./lib.js";

export async function renderHome(root, nav) {
  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner stack stack-5" });
  page.append(inner);
  clear(root).append(page);

  const data = await api.get("/api/home");

  function runAction(action) {
    if (!action) return;
    if (action.kind === "opportunity") nav.openOpportunity(action.id);
    else if (action.kind === "juno") nav.askJuno(action.prompt);
    else if (action.kind === "route") nav.go(action.route);
    else if (action.kind === "add") nav.addOpportunity();
  }

  // Home should never ask for the same thing twice on one screen.
  const offered = new Set();
  const target = (action) => `${action.kind}:${action.id || action.route || ""}`;

  function actionButton(action, primary = false) {
    if (!action) return null;
    offered.add(target(action));
    return el("button", {
      class: primary ? "btn btn-primary" : "btn",
      type: "button",
      text: action.label,
      onClick: () => runAction(action),
    });
  }

  // Greeting
  inner.append(
    el(
      "div",
      { class: "stack stack-2" },
      el("h1", { class: "greeting", text: data.greeting }),
      data.totalOpportunities
        ? el("div", { class: "lead", text: laneLine(data.lanes) })
        : el("div", { class: "lead", text: "Nothing on your plate yet." })
    )
  );

  // Juno's observation
  if (data.observation) {
    inner.append(
      junoNote(
        [data.observation.text],
        [actionButton(data.observation.action, true)].filter(Boolean)
      )
    );
  }

  // One next step
  if (data.nextAction) {
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "If you want one thing to do" }),
        el(
          "div",
          { class: "next-action" },
          el(
            "div",
            { class: "stack", style: "gap: 2px; min-width: 0" },
            el("div", { text: data.nextAction.text }),
            data.nextAction.context
              ? el("div", { class: "small faint", text: data.nextAction.context })
              : null
          ),
          el("div", { class: "spacer" }),
          actionButton(data.nextAction.action)
        )
      )
    );
  }

  // Opportunities waiting on the user, minus whichever one is already featured
  // above as the single next step.
  const waiting = data.attention.filter((item) => !offered.has(`opportunity:${item.id}`));
  if (waiting.length) {
    const list = el("div", { class: "stack stack-3" });
    for (const item of waiting) {
      list.append(opportunityCard(item, { onOpen: nav.openOpportunity }));
    }
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el(
          "div",
          { class: "row" },
          el("div", { class: "eyebrow", text: "Where you left off" }),
          el("div", { class: "spacer" }),
          el("button", {
            class: "btn btn-quiet",
            type: "button",
            text: "See all",
            onClick: () => nav.go("opportunities"),
          })
        ),
        list
      )
    );
  }

  // Progress, framed as things that happened rather than targets met
  if (data.progress.length) {
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "Lately" }),
        progressList(data.progress)
      )
    );
  } else if (data.totalOpportunities === 0 && !data.observation) {
    inner.append(
      junoNote(
        ["We haven't built up any history yet. That's just where everyone starts."],
        [
          el("button", {
            class: "btn btn-primary",
            type: "button",
            text: "Talk to Juno",
            onClick: () => nav.go("juno"),
          }),
        ]
      )
    );
  }

  if (data.totalOpportunities === 0 && !offered.has("add:")) {
    inner.append(
      el(
        "div",
        { class: "row row-wrap" },
        el(
          "button",
          { class: "btn", type: "button", onClick: nav.addOpportunity },
          icon("plus", "icon-sm"),
          "Add a role you're curious about"
        )
      )
    );
  }
}

function laneLine(lanes) {
  const parts = lanes.filter((lane) => lane.count > 0).map((lane) => `${lane.count} ${lane.summary}`);
  if (!parts.length) return "Nothing in motion right now.";
  if (parts.length > 1) parts[parts.length - 1] = `and ${parts[parts.length - 1]}`;
  return `You have ${parts.join(parts.length > 2 ? ", " : " ")}.`;
}
