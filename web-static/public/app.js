// Thin UI glue over the deterministic TypeScript pipeline. The only requests this
// page makes are for same-origin, static corpus assets; questions never leave the tab.
import { loadAssistant, answerCitations } from "./assets/index.js";

const loadStatus = document.getElementById("load-status");
const askForm = document.getElementById("ask-form");
const examples = document.getElementById("examples");
const evidencePanel = document.querySelector(".evidence-panel");
const answerHeading = document.getElementById("answer-h");
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
    loadStatus.hidden = true;
    askForm.hidden = false;
    examples.hidden = false;
    evidencePanel.setAttribute("aria-busy", "false");
    answerHeading.textContent = "Evidence appears here";
    statusEl.textContent =
      "Ask a question to see the supported sentences, citations, confidence, and safety routing.";
  } catch (err) {
    evidencePanel.setAttribute("aria-busy", "false");
    answerHeading.textContent = "Corpus unavailable";
    statusEl.textContent = "The local reference data could not be prepared.";
    loadStatus.textContent =
      "Could not load the cited corpus. Try reloading this page. " +
      String(err && err.message ? err.message : err);
  }
}

function selectedLanguage() {
  const checked = askForm.querySelector('input[name="lang"]:checked');
  return checked?.value === "es" ? "es" : "en";
}

function resetOutput() {
  answerEl.replaceChildren();
  citationsEl.replaceChildren();
  safetyEl.hidden = true;
  safetyEl.textContent = "";
  sourcesWrap.hidden = true;
  metaEl.textContent = "";
}

function renderCitation(citation) {
  const text = `${citation.title} — ${citation.source} (as of ${citation.fetch_date})`;
  if (citation.url?.startsWith("http")) {
    const link = document.createElement("a");
    link.href = citation.url;
    link.textContent = text;
    link.rel = "noreferrer";
    return link;
  }
  return document.createTextNode(text);
}

function render(question) {
  if (!question) return;

  evidencePanel.setAttribute("aria-busy", "true");
  resetOutput();
  const answer = assistant.answer(question, selectedLanguage());

  if (answer.refused) {
    answerHeading.textContent = "Honest refusal";
    statusEl.textContent = "The corpus did not support an answer.";
    const refusal = document.createElement("p");
    refusal.textContent = answer.refusal_text ?? "The cited corpus cannot support this answer.";
    answerEl.appendChild(refusal);
  } else {
    answerHeading.textContent = "Verified answer";
    statusEl.textContent = "Every rendered sentence passed the citation guard.";
    for (const sentence of answer.sentences) {
      const paragraph = document.createElement("p");
      paragraph.append(document.createTextNode(`${sentence.text} `));
      const marker = document.createElement("span");
      marker.className = "cite-marker";
      marker.append("[");
      marker.append(renderCitation(sentence.citation));
      marker.append("]");
      paragraph.append(marker);
      answerEl.appendChild(paragraph);
    }
  }

  if (answer.safety_notice) {
    safetyEl.textContent = answer.safety_notice;
    safetyEl.hidden = false;
  }

  const citations = answerCitations(answer);
  for (const citation of citations) {
    const item = document.createElement("li");
    item.append(renderCitation(citation));
    citationsEl.appendChild(item);
  }
  sourcesWrap.hidden = citations.length === 0;

  const confidence = `${Math.round(answer.confidence * 100)}% confidence${
    answer.low_confidence ? " · low" : ""
  }`;
  const references = answer.as_of ? `References current through ${answer.as_of}` : "No supporting reference";
  metaEl.textContent = `${confidence} · ${references} · ${answer.disclosure}`;
  evidencePanel.setAttribute("aria-busy", "false");
}

askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (assistant) render(qInput.value.trim());
});

examples.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-q]");
  if (!button || !assistant) return;
  const language = askForm.querySelector(`input[name="lang"][value="${button.dataset.lang}"]`);
  if (language) language.checked = true;
  qInput.value = button.dataset.q;
  render(button.dataset.q);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js").catch(() => {
      // Offline support is progressive enhancement and never blocks the reference UI.
    });
  });
}

init();
