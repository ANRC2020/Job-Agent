// One opportunity, one context. The posting, Juno's reasoning, the drafts, the
// notes, the history, and the whole conversation about it — in one place.

import { createChat } from "./chat.js";
import { junoNote, metaRow, reasonLine, sectionBlock, stageBadge } from "./components.js";
import { api, clear, el, icon, junoMark, prose, when } from "./lib.js";

const CHAT_OPENERS = {
  suggested: ["Why did you pick this one?", "What would worry you about it?", "Is this a stretch for me?"],
  interested: ["Help me tailor my resume for this", "Draft a cover letter", "What are they likely to ask?"],
  applying: ["Draft a cover letter", "Tighten my resume for this", "What should I say about my gap?"],
  applied: ["Should I follow up yet?", "What do I do while I wait?"],
  interviewing: ["Help me prepare", "What should I ask them?", "How do I talk about my last role?"],
  offer: ["Help me think this through", "What should I ask about the offer?"],
  closed: ["What can I take from this one?"],
};

export async function renderOpportunity(root, nav, { id, flash = null } = {}) {
  const data = await api.get(`/api/opportunities/${id}`);

  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner stack stack-4" });
  page.append(inner);

  const reload = (message) => nav.openOpportunity(id, message);

  async function move(stage, { reason = "", outcome = "", message = "" } = {}) {
    const result = await api.post(`/api/opportunities/${id}/stage`, { stage, reason, outcome });
    nav.refreshCounts();
    reload(result.reflection?.prompt || message);
  }

  function talk(prompt) {
    chat.prefill(prompt);
  }

  async function applyWithJuno() {
    const target = data.applyUrl || data.sourceUrl;
    if (!target) {
      talk("Help me find the official application page for this role.");
      return;
    }
    await api.post("/api/browser/start", { url: target, opportunityId: id });
    if (!["applying", "applied", "interviewing", "offer"].includes(data.stage)) {
      await api.post(`/api/opportunities/${id}/stage`, {
        stage: "applying",
        reason: "Started Clover's guided application runner",
      });
      nav.refreshCounts();
    }
    reload("I opened the application in Clover's browser. I'll fill verified answers, move through safe steps, and pause whenever I need you.");
  }

  // --- header ---------------------------------------------------------

  inner.append(
    el(
      "button",
      { class: "btn btn-quiet btn-back", type: "button", onClick: () => nav.go("opportunities") },
      icon("chevronLeft", "icon-sm"),
      "All opportunities"
    )
  );

  const header = el(
    "div",
    { class: "detail-head" },
    el(
      "div",
      { class: "row", style: "align-items: flex-start" },
      el(
        "div",
        { class: "stack", style: "gap: 3px; min-width: 0" },
        el("h1", { text: data.title }),
        el("div", { class: "muted", text: data.company })
      ),
      el("div", { class: "spacer" }),
      stageBadge(data)
    )
  );
  const meta = metaRow(data);
  if (meta) header.append(meta);
  if (data.sourceUrl) {
    header.append(
      el(
        "div",
        { class: "meta-row" },
        el(
          "a",
          { href: data.sourceUrl, target: "_blank", rel: "noreferrer" },
          icon("link", "icon-sm"),
          "View the posting"
        )
      )
    );
  }
  if (data.applyUrl && data.applyUrl !== data.sourceUrl) {
    header.append(
      el(
        "div",
        { class: "meta-row" },
        el(
          "a",
          { href: data.applyUrl, target: "_blank", rel: "noreferrer" },
          icon("link", "icon-sm"),
          "Open direct application"
        )
      )
    );
  }
  inner.append(header);

  if (flash) inner.append(junoNote([flash]));

  // --- Juno's take ----------------------------------------------------

  if (data.fitSummary || data.why.length || data.concerns.length || data.standouts.length) {
    const take = el("div", { class: "stack stack-3" });
    take.append(
      el(
        "div",
        { class: "row" },
        junoMark(),
        el("div", { class: "eyebrow", text: "Juno's take" })
      )
    );
    if (data.fitSummary) take.append(el("div", { class: "prose" }, prose(data.fitSummary)));
    const points = el("div", { class: "stack stack-2" });
    for (const reason of data.why) points.append(reasonLine("fit", reason));
    for (const concern of data.concerns) points.append(reasonLine("concern", concern));
    if (points.childElementCount) take.append(points);
    if (data.standouts.length) {
      take.append(
        el(
          "div",
          { class: "small muted" },
          data.standouts.map((item) => el("div", { text: `— ${item}` }))
        )
      );
    }
    inner.append(el("div", { class: "card-accent" }, take));
  } else if (data.lane !== "closed") {
    // Offering to weigh in on the fit of a role the user has already closed
    // would be asking them to reopen a decision they just made.
    inner.append(
      junoNote(
        [
          "I haven't formed a view on this one yet. If you want, I'll read it properly and tell you what I think of the fit — including anything that gives me pause.",
        ],
        [
          el("button", {
            class: "btn btn-primary",
            type: "button",
            text: "Ask Juno to weigh in",
            onClick: () =>
              chat.ask(
                "Read this role properly and tell me honestly what you think of the fit — what works, what doesn't, and what you'd be worried about. Then save your take."
              ),
          }),
        ]
      )
    );
  }

  // --- what happens next ----------------------------------------------

  const actions = el("div", { class: "actions" });
  const act = (label, handler, primary = false) =>
    el("button", { class: primary ? "btn btn-primary" : "btn", type: "button", text: label, onClick: handler });

  if (data.stage === "suggested") {
    actions.append(
      act("I'm interested", () => move("interested", { message: "Saved. Take it at whatever pace suits you." }), true),
      act("Apply with Juno", applyWithJuno),
      act("Not for me", () =>
        move("closed", {
          outcome: "not_a_fit",
          message: "Fair enough — knowing what you don't want is real progress, and it clears space.",
        })
      ),
      act("Ask Juno about it", () => talk("What do you make of this one?"))
    );
  } else if (data.stage === "interested") {
    actions.append(
      act("Apply with Juno", applyWithJuno, true),
      act("I've applied", () => move("applied", { message: "Logged. Nothing to do now but wait." })),
      act("Not for me", () =>
        move("closed", { outcome: "not_a_fit", message: "Closed out. That's a decision, not a loss." })
      )
    );
  } else if (data.stage === "applying") {
    actions.append(
      act("Continue application", applyWithJuno, true),
      act("I've applied", () => move("applied", { message: "Sent. That's the hard part done." })),
      act("Work on it with Juno", () => talk("Let's keep working on my application for this role."))
    );
  } else if (data.stage === "applied") {
    actions.append(
      act("I heard back", () => move("interviewing", { message: "Good news. Whenever you're ready, we can prepare." }), true),
      act("It's closed out", () => move("closed", { outcome: "rejected", message: "That one's behind you now." }))
    );
  } else if (data.stage === "interviewing") {
    actions.append(
      act("Prepare with Juno", () => talk("Help me prepare for this interview."), true),
      act("I got an offer", () => move("offer", { message: "That's worth sitting with for a minute." })),
      act("It's closed out", () =>
        move("closed", { outcome: "rejected", message: "Getting to an interview still counted." })
      )
    );
  } else if (data.stage === "offer") {
    actions.append(
      act("Talk it through", () => talk("Help me think through this offer."), true),
      act("It's closed out", () => move("closed", { outcome: "declined" }))
    );
  } else {
    actions.append(
      act("Reopen this", () => move("interested", { message: "Back on the shelf." })),
      act("What can I learn from it?", () =>
        talk("Looking back at this one, is there anything worth taking from it?")
      )
    );
  }
  inner.append(actions);

  const runner = el("div");
  let runnerPoll = null;
  const questionDrafts = new Map();
  inner.append(runner);

  async function refreshRunner() {
    if (!document.body.contains(page)) return;
    if (runnerPoll) window.clearTimeout(runnerPoll);
    try {
      const state = await api.get("/api/browser/status");
      clear(runner);
      if (!state.running || state.opportunityId !== id) return;
      const runnerActions = el("div", { class: "actions" });
      const refresh = async (path, payload = {}) => {
        await api.post(path, payload);
        refreshRunner();
      };
      if (state.phase === "needs_input" || state.phase === "error") {
        runnerActions.append(
          act("Check this step again", () => refresh("/api/browser/prepare"), true)
        );
      }
      if (state.phase === "ready_to_submit") {
        runnerActions.append(
          act("Continue to submission approval", () => refresh("/api/browser/submission/request"), true)
        );
      }
      const actionId = state.submission?.actionId;
      if (state.phase === "awaiting_approval" && actionId) {
        runnerActions.append(
          act("Submit application now", () => refresh("/api/browser/submission/approve", { actionId }), true),
          act("Cancel", () => refresh("/api/browser/submission/cancel", { actionId }))
        );
      }
      if (state.phase === "awaiting_receipt" && actionId) {
        runnerActions.append(
          act("Confirm employer received it", async () => {
            await refresh("/api/browser/submission/receipt", { actionId });
            nav.refreshCounts();
            reload("Application receipt confirmed. I marked this opportunity as applied.");
          }, true)
        );
      }
      if (state.phase === "completed" && state.reflection?.prompt) {
        runnerActions.append(
          act("Reflect with Juno (optional)", () => talk(state.reflection.prompt))
        );
      }
      runnerActions.append(
        act("Close application browser", () => refresh("/api/browser/close"))
      );
      const unresolved = state.unresolved || [];
      const answerable = unresolved.filter((item) => item.fieldId);
      let questionPanel = null;
      if (answerable.length) {
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
            feedback.textContent = "";
            try {
              await api.post("/api/browser/answers", { answers });
              for (const answer of answers) questionDrafts.delete(answer.fieldId);
              refreshRunner();
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
            text: "Answer here and Juno will place it into the application. Nothing is submitted without your approval.",
          })
        );
        for (const [index, item] of answerable.entries()) {
          const controlId = `application-question-${index}`;
          const options = item.options || [];
          let control;
          if (options.length) {
            control = el(
              "select",
              {
                id: controlId,
                class: "field-input",
                onChange: (event) => questionDrafts.set(item.fieldId, event.target.value),
              },
              el("option", { value: "", text: "Choose an answer…" }),
              options.map((option) =>
                el("option", {
                  value: option,
                  text: option,
                  selected: questionDrafts.get(item.fieldId) === option,
                })
              )
            );
          } else if (item.type === "textarea") {
            control = el("textarea", {
              id: controlId,
              class: "field-input",
              rows: "3",
              onInput: (event) => questionDrafts.set(item.fieldId, event.target.value),
            });
          } else {
            control = el("input", {
              id: controlId,
              class: "field-input",
              type: item.type === "number" ? "number" : "text",
              onInput: (event) => questionDrafts.set(item.fieldId, event.target.value),
            });
          }
          if (!options.length && questionDrafts.has(item.fieldId)) {
            control.value = questionDrafts.get(item.fieldId);
          }
          controls.set(item.fieldId, control);
          form.append(
            el(
              "label",
              { class: "stack stack-2 application-question", for: controlId },
              el("strong", {
                class: item.sensitive ? "warning" : "",
                text: `${item.label}${item.optional ? " (optional)" : ""}`,
              }),
              control,
              item.sensitive
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
            answerable.some((item) => item.optional)
              ? el("button", {
                  class: "btn",
                  type: "button",
                  text: "Skip optional questions",
                  onClick: async () => {
                    await refresh("/api/browser/questions/skip", {
                      fieldIds: answerable
                        .filter((item) => item.optional)
                        .map((item) => item.fieldId),
                    });
                  },
                })
              : null
          )
        );
        questionPanel = form;
      }
      runner.append(
        el(
          "div",
          { class: "card-accent stack stack-3" },
          el("div", { class: "eyebrow", text: "Application runner" }),
          el("strong", { text: state.message || "Juno is working on this application." }),
          state.url ? el("div", { class: "small faint", text: state.url }) : null,
          state.timing
            ? el("div", {
                class: "small faint",
                text: `${state.timing.quickFilled || 0} filled instantly · ${state.timing.junoFilled || 0} prepared by Juno · ${(state.timing.elapsedMs / 1000).toFixed(1)}s`,
              })
            : null,
          unresolved.length
            ? el(
                "div",
                { class: "stack stack-2" },
                answerable.length
                  ? questionPanel
                  : el("div", { class: "small muted", text: "Waiting for you in Chrome:" }),
                answerable.length
                  ? null
                  : unresolved.map((item) =>
                  el("div", {
                    class: item.sensitive ? "small warning" : "small",
                    text: `— ${item.label}`,
                  })
                )
              )
            : null,
          runnerActions
        )
      );
      if (!["completed", "closed"].includes(state.phase)) {
        runnerPoll = window.setTimeout(refreshRunner, 1500);
      }
    } catch (problem) {
      clear(runner);
      runner.append(el("div", { class: "small warning", text: problem.message }));
    }
  }

  refreshRunner();

  // --- the record -----------------------------------------------------

  const record = el("div", { class: "stack" });
  const listingFacts = [
    data.postedAt ? `Posted: ${when(data.postedAt)}` : "",
    data.verificationStatus
      ? `Source status: ${data.verificationStatus}${data.lastVerifiedAt ? ` · checked ${when(data.lastVerifiedAt)}` : ""}`
      : "",
    data.sourceKind ? `Source: ${data.sourceKind.replaceAll("_", " ")}` : "",
  ].filter(Boolean);
  if (listingFacts.length || data.requirements.length) {
    record.append(
      sectionBlock(
        "Listing details",
        null,
        el(
          "div",
          { class: "stack stack-2" },
          listingFacts.map((item) => el("div", { class: "small muted", text: item })),
          data.requirements.length
            ? el(
                "div",
                { class: "stack stack-2", style: "margin-top: 8px" },
                el("strong", { text: "Requirements" }),
                data.requirements.map((item) => el("div", { text: `— ${item}` }))
              )
            : null
        ),
        { open: true }
      )
    );
  }
  if (data.description) {
    record.append(
      sectionBlock(
        "Job description",
        null,
        el("div", { class: "jd", text: data.description })
      )
    );
  }
  record.append(
    sectionBlock(
      "Application materials",
      data.materials.length || null,
      data.materials.length
        ? materialsBlock(data.materials)
        : el(
            "div",
            { class: "muted small" },
            "Nothing drafted yet. Ask Juno to tailor your resume or write a cover letter for this role and it'll be kept here."
          )
    )
  );
  if (data.interactions.length) {
    record.append(
      sectionBlock(
        "Notes and contact",
        data.interactions.length,
        el(
          "div",
          { class: "stack" },
          data.interactions.map((item) =>
            el(
              "div",
              { class: "timeline-item" },
              el("div", { class: "timeline-when", text: when(item.occurred_at) }),
              el(
                "div",
                { class: "stack", style: "gap: 2px; min-width: 0" },
                el("div", { class: "small faint", text: noteLabel(item.kind) }),
                el("div", { text: item.summary || "" })
              )
            )
          )
        )
      )
    );
  }
  if (data.history.length > 1) {
    record.append(
      sectionBlock(
        "How this moved",
        null,
        el(
          "div",
          { class: "stack" },
          data.history.map((event) =>
            el(
              "div",
              { class: "timeline-item" },
              el("div", { class: "timeline-when", text: when(event.occurred_at) }),
              el(
                "div",
                { class: "stack", style: "gap: 2px" },
                el("div", { text: event.fromLabel ? `${event.fromLabel} → ${event.toLabel}` : event.toLabel }),
                event.reason ? el("div", { class: "small faint", text: event.reason }) : null
              )
            )
          )
        )
      )
    );
  }
  inner.append(record);

  // --- the conversation about this role -------------------------------

  inner.append(
    el(
      "div",
      { class: "row", style: "margin-top: 12px" },
      junoMark(),
      el("div", { class: "eyebrow", text: `About ${data.company}` })
    )
  );

  const chat = createChat({
    opportunityId: id,
    messages: data.messages,
    actions: data.actions || [],
    suggestions: data.messages.length ? [] : CHAT_OPENERS[data.stage] || [],
    placeholder: `Ask Juno about this role…`,
    intro: el(
      "div",
      { class: "card-quiet" },
      el(
        "div",
        { class: "prose muted" },
        prose(
          "Anything we say here stays with this role — the posting, your drafts, how the interviews went, what you thought of them. I'll have all of it next time you open this."
        )
      )
    ),
    onChanged: () => reload(),
  });

  inner.append(chat.thread);
  clear(root).append(page, chat.composer);
  page.scrollTop = 0;
}

