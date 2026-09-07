// How Juno currently understands you. Not settings, and not a database — a
// readable summary the user can correct.

import { junoNote } from "./components.js";
import { api, clear, dateRange, el, icon, junoMark, prose, readFileAsBase64 } from "./lib.js";

export async function renderProfile(root, nav) {
  const page = el("div", { class: "page" });
  const inner = el("div", { class: "page-inner stack stack-5" });
  page.append(inner);
  clear(root).append(page);

  const data = await api.get("/api/profile");
  const reload = () => nav.go("profile");

  inner.append(
    el(
      "div",
      { class: "stack stack-2" },
      el("h1", { text: data.preferredName ? `${data.preferredName}, as I understand it` : "How I understand you" }),
      el("div", {
        class: "lead",
        text: "If something here is wrong, say so — correcting me is quicker than starting over.",
      })
    )
  );

  if (data.isEmpty) {
    inner.append(
      junoNote(
        [
          "I don't know much about you yet, and I'd rather ask than guess.",
          "Give me your resume, or just tell me about the last job you had and what you thought of it.",
        ],
        [
          uploadButton(reload, "Add your resume"),
          el("button", {
            class: "btn",
            type: "button",
            text: "Tell Juno instead",
            onClick: () => nav.askJuno("Let me tell you about my background."),
          }),
        ]
      )
    );
    return;
  }

  // What Juno has been told
  for (const section of data.sections) {
    const list = el("div", { class: "stack" });
    for (const item of section.items) {
      list.append(
        el(
          "div",
          { class: "understanding-item" },
          el("div", { style: "min-width: 0", text: item.text }),
          el("div", { class: "spacer" }),
          el("button", {
            class: "btn btn-quiet",
            type: "button",
            title: "Remove this",
            "aria-label": "Remove this",
            text: "Not right",
            onClick: async () => {
              await api.post(`/api/profile/facts/${item.id}/dismiss`, {});
              reload();
            },
          })
        )
      );
    }
    inner.append(
      el("div", { class: "stack stack-3" }, el("div", { class: "eyebrow", text: section.label }), list)
    );
  }

  // Background
  if (data.experiences.length) {
    const list = el("div", { class: "stack stack-3" });
    for (const item of data.experiences) {
      list.append(
        el(
          "div",
          { class: "card-quiet stack", style: "gap: 4px" },
          el(
            "div",
            { class: "row" },
            el("strong", { text: item.title || item.organization }),
            el("div", { class: "spacer" }),
            el("span", { class: "small faint", text: dateRange(item.startDate, item.endDate) })
          ),
          item.title && item.organization ? el("div", { class: "small muted", text: item.organization }) : null,
          item.narrative ? el("div", { class: "small muted", text: item.narrative }) : null
        )
      );
    }
    inner.append(
      el("div", { class: "stack stack-3" }, el("div", { class: "eyebrow", text: "Your background" }), list)
    );
  }

  if (data.skills.length) {
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "What you can do" }),
        el(
          "div",
          { class: "row row-wrap", style: "gap: 7px" },
          data.skills.map((skill) => el("span", { class: "tag", text: skill }))
        )
      )
    );
  }

  // Juno's unconfirmed reads on the user
  const hunches = data.observations.filter((item) => !item.confirmed);
  const confirmed = data.observations.filter((item) => item.confirmed);

  if (hunches.length) {
    const list = el("div", { class: "stack stack-3" });
    for (const item of hunches) {
      list.append(
        el(
          "div",
          { class: "hunch stack stack-3" },
          el("div", { class: "row", style: "align-items: flex-start; gap: 12px" }, junoMark(), el("div", { class: "prose" }, prose(item.claim))),
          el(
            "div",
            { class: "actions" },
            el("button", {
              class: "btn",
              type: "button",
              text: "That's right",
              onClick: async () => {
                await api.post(`/api/profile/observations/${item.id}/review`, { verdict: "confirmed" });
                reload();
              },
            }),
            el("button", {
              class: "btn btn-quiet",
              type: "button",
              text: "Not quite",
              onClick: async () => {
                await api.post(`/api/profile/observations/${item.id}/review`, { verdict: "rejected" });
                reload();
              },
            })
          )
        )
      );
    }
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "Things I think I'm seeing" }),
        el("div", {
          class: "small muted",
          text: "These are guesses, not facts. They only shape how I help you if you confirm them.",
        }),
        list
      )
    );
  }

  if (confirmed.length) {
    inner.append(
      el(
        "div",
        { class: "stack stack-3" },
        el("div", { class: "eyebrow", text: "What you've confirmed" }),
        el(
          "div",
          { class: "stack" },
          confirmed.map((item) =>
            el(
              "div",
              { class: "understanding-item" },
              icon("check", "icon-sm"),
              el("div", { text: item.claim })
            )
          )
        )
      )
    );
  }

  // Documents
  inner.append(
    el(
      "div",
      { class: "stack stack-3" },
      el("div", { class: "eyebrow", text: "On file" }),
      data.documents.length
        ? el(
            "div",
            { class: "stack" },
            data.documents.map((doc) =>
              el(
                "div",
                { class: "understanding-item" },
                icon("doc", "icon-sm"),
                el("div", { text: doc.filename }),
                el("div", { class: "spacer" }),
                // Only worth saying when something is wrong with the file.
                // "Read" would also read as a claim Juno has studied it.
                doc.hasText
                  ? null
                  : el("span", { class: "small faint", text: "saved, but I couldn't read this one" })
              )
            )
          )
        : el("div", { class: "muted small", text: "No resume on file yet." }),
      el("div", { class: "row row-wrap" }, uploadButton(reload, data.documents.length ? "Replace resume" : "Add your resume"))
    )
  );
}

function uploadButton(reload, label) {
  const file = el("input", {
    type: "file",
    accept: ".pdf,.docx,.txt,.md,.rtf",
    style: "display: none",
  });
  const status = el("span", { class: "small faint" });
  const button = el("button", {
    class: "btn",
    type: "button",
    text: label,
    onClick: () => file.click(),
  });
  file.addEventListener("change", async () => {
    const chosen = file.files?.[0];
    if (!chosen) return;
    status.textContent = "Reading…";
    try {
      const result = await api.post("/api/documents", {
        filename: chosen.name,
        content: await readFileAsBase64(chosen),
      });
      status.textContent = result.readable ? "" : "Couldn't read that one.";
      reload();
    } catch (problem) {
      status.textContent = problem.message;
    }
  });
  return el("span", { class: "row" }, file, button, status);
}
