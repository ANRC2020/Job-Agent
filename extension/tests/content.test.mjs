import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const here = path.dirname(fileURLToPath(import.meta.url));
const extensionRoot = path.resolve(here, "..");
const script = await readFile(path.join(extensionRoot, "content.js"), "utf8");

async function fixture(name) {
  return readFile(path.join(here, "fixtures", `${name}.html`), "utf8");
}

async function companion(name) {
  const dom = new JSDOM(await fixture(name), {
    runScripts: "outside-only",
    url: `https://${name}.example.test/jobs/42`,
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.HTMLElement.prototype.getBoundingClientRect = () => ({
    width: 200, height: 30, top: 0, left: 0, right: 200, bottom: 30,
  });
  window.CSS ||= {};
  window.CSS.escape ||= (value) => String(value).replace(/["\\]/g, "\\$&");
  Object.defineProperty(window.HTMLInputElement.prototype, "files", {
    configurable: true,
    get() { return this.__testFiles || []; },
    set(value) { this.__testFiles = value; },
  });
  window.DataTransfer = class {
    constructor() {
      this.files = [];
      this.items = { add: (file) => this.files.push(file) };
    }
  };
  window.HTMLFormElement.prototype.checkValidity = () => true;
  let listener;
  window.chrome = {
    runtime: {
      onMessage: {
        addListener(value) {
          listener = value;
        },
      },
    },
  };
  window.eval(script);
  return {
    dom,
    window,
    send(message) {
      let result;
      listener(message, {}, (response) => { result = response; });
      return result;
    },
  };
}

test("extracts useful fields across representative ATS fixtures", async () => {
  const expected = {
    greenhouse: ["Full name", "Why Acme?"],
    lever: ["Name", "Additional information"],
    workday: ["Portfolio URL", "Cover letter"],
    generic: ["Current employer", "What interests you about this role?", "Country"],
  };
  for (const [name, labels] of Object.entries(expected)) {
    const instance = await companion(name);
    const page = instance.send({ type: "CAPTURE_PAGE" });
    assert.deepEqual(Array.from(page.fields, (field) => field.label), labels, name);
    assert.ok(!page.fields.some((field) => /ssn|password|veteran|consent/i.test(field.label)));
    instance.dom.window.close();
  }
});

test("fills only empty safe fields, dispatches events, and never submits", async () => {
  const instance = await companion("generic");
  const page = instance.send({ type: "CAPTURE_PAGE" });
  const byLabel = Object.fromEntries(page.fields.map((field) => [field.label, field.fieldId]));
  let inputEvents = 0;
  let submissions = 0;
  instance.window.document.querySelector("#motivation").addEventListener("input", () => inputEvents++);
  instance.window.document.querySelector("main").addEventListener("submit", () => submissions++);

  const result = instance.send({
    type: "FILL_FIELDS",
    suggestions: [
      { fieldId: byLabel["Current employer"], value: "Overwrite attempt" },
      { fieldId: byLabel["What interests you about this role?"], value: "Grounded answer" },
      { fieldId: byLabel.Country, value: "United States" },
      { fieldId: "missing", value: "Ignored" },
    ],
  });

  assert.equal(result.filled, 2);
  assert.equal(instance.window.document.querySelector("#existing").value, "AnySoft");
  assert.equal(instance.window.document.querySelector("#motivation").value, "Grounded answer");
  assert.equal(instance.window.document.querySelector("#country").value, "US");
  assert.equal(inputEvents, 1);
  assert.equal(submissions, 0);
  assert.equal(instance.window.document.querySelector("#motivation").dataset.cloverFilled, "true");
  instance.dom.window.close();
});

test("undo restores values and navigation clears the undo history", async () => {
  const instance = await companion("generic");
  let page = instance.send({ type: "CAPTURE_PAGE" });
  const motivation = page.fields.find((field) => field.label.includes("interests"));
  instance.send({
    type: "FILL_FIELDS",
    suggestions: [{ fieldId: motivation.fieldId, value: "Temporary answer" }],
  });
  assert.equal(instance.send({ type: "UNDO_FILL" }).restored, 1);
  assert.equal(instance.window.document.querySelector("#motivation").value, "");

  instance.send({
    type: "FILL_FIELDS",
    suggestions: [{ fieldId: motivation.fieldId, value: "Second answer" }],
  });
  instance.window.history.pushState({}, "", "/jobs/43");
  page = instance.send({ type: "CAPTURE_PAGE" });
  assert.equal(page.url, "https://generic.example.test/jobs/43");
  assert.equal(instance.send({ type: "UNDO_FILL" }).restored, 0);
  instance.dom.window.close();
});

test("uploads a resume without exposing file paths and undo clears it", async () => {
  const instance = await companion("generic");
  const result = instance.send({
    type: "UPLOAD_FILE",
    file: {
      filename: "resume.pdf",
      mimeType: "application/pdf",
      content: instance.window.btoa("resume bytes"),
    },
  });

  assert.equal(result.uploaded, true);
  assert.equal(instance.window.document.querySelector("#resume").files[0].name, "resume.pdf");
  assert.equal(instance.send({ type: "UNDO_FILL" }).restored, 1);
  assert.equal(instance.window.document.querySelector("#resume").files.length, 0);
  instance.dom.window.close();
});

test("submits once only after required fields are complete", async () => {
  const instance = await companion("generic");
  let submissions = 0;
  instance.window.document.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();
    submissions += 1;
  });

  const blocked = instance.send({
    type: "SUBMIT_APPLICATION",
    actionId: "approval-1",
    expectedUrl: "https://generic.example.test/jobs/42",
  });
  assert.equal(blocked.clicked, false);

  const page = instance.send({ type: "CAPTURE_PAGE" });
  const byLabel = Object.fromEntries(page.fields.map((field) => [field.label, field.fieldId]));
  instance.send({
    type: "FILL_FIELDS",
    suggestions: [
      { fieldId: byLabel["What interests you about this role?"], value: "Grounded answer" },
      { fieldId: byLabel.Country, value: "United States" },
    ],
  });
  instance.send({
    type: "UPLOAD_FILE",
    file: {
      filename: "resume.pdf",
      mimeType: "application/pdf",
      content: instance.window.btoa("resume bytes"),
    },
  });
  instance.window.document.querySelector("input[name='consent']").checked = true;
  instance.window.document.querySelector("form").noValidate = true;
  const submitted = instance.send({
    type: "SUBMIT_APPLICATION",
    actionId: "approval-2",
    expectedUrl: "https://generic.example.test/jobs/42",
  });
  const replayed = instance.send({
    type: "SUBMIT_APPLICATION",
    actionId: "approval-2",
    expectedUrl: "https://generic.example.test/jobs/42",
  });

  assert.equal(submitted.clicked, true);
  assert.equal(replayed.clicked, false);
  assert.equal(submissions, 1);
  instance.dom.window.close();
});
