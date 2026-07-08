// Thin UI glue over the TypeScript pipeline (compiled to ./assets/*.js by `npm run
// build:site`). No framework, matching the framework-free ethos of `web/dist/app.js` —
// this file only wires DOM events to `Assistant.answer()` and renders the result.
import { loadAssistant, answerText, answerDisplayText, answerCitations } from "./assets/index.js";

const loadStatus = document.getElementById("load-status");
const askForm = document.getElementById("ask-form");
const examplesSection = document.getElementById("examples-section");
const qInput = document.getElementById("q");
const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const safetyEl = document.getElementById("safety");
const sourcesWrap = document.getElementById("sources-wrap");
const citationsEl = document.getElementById("citations");
const metaEl = document.getElementById("meta");

let assistant = null;

async function init() {
  try {
    assistant = await loadAssistant("./data/");
    loadStatus.textContent = "";
    loadStatus.hidden = true;
    askForm.hidden = false;
    examplesSection.hidden = false;
    qInput.focus();
  } catch (err) {
    loadStatus.textContent =
      "Could not load the corpus index (data/index.json, data/config.json). " +
      "If you're developing locally, run `make web-static-bundle` first. " +
      String(err && err.message ? err.message : err);
  }
}

function selectedLanguage() {
  const checked = askForm.querySelector('input[name="lang"]:checked');
  const value = checked ? checked.value : "";
  return value === "" ? null : value;
}

function render(question) {
  const language = selectedLanguage();
  const answer = assistant.answer(question, language);

  statusEl.textContent = answer.refused ? "No cited answer found." : "Answered.";
  answerEl.textContent = answerDisplayText(answer);

  if (answer.safety_notice) {
    safetyEl.textContent = answer.safety_notice;
    safetyEl.hidden = false;
  } else {
    safetyEl.hidden = true;
    safetyEl.textContent = "";
  }

  const citations = answerCitations(answer);
  citationsEl.innerHTML = "";
  if (citations.length > 0) {
    for (const c of citations) {
      const li = document.createElement("li");
      li.textContent = `${c.title} — ${c.source} (as of ${c.fetch_date})`;
      citationsEl.appendChild(li);
    }
    sourcesWrap.hidden = false;
  } else {
    sourcesWrap.hidden = true;
  }

  const bits = [];
  if (answer.as_of) {
    bits.push(`Based on references as of ${answer.as_of}.`);
  }
  bits.push(`[confidence ${answer.confidence.toFixed(2)}${answer.low_confidence ? " · low" : ""}]`);
  bits.push(answer.disclosure);
  metaEl.textContent = bits.join(" ");

  // `answerText` is available for programmatic/debug use (devtools console) even though
  // the UI renders `answerDisplayText`, which also includes the safety notice.
  void answerText;
}

askForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (!assistant) return;
  render(qInput.value.trim());
});

document.getElementById("examples").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-q]");
  if (!btn || !assistant) return;
  qInput.value = btn.dataset.q;
  render(btn.dataset.q);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {
      // Installability is a progressive enhancement; a registration failure (e.g. this
      // page served over plain http in local dev) must never block asking a question.
    });
  });
}

init();
