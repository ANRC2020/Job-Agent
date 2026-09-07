// Small helpers shared by every view. No framework, no build step.

export function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(4)) {
    if (child === null || child === undefined || child === false || child === "") continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

const ICON_PATHS = {
  home: "M3 10.5 12 3l9 7.5M5.5 9v11h13V9",
  juno: "M12 3c3.5 2.2 5 5 5 8a5 5 0 0 1-10 0c0-3 1.5-5.8 5-8ZM12 11v10",
  briefcase: "M3 8h18v12H3zM9 8V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V8",
  person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM4.5 21c0-3.6 3.4-6 7.5-6s7.5 2.4 7.5 6",
  gear: "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a1.6 1.6 0 1 1-2.3 2.3l-.1-.1a1.7 1.7 0 0 0-2.9 1.2 1.6 1.6 0 1 1-3.2 0 1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.6 1.6 0 1 1-2.3-2.3l.1-.1A1.7 1.7 0 0 0 4.6 15a1.6 1.6 0 1 1 0-3.2 1.7 1.7 0 0 0 1.2-2.9l-.1-.1a1.6 1.6 0 1 1 2.3-2.3l.1.1A1.7 1.7 0 0 0 11 4.6a1.6 1.6 0 1 1 3.2 0 1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.6 1.6 0 1 1 2.3 2.3l-.1.1a1.7 1.7 0 0 0 1.2 2.9 1.6 1.6 0 1 1 0 3.2",
  plus: "M12 5v14M5 12h14",
  send: "M5 12h14M13 6l6 6-6 6",
  check: "M4.5 12.5 9 17l10.5-10.5",
  x: "M6 6l12 12M18 6 6 18",
  chevron: "m9 6 6 6-6 6",
  chevronLeft: "m15 6-6 6 6 6",
  link: "M10.5 13.5a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1 1M13.5 10.5a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1-1",
  pin: "M12 21s7-6.3 7-11a7 7 0 1 0-14 0c0 4.7 7 11 7 11ZM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  coin: "M12 20c4.4 0 8-1.6 8-3.5V7.5C20 5.6 16.4 4 12 4S4 5.6 4 7.5v9C4 18.4 7.6 20 12 20ZM20 7.5c0 2-3.6 3.5-8 3.5s-8-1.6-8-3.5",
  sparkle: "M12 4l1.6 4.6L18 10l-4.4 1.4L12 16l-1.6-4.6L6 10l4.4-1.4L12 4ZM18.5 16l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z",
  doc: "M6 3h8l4 4v14H6zM14 3v4h4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7.5V12l3 2",
  leaf: "M20 4c-8 0-14 3.6-14 10a6 6 0 0 0 .8 3M5 20C5 12 10.5 8.5 18 8",
};

export function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.7");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("class", className);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICON_PATHS[name] || ICON_PATHS.sparkle);
  svg.append(path);
  return svg;
}

export function cloverMark(size = 22) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("aria-hidden", "true");
  svg.style.color = "var(--clover)";
  for (const [cx, cy] of [[12, 7.5], [16.5, 12], [12, 16.5], [7.5, 12]]) {
    const petal = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    petal.setAttribute("cx", String(cx));
    petal.setAttribute("cy", String(cy));
    petal.setAttribute("r", "3.5");
    petal.setAttribute("fill", "currentColor");
    petal.setAttribute("opacity", "0.9");
    svg.append(petal);
  }
  return svg;
}

export function junoMark(large = false) {
  return el("span", { class: large ? "juno-mark juno-mark-lg" : "juno-mark" }, icon("leaf"));
}

export function dots() {
  return el("span", { class: "dots" }, el("i"), el("i"), el("i"));
}

// --- text --------------------------------------------------------------

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s<>()]+)/g;

function inlineNodes(text) {
  const out = [];
  for (const piece of text.split(INLINE)) {
    if (!piece) continue;
    if (piece.startsWith("**") && piece.endsWith("**") && piece.length > 4) {
      out.push(el("strong", { text: piece.slice(2, -2) }));
    } else if (piece.startsWith("`") && piece.endsWith("`") && piece.length > 2) {
      out.push(el("code", { text: piece.slice(1, -1) }));
    } else if (/^https?:\/\//.test(piece)) {
      out.push(el("a", { href: piece, target: "_blank", rel: "noreferrer", text: piece }));
    } else {
      out.push(document.createTextNode(piece));
    }
  }
  return out;
}

/** Render Juno's reply as safe DOM. Never uses innerHTML. */
export function prose(text) {
  const fragment = document.createDocumentFragment();
  const blocks = String(text || "").replace(/\r/g, "").split(/\n{2,}/);
  for (const block of blocks) {
    const lines = block.split("\n").filter((line) => line.trim());
    if (!lines.length) continue;
    if (lines.every((line) => /^\s*([-*_])\1{2,}\s*$/.test(line))) {
      fragment.append(el("hr", { class: "divider" }));
      continue;
    }
    const bulleted = lines.every((line) => /^\s*[-*•]\s+/.test(line));
    const numbered = lines.every((line) => /^\s*\d+[.)]\s+/.test(line));
    if (bulleted || numbered) {
      const list = el(numbered ? "ol" : "ul");
      for (const line of lines) {
        list.append(el("li", {}, inlineNodes(line.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ""))));
      }
      fragment.append(list);
      continue;
    }
    const paragraph = el("p");
    lines.forEach((line, index) => {
      if (index) paragraph.append(el("br"));
      append(paragraph, [inlineNodes(line)]);
    });
    fragment.append(paragraph);
  }
  return fragment;
}

export function when(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 365) return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return then.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

export function dateRange(start, end) {
  const format = (value) => {
    if (!value) return "";
    const parsed = new Date(value.length === 4 ? `${value}-01-01` : value);
    if (Number.isNaN(parsed.getTime())) return value;
    return value.length === 4 ? value : parsed.toLocaleDateString(undefined, { month: "short", year: "numeric" });
  };
  const from = format(start);
  const to = end ? format(end) : "now";
  if (!from && !end) return "";
  return `${from || "?"} – ${to}`;
}

// --- server ------------------------------------------------------------

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) {
    throw new Error(data.error || "Something didn't go through. Try again in a moment.");
  }
  return data;
}

export const api = {
  get: (path) => request(path, { headers: { Accept: "application/json" } }),
  post: (path, body) =>
    request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }),
};

/**
 * Send a message to Juno and receive her turn as it arrives.
 * Handlers: onActivity(text), onDelta(text), onBreak(), onEnd(result), onError(message).
 */
export async function sendToJuno({ message, opportunityId, handlers, signal }) {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, opportunityId: opportunityId || null }),
    signal,
  });
  if (!response.ok || !response.body) {
    handlers.onError?.("Juno couldn't be reached just now.");
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((part) => part.startsWith("data:"));
      if (!line) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (event.type === "delta") handlers.onDelta?.(event.text);
      else if (event.type === "activity") handlers.onActivity?.(event.text);
      else if (event.type === "break") handlers.onBreak?.();
      else if (event.type === "error") handlers.onError?.(event.message);
      else if (event.type === "end") handlers.onEnd?.(event);
    }
  }
}

export function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("That file couldn't be read."));
    reader.readAsDataURL(file);
  });
}

export function autoGrow(textarea) {
  const resize = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 190)}px`;
  };
  textarea.addEventListener("input", resize);
  requestAnimationFrame(resize);
  return resize;
}
