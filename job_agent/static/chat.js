// The conversation surface. Used for Juno's main thread and, unchanged, inside
// every opportunity — the only difference is which context it's attached to.

import { append, autoGrow, clear, dots, el, junoMark, prose, sendToJuno } from "./lib.js";

export function createChat({
  opportunityId = null,
  messages = [],
  suggestions = [],
  placeholder = "Talk to Juno…",
  intro = null,
  onChanged = () => {},
} = {}) {
  const thread = el("div", { class: "thread" });
  const textarea = el("textarea", { rows: 1, placeholder, "aria-label": "Message Juno" });
  const send = el("button", { class: "send", type: "submit", "aria-label": "Send" });
  send.append(sendGlyph());
  const composer = el("form", { class: "composer" }, textarea, send);
  const suggestionRow = el("div", { class: "suggestions" });
  const wrap = el("div", { class: "composer-wrap" }, el("div", { class: "composer-inner" }, suggestionRow, composer));

  let busy = false;
  autoGrow(textarea);

  const scroller = () => thread.closest(".page");

  function scrollDown(force = false) {
    const box = scroller();
    if (!box) return;
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
    if (force || nearBottom) box.scrollTop = box.scrollHeight;
  }

  function addUserTurn(text) {
    thread.append(el("div", { class: "turn turn-user" }, el("div", { class: "bubble", text })));
  }

  function addJunoTurn() {
    const bubble = el("div", { class: "bubble" });
    thread.append(el("div", { class: "turn turn-juno" }, junoMark(), bubble));
    return bubble;
  }

  function renderHistory() {
    clear(thread);
    if (intro && !messages.length) thread.append(intro);
    for (const message of messages) {
      if (message.role === "user") addUserTurn(message.content);
      else append(addJunoTurn(), [el("div", { class: "prose" }, prose(message.content))]);
    }
  }

  function setSuggestions(items) {
    clear(suggestionRow);
    if (busy) return;
    for (const item of items) {
      suggestionRow.append(
        el("button", { class: "chip", type: "button", text: item, onClick: () => submit(item) })
      );
    }
  }

  function setBusy(state) {
    busy = state;
    send.disabled = state || !textarea.value.trim();
    textarea.disabled = false;
    if (state) clear(suggestionRow);
  }

  async function submit(text) {
    const message = String(text || textarea.value).trim();
    if (!message || busy) return;
    textarea.value = "";
    textarea.style.height = "auto";
    setBusy(true);
    addUserTurn(message);
    messages.push({ role: "user", content: message });
    scrollDown(true);

    const bubble = addJunoTurn();
    const status = el("div", { class: "activity" }, dots(), el("span", { text: "Thinking" }));
    bubble.append(status);

    // Text arrives in blocks: Juno may say something, go do a few things, then
    // carry on. Each block is settled into prose once it's finished.
    let block = null;
    let pending = "";
    let failed = false;

    const settle = () => {
      if (!block) return;
      block.replaceChildren(prose(pending));
      block.removeAttribute("style");
      block = null;
      pending = "";
    };

    await sendToJuno({
      message,
      opportunityId,
      handlers: {
        onActivity: (label) => {
          status.lastChild.textContent = label;
          scrollDown();
        },
        onDelta: (piece) => {
          if (!block) {
            block = el("div", { class: "prose", style: "white-space: pre-wrap" });
            bubble.insertBefore(block, status);
          }
          pending += piece;
          block.textContent = pending;
          scrollDown();
        },
        onBreak: settle,
        onError: (problem) => {
          failed = true;
          settle();
          status.remove();
          bubble.append(el("div", { class: "prose muted" }, prose(problem)));
          scrollDown();
        },
        onEnd: (result) => {
          settle();
          status.remove();
          const finalText = String(result.content || "").trim();
          if (finalText) {
            messages.push({ role: "assistant", content: finalText });
          } else if (!failed) {
            bubble.append(
              el("div", { class: "prose muted" }, prose("Juno went quiet there. Try asking again."))
            );
          }
          setBusy(false);
          scrollDown();
          if (result.changed) onChanged();
        },
      },
    }).catch(() => {
      settle();
      status.remove();
      bubble.append(
        el(
          "div",
          { class: "prose muted" },
          prose("Juno couldn't be reached just now. She may still be waking up.")
        )
      );
      setBusy(false);
    });
  }

  composer.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });

  textarea.addEventListener("input", () => {
    send.disabled = busy || !textarea.value.trim();
  });

  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });

  renderHistory();
  setSuggestions(suggestions);
  send.disabled = true;

  return {
    thread,
    composer: wrap,
    focus: () => textarea.focus(),
    ask: (text) => submit(text),
    prefill: (text) => {
      textarea.value = text;
      textarea.dispatchEvent(new Event("input"));
      textarea.focus();
    },
    scrollDown,
  };
}

function sendGlyph() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "17");
  svg.setAttribute("height", "17");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M12 19V6M6 12l6-6 6 6");
  svg.append(path);
  return svg;
}
