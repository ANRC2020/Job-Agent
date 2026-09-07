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
  let pairingCode = null;

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

    if (data.pendingActions?.length) {
      body.append(
        el(
          "div",
          { class: "stack stack-3" },
          el("div", { class: "eyebrow", text: "Waiting for your approval" }),
          data.pendingActions.map((item) =>
            el(
              "div",
              { class: "card-quiet stack stack-2" },
              el("div", { text: item.explanation }),
              el(
                "div",
                { class: "actions" },
                el("button", {
                  class: "btn",
                  type: "button",
                  text: "Approve",
                  onClick: async () => {
                    await api.post(`/api/approvals/${item.id}`, { approved: true });
                    draw();
                  },
                }),
                el("button", {
                  class: "btn btn-quiet",
                  type: "button",
                  text: "Reject",
                  onClick: async () => {
                    await api.post(`/api/approvals/${item.id}`, { approved: false });
                    draw();
                  },
                })
              )
            )
          )
        )
      );
    }

    body.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "Browser companion" }),
        el("div", {
          class: "small muted",
          text: "Pair the Chromium extension to ask Juno about the page you're viewing. Page captures stay temporary unless you choose Save.",
        }),
        pairingCode
          ? el(
              "div",
              { class: "card-quiet stack stack-2" },
              el("div", { class: "small muted", text: "Enter this one-time code in the extension within 10 minutes:" }),
              el("strong", { text: pairingCode.code, style: "font-size: 24px; letter-spacing: .18em" })
            )
          : null,
        el("button", {
          class: "btn",
          type: "button",
          text: pairingCode ? "Create a new code" : "Pair a browser",
          onClick: async () => {
            pairingCode = await api.post("/api/settings/extension/pairing-code", {});
            draw();
          },
        }),
        ...(data.browserConnections || []).map((connection) =>
          el(
            "div",
            { class: "understanding-item row" },
            el(
              "div",
              { class: "stack", style: "gap: 2px" },
              el("div", { text: connection.extension_name || "Clover Browser Companion" }),
              el("div", {
                class: "small faint",
                text: `Last used ${connection.last_used_at ? new Date(connection.last_used_at).toLocaleString() : "never"}`,
              })
            ),
            el("div", { class: "spacer" }),
            el("button", {
              class: "btn btn-quiet",
              type: "button",
              text: "Revoke",
              onClick: async () => {
                await api.post(`/api/settings/extension/${connection.id}/revoke`, {});
                draw();
              },
            })
          )
        )
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
    const modelOptions = [
      ...new Set([...(engineState.recommendedModels || []), ...models, engineState.model]),
    ];
    const modelLabel = (name) => {
      if (name === "qwen/qwen3.5-4b") return "Qwen3.5 4B — faster";
      if (name === "qwen/qwen3.5-9b") return "Qwen3.5 9B — higher quality";
      return name;
    };
    const select = el(
      "select",
      {},
      modelOptions.map((name) =>
        el("option", {
          value: name,
          selected: name === engineState.model,
          text: modelLabel(name),
        })
      )
    );
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
