// Sprout's stateless reference surface. Sentence-grained SSE means the live region
// only receives citation-verified text; ungrounded text is never streamed and retracted.
"use strict";

(function () {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("q");
  const statusEl = document.getElementById("status");
  const answerEl = document.getElementById("answer");
  const answerHeading = document.getElementById("answer-h");
  const evidencePanel = document.querySelector(".evidence-panel");
  const safetyEl = document.getElementById("safety");
  const disagreementsEl = document.getElementById("disagreements");
  const sourcesWrap = document.getElementById("sources-wrap");
  const citationsEl = document.getElementById("citations");
  const metaEl = document.getElementById("meta");
  const askBtn = document.getElementById("ask-btn");
  let source = null;

  function selectedLanguage() {
    const checked = document.querySelector('input[name="lang"]:checked');
    return checked ? checked.value : "en";
  }

  function setBusy(isBusy) {
    evidencePanel.setAttribute("aria-busy", String(isBusy));
    askBtn.disabled = isBusy;
  }

  function resetResult() {
    if (source) {
      source.close();
      source = null;
    }
    answerEl.textContent = "";
    citationsEl.textContent = "";
    metaEl.textContent = "";
    safetyEl.hidden = true;
    safetyEl.textContent = "";
    disagreementsEl.hidden = true;
    disagreementsEl.textContent = "";
    sourcesWrap.hidden = true;
    answerHeading.textContent = "Checking the evidence";
  }

  function addCitation(label, url) {
    for (const item of citationsEl.children) {
      if (item.dataset.label === label) return;
    }

    const item = document.createElement("li");
    item.dataset.label = label;
    if (url && /^https?:\/\//.test(url)) {
      const link = document.createElement("a");
      link.href = url;
      link.textContent = label;
      link.rel = "noopener noreferrer";
      item.appendChild(link);
    } else {
      item.textContent = label;
    }
    citationsEl.appendChild(item);
    sourcesWrap.hidden = false;
  }

  function ask(question) {
    resetResult();
    setBusy(true);
    statusEl.textContent = "Searching the dated corpus and verifying each sentence…";

    const url = "/api/chat/stream?q=" + encodeURIComponent(question) +
      "&language=" + encodeURIComponent(selectedLanguage());
    source = new EventSource(url);

    source.addEventListener("sentence", function (event) {
      const data = JSON.parse(event.data);
      const paragraph = document.createElement("p");
      paragraph.textContent = data.text + " ";

      const marker = document.createElement("span");
      marker.className = "cite-marker";
      marker.textContent = "[" + data.citation + "]";
      paragraph.appendChild(marker);
      answerEl.appendChild(paragraph);

      addCitation(data.citation, data.url);
      answerHeading.textContent = "Verified answer";
      statusEl.textContent = "";
    });

    source.addEventListener("refusal", function (event) {
      const data = JSON.parse(event.data);
      const paragraph = document.createElement("p");
      paragraph.textContent = data.text;
      answerEl.appendChild(paragraph);
      answerHeading.textContent = "Honest refusal";
      statusEl.textContent = "The corpus did not support an answer.";
    });

    source.addEventListener("safety", function (event) {
      const data = JSON.parse(event.data);
      safetyEl.textContent = data.text;
      safetyEl.hidden = false;
    });

    // EXP-02: when retrieved sources give a conflicting numeric care cadence, both
    // citations are rendered here plainly rather than one being silently dropped.
    source.addEventListener("disagreement", function (e) {
      const data = JSON.parse(e.data);
      const p = document.createElement("p");
      p.textContent = data.text;
      disagreementsEl.appendChild(p);
      disagreementsEl.hidden = false;
    });

    source.addEventListener("done", function (event) {
      const data = JSON.parse(event.data);
      const details = [];
      if (typeof data.confidence === "number") {
        details.push("Confidence " + data.confidence.toFixed(2) +
          (data.low_confidence && !data.refused ? " — low; check another source" : ""));
      }
      if (data.as_of) details.push("References current to " + data.as_of);
      if (data.disclosure) details.push(data.disclosure);
      metaEl.textContent = details.join(" · ");
      setBusy(false);
      if (source) {
        source.close();
        source = null;
      }
    });

    source.onerror = function () {
      answerHeading.textContent = "Reference unavailable";
      statusEl.textContent = "The answer service could not be reached. Check the server and try again.";
      setBusy(false);
      if (source) {
        source.close();
        source = null;
      }
    };
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const question = input.value.trim();
    if (question) ask(question);
  });

  document.getElementById("examples").addEventListener("click", function (event) {
    const button = event.target.closest("button[data-q]");
    if (!button) return;
    input.value = button.dataset.q;
    ask(button.dataset.q);
  });
})();
