// Sprout chat UI — dependency-free. Consumes the sentence-grained SSE stream so the
// live region only ever announces citation-verified text, never ungrounded text it
// would have to retract. Severity/provenance are conveyed in words, not colour alone.
"use strict";

(function () {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("q");
  const statusEl = document.getElementById("status");
  const answerEl = document.getElementById("answer");
  const safetyEl = document.getElementById("safety");
  const sourcesWrap = document.getElementById("sources-wrap");
  const citationsEl = document.getElementById("citations");
  const metaEl = document.getElementById("meta");
  const askBtn = document.getElementById("ask-btn");
  let source = null;

  function selectedLanguage() {
    const checked = document.querySelector('input[name="lang"]:checked');
    return checked ? checked.value : "en";
  }

  function reset() {
    if (source) { source.close(); source = null; }
    answerEl.textContent = "";
    citationsEl.textContent = "";
    metaEl.textContent = "";
    safetyEl.hidden = true;
    safetyEl.textContent = "";
    sourcesWrap.hidden = true;
  }

  function addCitation(label, url) {
    for (const li of citationsEl.children) {
      if (li.dataset.label === label) return;
    }
    const li = document.createElement("li");
    li.dataset.label = label;
    if (url && /^https?:\/\//.test(url)) {
      const a = document.createElement("a");
      a.href = url;
      a.textContent = label;
      a.rel = "noopener noreferrer";
      li.appendChild(a);
    } else {
      li.textContent = label;
    }
    citationsEl.appendChild(li);
    sourcesWrap.hidden = false;
  }

  function ask(question) {
    reset();
    askBtn.disabled = true;
    statusEl.textContent = "Searching the cited corpus…";
    const url = "/api/chat/stream?q=" + encodeURIComponent(question) +
      "&language=" + encodeURIComponent(selectedLanguage());
    source = new EventSource(url);

    source.addEventListener("sentence", function (e) {
      const data = JSON.parse(e.data);
      const p = document.createElement("p");
      p.textContent = data.text + " ";
      const marker = document.createElement("span");
      marker.className = "cite-marker";
      marker.textContent = "[" + data.citation + "]";
      p.appendChild(marker);
      answerEl.appendChild(p);
      addCitation(data.citation, data.url);
      statusEl.textContent = "";
    });

    source.addEventListener("refusal", function (e) {
      const data = JSON.parse(e.data);
      const p = document.createElement("p");
      p.textContent = data.text;
      answerEl.appendChild(p);
      statusEl.textContent = "";
    });

    source.addEventListener("safety", function (e) {
      const data = JSON.parse(e.data);
      safetyEl.textContent = data.text;
      safetyEl.hidden = false;
    });

    source.addEventListener("done", function (e) {
      const data = JSON.parse(e.data);
      const bits = [];
      if (typeof data.confidence === "number") {
        bits.push("Confidence " + data.confidence.toFixed(2) +
          (data.low_confidence && !data.refused ? " (low — consider a second source)" : ""));
      }
      if (data.as_of) bits.push("Based on references as of " + data.as_of);
      if (data.disclosure) bits.push(data.disclosure);
      metaEl.textContent = bits.join(" · ");
      statusEl.textContent = "";
      askBtn.disabled = false;
      if (source) { source.close(); source = null; }
    });

    source.onerror = function () {
      statusEl.textContent = "Something went wrong reaching the assistant. Please try again.";
      askBtn.disabled = false;
      if (source) { source.close(); source = null; }
    };
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const q = input.value.trim();
    if (q) ask(q);
  });

  document.getElementById("examples").addEventListener("click", function (e) {
    const btn = e.target.closest("button[data-q]");
    if (!btn) return;
    input.value = btn.dataset.q;
    input.focus();
    ask(btn.dataset.q);
  });

  // --- Photo identification ---------------------------------------------------
  const photoForm = document.getElementById("photo-form");
  const photoInput = document.getElementById("photo");
  const photoQ = document.getElementById("photo-q");
  const photoStatus = document.getElementById("photo-status");
  const photoLabel = document.getElementById("photo-label");
  const photoAnswer = document.getElementById("photo-answer");
  const photoSafety = document.getElementById("photo-safety");
  const photoSourcesWrap = document.getElementById("photo-sources-wrap");
  const photoCitations = document.getElementById("photo-citations");
  const photoBtn = document.getElementById("photo-btn");

  function readAsBase64(file) {
    return new Promise(function (resolve, reject) {
      const reader = new FileReader();
      reader.onload = function () {
        const result = String(reader.result || "");
        const comma = result.indexOf(",");
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  function renderPhoto(data) {
    photoAnswer.textContent = "";
    photoCitations.textContent = "";
    photoSourcesWrap.hidden = true;
    photoSafety.hidden = true;
    photoSafety.textContent = "";
    if (!data.identified || !data.answer) {
      photoLabel.textContent = "";
      const p = document.createElement("p");
      p.textContent = data.message || "Could not identify the plant from the photo.";
      photoAnswer.appendChild(p);
      return;
    }
    photoLabel.textContent = data.label || "";
    const ans = data.answer;
    const p = document.createElement("p");
    p.textContent = ans.display_text;
    photoAnswer.appendChild(p);
    if (ans.safety_notice) {
      photoSafety.textContent = ans.safety_notice;
      photoSafety.hidden = false;
    }
    (ans.citations || []).forEach(function (c) {
      const li = document.createElement("li");
      if (c.url && /^https?:\/\//.test(c.url)) {
        const a = document.createElement("a");
        a.href = c.url;
        a.textContent = c.label;
        a.rel = "noopener noreferrer";
        li.appendChild(a);
      } else {
        li.textContent = c.label;
      }
      photoCitations.appendChild(li);
      photoSourcesWrap.hidden = false;
    });
  }

  if (photoForm) {
    photoForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const file = photoInput.files && photoInput.files[0];
      if (!file) { photoStatus.textContent = "Please choose a photo first."; return; }
      photoBtn.disabled = true;
      photoStatus.textContent = "Identifying the plant…";
      readAsBase64(file).then(function (b64) {
        return fetch("/api/identify", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            image_b64: b64,
            question: photoQ.value.trim() || null,
            language: selectedLanguage()
          })
        });
      }).then(function (r) { return r.json(); }).then(function (data) {
        photoStatus.textContent = "";
        renderPhoto(data);
      }).catch(function () {
        photoStatus.textContent = "Something went wrong identifying the photo. Please try again.";
      }).then(function () { photoBtn.disabled = false; });
    });
  }

  // --- Reminders --------------------------------------------------------------
  const reminderForm = document.getElementById("reminder-form");
  const reminderStatus = document.getElementById("reminder-status");
  const remindersBody = document.getElementById("reminders-body");
  const remindersEmpty = document.getElementById("reminders-empty");

  function renderReminders(reminders) {
    remindersBody.textContent = "";
    if (!reminders.length) { remindersEmpty.hidden = false; return; }
    remindersEmpty.hidden = true;
    reminders.forEach(function (r) {
      const tr = document.createElement("tr");
      [r.plant, r.kind, "every " + r.interval_days + "d", r.next_due].forEach(function (text) {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      });
      const actions = document.createElement("td");
      const done = document.createElement("button");
      done.type = "button";
      done.textContent = "Mark done";
      done.addEventListener("click", function () { completeReminder(r.reminder_id); });
      const del = document.createElement("button");
      del.type = "button";
      del.className = "ghost";
      del.textContent = "Remove";
      del.setAttribute("aria-label", "Remove " + r.kind + " reminder for " + r.plant);
      del.addEventListener("click", function () { removeReminder(r.reminder_id); });
      actions.appendChild(done);
      actions.appendChild(del);
      tr.appendChild(actions);
      remindersBody.appendChild(tr);
    });
  }

  function loadReminders() {
    fetch("/api/reminders").then(function (r) { return r.json(); }).then(function (data) {
      renderReminders(data.reminders || []);
    }).catch(function () { /* offline build: leave the empty message */ });
  }

  function completeReminder(id) {
    fetch("/api/reminders/" + encodeURIComponent(id) + "/complete", { method: "POST" })
      .then(function () { reminderStatus.textContent = "Marked done and rescheduled."; loadReminders(); });
  }

  function removeReminder(id) {
    fetch("/api/reminders/" + encodeURIComponent(id), { method: "DELETE" })
      .then(function () { reminderStatus.textContent = "Reminder removed."; loadReminders(); });
  }

  if (reminderForm) {
    reminderForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const plant = document.getElementById("r-plant").value.trim();
      if (!plant) { reminderStatus.textContent = "Please enter a plant."; return; }
      fetch("/api/reminders", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          plant: plant,
          kind: document.getElementById("r-kind").value,
          interval_days: parseInt(document.getElementById("r-every").value, 10) || null,
          language: selectedLanguage()
        })
      }).then(function (r) { return r.json(); }).then(function () {
        reminderStatus.textContent = "Reminder added.";
        document.getElementById("r-plant").value = "";
        loadReminders();
      }).catch(function () { reminderStatus.textContent = "Could not add the reminder."; });
    });
    loadReminders();
  }
})();
