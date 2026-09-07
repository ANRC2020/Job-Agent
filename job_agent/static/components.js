// Pieces that show up in more than one place.

import { el, icon, junoMark, prose, when } from "./lib.js";

export function stageBadge(item) {
  return el("span", { class: `badge badge-${item.stage}`, text: item.stageLabel });
}

export function metaRow(item) {
  const bits = [];
  if (item.location) bits.push(el("span", {}, icon("pin", "icon-sm"), item.location));
  if (item.compensation) bits.push(el("span", {}, icon("coin", "icon-sm"), item.compensation));
  if (item.employmentType) bits.push(el("span", {}, item.employmentType));
  if (item.workplaceType && !String(item.location || "").toLowerCase().includes(String(item.workplaceType).toLowerCase())) {
    bits.push(el("span", { text: item.workplaceType }));
  }
  if (item.department) bits.push(el("span", { text: item.department }));
  if (item.seniority) bits.push(el("span", { text: item.seniority }));
  if (!bits.length) return null;
  return el("div", { class: "meta-row" }, bits);
}

export function reasonLine(kind, text) {
  return el(
    "div",
    { class: `reason reason-${kind}` },
    icon(kind === "fit" ? "check" : "x", "icon-sm"),
    el("span", { text })
  );
}

/** One opportunity, summarized the way a person would want to skim it. */
export function opportunityCard(item, { onOpen }) {
  const card = el("button", {
    class: "card-button",
    type: "button",
    onClick: () => onOpen(item.id),
  });
  const head = el(
    "div",
    { class: "row", style: "align-items: flex-start" },
    el(
      "div",
      { class: "stack", style: "gap: 2px; min-width: 0" },
      el("div", { class: "opp-title", text: item.title }),
      el("div", { class: "muted small", text: item.company })
    ),
    el("div", { class: "spacer" }),
    stageBadge(item)
  );

  const body = el("div", { class: "stack stack-2", style: "margin-top: 12px" });
  const meta = metaRow(item);
  if (meta) body.append(meta);
  if (item.verificationStatus === "verified") {
    body.append(
      el("div", {
        class: "small faint",
        text: `Verified at the source${item.lastVerifiedAt ? ` · ${when(item.lastVerifiedAt)}` : ""}`,
      })
    );
  }
  if (item.fitSummary) body.append(el("div", { class: "opp-take", text: item.fitSummary }));
  if (item.keyReason) body.append(reasonLine("fit", item.keyReason));
  if (item.mainConcern) body.append(reasonLine("concern", item.mainConcern));
  // Only when Juno set an action for this role. Repeating the stage default on
  // every card turns a useful line into wallpaper.
  if (item.nextAction && !item.nextActionIsDefault) {
    body.append(
      el(
        "div",
        { class: "row faint small", style: "margin-top: 4px" },
        icon("chevron", "icon-sm"),
        el("span", { text: item.nextAction })
      )
    );
  }

  card.append(head, body);
  return card;
}

/** Juno saying something, in a card. Used for empty states and observations. */
export function junoNote(lines, actions = []) {
  const stack = el("div", { class: "stack stack-3" });
  for (const line of [].concat(lines)) {
    stack.append(el("div", { class: "prose" }, prose(line)));
  }
  if (actions.length) stack.append(el("div", { class: "actions" }, actions));
  return el("div", { class: "observation" }, junoMark(true), stack);
}

export function progressList(events) {
  const list = el("div", { class: "stack" });
  for (const event of events) {
    list.append(
      el(
        "div",
        { class: "progress-item" },
        icon("check", "icon-sm"),
        el(
          "div",
          { class: "stack", style: "gap: 1px; min-width: 0" },
          el("div", { text: event.headline }),
          event.detail ? el("div", { class: "small faint", text: event.detail }) : null
        ),
        el("div", { class: "progress-when", text: when(event.occurred_at) })
      )
    );
  }
  return list;
}

export function sectionBlock(title, count, body, { open = false } = {}) {
  const summary = el(
    "summary",
    {},
    icon("chevron", "icon-sm chevron"),
    el("span", { text: title }),
    count === null || count === undefined ? null : el("span", { class: "count", text: String(count) })
  );
  return el("details", { class: "section", open }, summary, el("div", { class: "section-body" }, body));
}
