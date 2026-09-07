// The main conversation with Juno.

import { createChat } from "./chat.js";
import { junoNote } from "./components.js";
import { api, clear, el } from "./lib.js";

const OPENERS = [
  "I don't really know what I qualify for",
  "Find me something remote",
  "Can we work on my resume?",
  "What should I focus on this week?",
];

export async function renderJuno(root, nav, { prompt } = {}) {
  const [{ threadId, messages, actions = [] }, board] = await Promise.all([
    api.get("/api/thread"),
    api.get("/api/opportunities"),
  ]);
  void threadId;

  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner" });
  page.append(inner);

  const chat = createChat({
    messages,
    actions,
    suggestions: messages.length ? [] : OPENERS,
    placeholder: "Tell Juno what's on your mind…",
    intro: junoNote([
      "This is where we talk. You can be blunt with me — about what you want, what you're dreading, or what you have no idea about.",
      "I'll remember it, so you won't have to explain yourself twice.",
    ]),
    onChanged: () => nav.refreshCounts(),
  });

  if (board.opportunities?.length) {
    const selector = el(
      "select",
      {
        class: "btn btn-quiet",
        "aria-label": "Open an opportunity conversation",
        onChange: (event) => {
          if (event.target.value) nav.openOpportunity(event.target.value);
        },
      },
      el("option", { value: "", text: "Talk generally" }),
      board.opportunities.map((item) =>
        el("option", {
          value: item.id,
          text: `${item.title}${item.company ? ` · ${item.company}` : ""}`,
        })
      )
    );
    inner.append(el("div", { class: "row", style: "justify-content: flex-end; margin-bottom: 12px" }, selector));
  }
  inner.append(chat.thread);
  clear(root).append(page, chat.composer);
  chat.scrollDown(true);

  if (prompt) chat.ask(prompt);
  else chat.focus();
}
