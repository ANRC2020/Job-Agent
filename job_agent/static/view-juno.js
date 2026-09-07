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
  const { threadId, messages } = await api.get("/api/thread");
  void threadId;

  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner" });
  page.append(inner);

  const chat = createChat({
    messages,
    suggestions: messages.length ? [] : OPENERS,
    placeholder: "Tell Juno what's on your mind…",
    intro: junoNote([
      "This is where we talk. You can be blunt with me — about what you want, what you're dreading, or what you have no idea about.",
      "I'll remember it, so you won't have to explain yourself twice.",
    ]),
    onChanged: () => nav.refreshCounts(),
  });

  inner.append(chat.thread);
  clear(root).append(page, chat.composer);
  chat.scrollDown(true);

  if (prompt) chat.ask(prompt);
  else chat.focus();
}