/** The current draft of each thing, with superseded versions kept but folded away. */
function materialsBlock(materials) {
  const byKind = new Map();
  for (const material of materials) {
    byKind.set(material.kind, [...(byKind.get(material.kind) || []), material]);
  }

  const stack = el("div", { class: "stack stack-3" });
  for (const versions of byKind.values()) {
    const [latest, ...earlier] = [...versions].sort((a, b) => (b.version || 0) - (a.version || 0));
    stack.append(materialCard(latest, true));
    if (!earlier.length) continue;
    stack.append(
      el(
        "details",
        { class: "section section-nested" },
        el(
          "summary",
          {},
          icon("chevron", "icon-sm chevron"),
          el("span", { text: earlier.length === 1 ? "Earlier version" : "Earlier versions" }),
          el("span", { class: "count", text: String(earlier.length) })
        ),
        el(
          "div",
          { class: "section-body stack stack-3" },
          earlier.map((material) => materialCard(material, false))
        )
      )
    );
  }
  return stack;
}

/** The current draft reads in full; older ones stay compact. */
function materialCard(material, current) {
  return el(
    "div",
    { class: "material" },
    el(
      "div",
      { class: "row small" },
      el("strong", { text: materialLabel(material.kind) }),
      el("span", { class: "faint", text: `v${material.version}` }),
      el("div", { class: "spacer" }),
      material.content ? copyButton(material.content) : null,
      el("span", { class: "faint", text: when(material.updated_at) })
    ),
    material.content ? el("pre", { class: current ? "" : "is-capped", text: material.content }) : null
  );
}

/** Application forms want this text pasted in, so make that one click. */
function copyButton(text) {
  const button = el("button", { class: "btn-quiet", type: "button", text: "Copy" });
  button.addEventListener("click", async () => {
    button.textContent = (await copyText(text)) ? "Copied" : "Couldn't copy";
    setTimeout(() => (button.textContent = "Copy"), 1800);
  });
  return button;
}

/** The clipboard API isn't granted in every webview, so keep a way that is. */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    /* fall through */
  }
  const scratch = el("textarea", {
    style: "position: fixed; top: -1000px; opacity: 0",
    "aria-hidden": "true",
  });
  scratch.value = text;
  document.body.append(scratch);
  scratch.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    scratch.remove();
  }
}

function materialLabel(kind) {
  return (
    {
      resume: "Resume",
      cover_letter: "Cover letter",
      application_answer: "Application answer",
      portfolio: "Portfolio",
      outreach: "Outreach",
    }[kind] || kind
  );
}

function noteLabel(kind) {
  return (
    {
      note: "Note",
      email: "Email",
      call: "Call",
      interview: "Interview",
      task: "Task",
      follow_up: "Follow-up",
      reflection: "Reflection",
    }[kind] || kind
  );
}
