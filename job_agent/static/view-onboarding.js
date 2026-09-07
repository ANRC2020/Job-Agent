// Meeting Juno. A short conversation that works even while her engine is still
// warming up, because nothing here needs the model.

import { api, autoGrow, clear, el, junoMark, prose, readFileAsBase64 } from "./lib.js";

export async function renderOnboarding(root, { onDone }) {
  const transcript = el("div", { class: "stack stack-4" });
  const current = el("div", { class: "stack stack-3" });
  const inner = el("div", { class: "onboarding-inner" }, transcript, current);
  const scroll = el("div", { class: "onboarding-scroll" }, inner);
  clear(root).append(el("div", { class: "onboarding" }, scroll));

  let state = await api.get("/api/onboarding");

  const scrollDown = () =>
    requestAnimationFrame(() => {
      scroll.scrollTop = scroll.scrollHeight;
    });

  function junoSays(lines, secondary = false) {
    const block = el("div", { class: "row fade-in", style: "align-items: flex-start; gap: 14px" });
    block.append(junoMark());
    const stack = el("div", { class: "stack stack-2" });
    lines.forEach((line, index) => {
      stack.append(el("div", { class: index ? "say is-secondary" : "say", text: line }));
    });
    block.append(stack);
    return block;
  }

  function youSaid(text) {
    return el(
      "div",
      { class: "turn turn-user fade-in" },
      el("div", { class: "bubble", text })
    );
  }

  function progress(step) {
    const row = el("div", { class: "progress-dots" });
    for (let index = 0; index < step.total; index += 1) {
      row.append(el("i", { class: index < step.index ? "is-done" : "" }));
    }
    return row;
  }

  async function advance(step, value, { skipped = false, echo = true } = {}) {
    transcript.append(junoSays(step.say));
    if (echo && value) transcript.append(youSaid(value));
    clear(current);
    state = await api.post("/api/onboarding/answer", { step: step.id, value, skipped });
    draw();
  }

  async function finishEarly(step) {
    transcript.append(junoSays(step.say));
    clear(current);
    state = await api.post("/api/onboarding/finish", {});
    draw();
  }

  function controls(step) {
    const box = el("div", { class: "stack stack-3 fade-in" });

    if (step.input === "resume") {
      box.append(resumeStep(step));
    } else if (step.input === "short") {
      const input = el("input", { type: "text", placeholder: step.placeholder || "" });
      const go = el("button", {
        class: "btn btn-primary",
        type: "submit",
        text: "Continue",
        disabled: true,
      });
      input.addEventListener("input", () => {
        go.disabled = !input.value.trim();
      });
      const form = el(
        "form",
        {
          class: "row",
          onSubmit: (event) => {
            event.preventDefault();
            if (input.value.trim()) advance(step, input.value.trim());
          },
        },
        input,
        go
      );
      box.append(form);
      requestAnimationFrame(() => input.focus());
    } else {
      const chips = el("div", { class: "suggestions" });
      for (const choice of step.choices || []) {
        chips.append(
          el("button", { class: "chip", type: "button", text: choice, onClick: () => advance(step, choice) })
        );
      }
      if (step.choices?.length) box.append(chips);
      const area = el("textarea", {
        class: "field-input",
        rows: 3,
        placeholder: step.placeholder || "",
      });
      autoGrow(area);
      const go = el("button", { class: "btn btn-primary", type: "submit", text: "Continue", disabled: true });
      area.addEventListener("input", () => {
        go.disabled = !area.value.trim();
      });
      area.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && area.value.trim()) {
          event.preventDefault();
          advance(step, area.value.trim());
        }
      });
      box.append(
        el(
          "form",
          {
            class: "stack stack-3",
            onSubmit: (event) => {
              event.preventDefault();
              if (area.value.trim()) advance(step, area.value.trim());
            },
          },
          area,
          el("div", { class: "row" }, go, el("div", { class: "spacer" }), footer(step))
        )
      );
      requestAnimationFrame(() => area.focus());
      return box;
    }

    box.append(el("div", { class: "row" }, footer(step, { flush: true })));
    return box;
  }

  // `flush` lines the first label up with Juno's text instead of leaving it
  // inset by the button's own padding.
  function footer(step, { flush = false } = {}) {
    const row = el("div", { class: flush ? "row row-wrap is-flush" : "row row-wrap" });
    if (step.optional) {
      row.append(
        el("button", {
          class: "btn btn-quiet",
          type: "button",
          text: step.skipLabel || "Skip",
          onClick: () => advance(step, "", { skipped: true, echo: false }),
        })
      );
    }
    if (step.canFinishEarly) {
      row.append(
        el("button", {
          class: "btn btn-quiet",
          type: "button",
          text: "That's enough for now",
          onClick: () => finishEarly(step),
        })
      );
    }
    return row;
  }

  function resumeStep(step) {
    const box = el("div", { class: "stack stack-3" });
    const file = el("input", { type: "file", accept: ".pdf,.docx,.txt,.md,.rtf", style: "display: none" });
    const status = el("div", { class: "small muted status-line" });

    const zone = el(
      "button",
      {
        class: "dropzone",
        type: "button",
        onClick: () => file.click(),
      },
      el("div", { class: "row" }, el("strong", { text: "Choose your resume" })),
      el("div", { class: "small faint", text: "PDF, Word, or plain text" })
    );

    const upload = async (chosen) => {
      if (!chosen) return;
      status.textContent = `Reading ${chosen.name}…`;
      try {
        const result = await api.post("/api/documents", {
          filename: chosen.name,
          content: await readFileAsBase64(chosen),
        });
        transcript.append(junoSays(step.say));
        transcript.append(youSaid(chosen.name));
        transcript.append(junoSays([result.message]));
        clear(current);
        state = await api.post("/api/onboarding/answer", { step: step.id, value: chosen.name });
        draw();
      } catch (problem) {
        status.textContent = problem.message;
      }
    };

    file.addEventListener("change", () => upload(file.files?.[0]));
    for (const name of ["dragover", "dragenter"]) {
      zone.addEventListener(name, (event) => {
        event.preventDefault();
        zone.classList.add("is-over");
      });
    }
    zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("is-over");
      upload(event.dataTransfer?.files?.[0]);
    });

    const pasteArea = el("textarea", {
      class: "field-input",
      rows: 7,
      placeholder: "Paste your resume, or just describe your last couple of roles…",
    });
    const pasteBox = el(
      "form",
      {
        class: "stack stack-3",
        style: "display: none",
        onSubmit: async (event) => {
          event.preventDefault();
          const text = pasteArea.value.trim();
          if (!text) return;
          status.textContent = "Reading it…";
          try {
            const result = await api.post("/api/documents/paste", { text });
            transcript.append(junoSays(step.say));
            transcript.append(youSaid("(pasted)"));
            transcript.append(junoSays([result.message]));
            clear(current);
            state = await api.post("/api/onboarding/answer", { step: step.id, value: "pasted" });
            draw();
          } catch (problem) {
            status.textContent = problem.message;
          }
        },
      },
      pasteArea,
      el("button", { class: "btn btn-primary", type: "submit", text: "Give this to Juno" })
    );

    const toggle = el("button", {
      class: "btn btn-quiet",
      type: "button",
      text: "Paste it instead",
      onClick: () => {
        const showing = pasteBox.style.display !== "none";
        pasteBox.style.display = showing ? "none" : "flex";
        zone.style.display = showing ? "flex" : "none";
        toggle.textContent = showing ? "Paste it instead" : "Choose a file instead";
        if (!showing) pasteArea.focus();
      },
    });

    box.append(file, zone, pasteBox, el("div", { class: "row is-flush" }, toggle), status);
    return box;
  }

  function draw() {
    clear(current);
    if (state.complete) {
      current.append(junoSays(state.closing));
      current.append(
        el(
          "div",
          { class: "row fade-in", style: "padding-left: 38px" },
          el("button", {
            class: "btn btn-primary btn-lg",
            type: "button",
            text: "Open Clover",
            onClick: onDone,
          })
        )
      );
      scrollDown();
      return;
    }
    const step = state.step;
    current.append(junoSays(step.say));
    const body = el("div", { class: "stack stack-3", style: "padding-left: 38px" }, controls(step));
    current.append(body);
    current.append(el("div", { class: "row", style: "padding-left: 38px" }, progress(step)));
    scrollDown();
  }

  draw();
}
