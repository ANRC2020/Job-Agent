// Settings. The only place in Clover where the machinery is visible, and even
// here it's tucked behind "Advanced".

import { api, clear, el, icon } from "./lib.js";

export function openSettings() {
  const overlay = el("div", { class: "overlay" });
  const body = el("div", { class: "stack stack-4" });
  const drawer = el("div", { class: "drawer" }, body);
  const close = () => overlay.remove();

  overlay.append(drawer);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  document.body.append(overlay);

  const log = el("pre", { class: "log", style: "display: none" });

  async function engine(action, model) {
    log.style.display = "block";
    log.textContent = "Working on it…";
    try {
      const result = await api.post(`/api/engine/${action}`, model ? { model } : {});
      log.textContent = (result.logs || []).join("\n") || "Done.";
      draw();
    } catch (problem) {
      log.textContent = problem.message;
    }
  }

  async function draw() {
    const data = await api.get("/api/settings");
    const engineState = data.engine;
    clear(body);

    body.append(
      el(
        "div",
        { class: "row" },
        el("h2", { text: "Settings" }),
        el("div", { class: "spacer" }),
        el("button", { class: "btn btn-quiet", type: "button", "aria-label": "Close", onClick: close }, icon("x", "icon-sm"))
      )
    );

    // Juno's state, in plain language
    body.append(
      el(
        "div",
        { class: "card-quiet stack stack-3" },
        el(
          "div",
          { class: "stack", style: "gap: 3px" },
          el("strong", { text: engineState.ready ? "Juno is ready" : "Juno isn't running yet" }),
          el("div", {
            class: "small muted",
            text: engineState.ready
              ? "She's thinking entirely on this machine. Nothing you tell her leaves it."
              : "She needs her local engine running before she can answer.",
          })
        ),
        // Offering to start something that is already running just makes a
        // working app look broken.
        el(
          "div",
          { class: "actions" },
          engineState.ready
            ? null
            : el("button", {
                class: "btn btn-primary",
                type: "button",
                text: "Start Juno",
                onClick: () => engine("start"),
              }),
          el("button", { class: "btn btn-quiet", type: "button", text: "Repair setup", onClick: () => engine("setup") })
        )
      )
    );

    // What shapes her behavior
    const personal = data.personalization;
    const items = [
      ...(personal.learnings || []).map((item) => item.claim),
      ...(personal.communicationPreferences || []).map(
        (item) => `${item.dimension}: ${typeof item.value === "string" ? item.value : JSON.stringify(item.value)}`
      ),
    ];
    body.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "What shapes how Juno works with you" }),
        items.length
          ? el(
              "div",
              { class: "stack" },
              items.map((text) => el("div", { class: "understanding-item" }, el("div", { text })))
            )
          : el("div", {
              class: "small muted",
              text: "Nothing yet. Tell Juno how you'd like her to work with you and she'll hold onto it.",
            })
      )
    );

    // Where the data lives
    body.append(
      el(
        "div",
        { class: "stack stack-2" },
        el("div", { class: "eyebrow", text: "Your data" }),
        el("div", {
          class: "small muted",
          text: "Everything Clover knows is stored in a single file on this computer. There is no account and no sync.",
        }),
        el("div", { class: "small faint", text: engineState.database?.path || "" })
      )
    );

    // Advanced
    const models = engineState.availableModels || [];
    const select = el("select", {}, [
      ...models.map((name) => el("option", { value: name, selected: name === engineState.model, text: name })),
      models.includes(engineState.model)
        ? null
        : el("option", { value: engineState.model, selected: true, text: engineState.model }),
    ]);
    body.append(
      el(
        "details",
        { class: "section" },
        el("summary", {}, icon("chevron", "icon-sm chevron"), el("span", { text: "Advanced" })),
        el(
          "div",
          { class: "section-body stack stack-3" },
          el("div", { class: "field" }, el("label", { text: "Which local model Juno uses" }), select),
          el("button", {
            class: "btn btn-block",
            type: "button",
            text: "Use this model",
            onClick: () => engine("model", select.value),
          }),
          el("div", { class: "small faint", text: `Serving on ${engineState.apiBase || ""}` }),
          log
        )
      )
    );
  }

  draw();
}
