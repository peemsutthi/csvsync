// UI glue only: no network or filesystem logic. Python (main/app.py) does the work
// and pushes events here through onEvent(); every call back goes via pywebview.api.
"use strict";

const $ = (id) => document.getElementById(id);
const MAC = /Mac/.test(navigator.userAgent);
const DEFAULT_NAME = "downloaded_google_sheet";
const LOG_ROWS = 500;          // a week-long loop must not grow the page without bound
const ICON = {
  ok: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7"/></svg>',
  err: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.5v4M8 11.2v.1"/></svg>',
};
const ALERT_TITLE = {
  private: "This sheet isn't shared publicly",
  input: "Check the sheet and tab",
  http: "Google couldn't open that sheet",
  timeout: "Google didn't answer in time",
  network: "Couldn't reach Google",
  write: "Couldn't save the file",
  unexpected: "Something went wrong",
};

let api = null;
let state = "setup";
let folder = "";               // the full path; the well shows Python's short form
let folderDisplay = "";
let interval = 10;
let custom = false;            // the Custom segment is picked; interval comes from its field
const MAX_INTERVAL = 86400;    // = config.MAX_INTERVAL
let tab = "";                  // the chosen tab; kept even while the select can't show it
let tabs = null;               // the link's tab list, once known
let tabsHint = "";             // what an empty select says
let lookupTimer = null;
let lastSaved = null;          // "HH:MM:SS" of this session's latest save
let run = null;                // the sync in progress: {tab, interval, started, stopping, failure}
let deadline = null;           // epoch ms of the next fetch, from the "wait" event

// --- small helpers -----------------------------------------------------------
function fileName() {
  const name = $("filename").value.trim() || DEFAULT_NAME;
  return name.replace(/\.csv$/i, "") + ".csv";
}

function form() {
  return { sheet_id: $("link").value, tab: tab, filename: $("filename").value,
           folder: folder, interval: interval };
}

function save() { api.save_settings(form()); }

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;   // never innerHTML: names come from Google
  return node;
}

// A note line under a field: kind is "ok", "err", or "" (muted). Text is never HTML.
function note(id, kind, text) {
  const p = $(id);
  p.replaceChildren();
  p.hidden = !text;
  if (!text) return;
  p.className = "note " + kind;
  if (ICON[kind]) p.insertAdjacentHTML("beforeend", ICON[kind]);
  if (Array.isArray(text)) {       // [prose, mono, prose …]
    const span = el("span");
    text.forEach((part, i) => span.append(i % 2 ? el("span", "mono", part) : part));
    p.append(span);
  } else {
    p.append(el("span", "", text));
  }
}

function invalid(id, on) {
  const field = $(id);
  if (on) field.setAttribute("aria-invalid", "true");
  else field.removeAttribute("aria-invalid");
}

function clearFieldErrors() {
  for (const id of ["link", "tab", "folder", "custom-seconds"]) invalid(id, false);
  note("custom-note", "", "");
  if ($("link-note").classList.contains("err")) note("link-note", "", "");
  $("tab").disabled = false;           // a private sheet's "Tabs show once…" placeholder
  renderTabs();
  note("tab-note", "", "");
  note("folder-note", "", "");
  $("action-note").hidden = true;
}

// --- header --------------------------------------------------------------------
function setState(next, word) {
  state = next;
  document.body.dataset.state = next;
  const words = { setup: "ready", downloading: "downloading…", running: "syncing", error: "failed" };
  const marks = { setup: "hollow", downloading: "pulse", running: "filled", error: "error" };
  word = word || words[next];
  $("status").dataset.mark = word === "saved" ? "ok" : marks[next];
  $("word").textContent = word;
  const showSaved = lastSaved && (next === "downloading" || next === "running");
  $("subtitle").textContent = showSaved ? "Last saved " + lastSaved : "";
  $("primary").textContent = next === "error" ? "Try Again" : interval === 0 ? "Fetch Now" : "Start Sync";
  renderBar();
}

// --- setup: tabs ---------------------------------------------------------------
// The saved tab is always kept as an option, even when the sheet doesn't list it:
// swapping it for another would quietly sync a tab nobody picked.
function renderTabs() {
  const select = $("tab");
  const names = tabs || [];
  select.replaceChildren();
  if (tab && !names.includes(tab)) {
    select.append(new Option(tabs ? tab + " (not in this sheet)" : tab, tab));
  }
  for (const name of names) select.append(new Option(name, name));
  if (!select.options.length) {
    const empty = new Option(tabsHint || (tabs ? "No tabs found" : "Paste a link first"), "");
    empty.disabled = true;
    select.append(empty);
  }
  select.value = tab;
}

function scheduleLookup() {
  clearTimeout(lookupTimer);
  tabs = null;                         // the old sheet's tabs no longer apply
  tabsHint = $("link").value.trim() ? "Looking up tabs…" : "";
  $("tab").disabled = false;
  invalid("link", false);
  note("link-note", "", "");
  renderTabs();
  lookupTimer = setTimeout(lookup, 600);
}

async function lookup() {
  lookupTimer = null;
  const link = $("link").value.trim();
  if (!link) return;
  note("link-note", "", "Looking up the sheet…");
  let info;
  try { info = await api.sheet_info(link); }
  catch (e) { info = { kind: "unexpected", message: String(e) }; }
  if (link !== $("link").value.trim()) return;      // an answer for a link since edited
  showLookup(info);
}

function showLookup(info) {
  if (info.kind) {
    tabs = null;
    tabsHint = "Tabs unavailable";
    const blamesLink = info.kind === "private" || info.kind === "http";
    invalid("link", blamesLink);
    note("link-note", blamesLink ? "err" : "", info.message);
    $("tab").disabled = info.kind === "private";
    if (info.kind === "private") {
      $("tab").replaceChildren(new Option("Tabs show once the sheet is public", ""));
    } else {
      renderTabs();
    }
    return;
  }
  tabs = info.tabs;
  tabsHint = "";
  $("tab").disabled = false;
  invalid("link", false);
  const count = tabs.length + (tabs.length === 1 ? " tab" : " tabs");
  note("link-note", "ok", info.title ? ["Sheet found: ", info.title, " · " + count] : "Sheet found · " + count);
  // Fill only an empty tab, never replace a chosen one.
  const filled = !tab && tabs.length > 0;
  if (filled) tab = tabs[0];
  renderTabs();
  if (filled) save();
}

// --- setup: save to, schedule ---------------------------------------------------
function renderSaves() {
  const p = $("saves");
  p.replaceChildren();
  $("folder").value = folder ? folderDisplay : "";
  $("folder").placeholder = "No folder chosen";
  $("folder").title = folder;
  if (!folder) {
    p.append("Choose a folder for ", el("code", "", fileName()), ".");
    return;
  }
  const sep = folderDisplay.includes("\\") ? "\\" : "/";
  const base = folderDisplay.endsWith(sep) ? folderDisplay : folderDisplay + sep;
  p.append("Saves ", el("code", "", base + fileName()), " and a backup in ", el("code", "", "data" + sep));
}

async function chooseFolder() {
  if (state !== "setup" && state !== "error") return;
  const chosen = await api.choose_folder();
  if (!chosen) return;
  folder = chosen.path;
  folderDisplay = chosen.display;
  invalid("folder", false);
  note("folder-note", "", "");
  renderSaves();
  save();
}

function renderInterval() {
  for (const button of document.querySelectorAll(".segments button")) {
    const on = button.dataset.interval === "custom" ? custom : !custom && Number(button.dataset.interval) === interval;
    button.setAttribute("aria-pressed", String(on));
  }
  $("custom-row").hidden = !custom;
  if (state === "setup") $("primary").textContent = interval === 0 ? "Fetch Now" : "Start Sync";
}

// The Custom field's seconds, or null while it doesn't hold 1…MAX_INTERVAL.
function customSeconds() {
  const n = Number($("custom-seconds").value);
  return /^\d+$/.test($("custom-seconds").value) && n >= 1 && n <= MAX_INTERVAL ? n : null;
}

// Digits only: anything else is dropped as it is typed or pasted, and the note says why.
function applyCustom() {
  const field = $("custom-seconds");
  const digits = field.value.replace(/\D/g, "");
  const stripped = digits !== field.value;
  field.value = digits;
  const seconds = customSeconds();
  invalid("custom-seconds", digits !== "" && seconds === null);
  note("custom-note", stripped || (digits && seconds === null) ? "err" : "",
       stripped ? "Numbers only." : digits && seconds === null ? "Enter 1–" + MAX_INTERVAL + " seconds." : "");
  if (seconds === null) return;
  interval = seconds;
  renderInterval();
  save();
}

// --- start / stop ----------------------------------------------------------------
async function start() {
  if ((state !== "setup" && state !== "error") || $("primary").disabled) return;
  clearFieldErrors();
  if (custom && customSeconds() === null) {
    invalid("custom-seconds", true);
    note("custom-note", "err", "Enter 1–" + MAX_INTERVAL + " seconds.");
    $("custom-seconds").focus();
    return;
  }
  const settings = form();
  // Set up before asking: the worker's first events can arrive before start() returns.
  run = { tab: settings.tab, interval: settings.interval, started: false, stopping: false, failure: null };
  $("sum-tab").textContent = settings.tab;
  $("sum-file").textContent = fileName();
  $("sum-folder").textContent = folderDisplay;
  $("primary").disabled = true;
  let answer;
  try { answer = await api.start(settings); }
  catch (e) { answer = { ok: false, field: null, message: String(e) }; }
  $("primary").disabled = false;
  if (!answer.ok) {
    run = null;
    refuse(answer.field, answer.message);
    return;
  }
  $("sum-file").textContent = answer.file;
  $("sum-folder").textContent = answer.folder;
  $("summary").setAttribute("aria-label", answer.summary);
}

// Say why Start did nothing, and put the cursor where the fix goes.
function refuse(field, message) {
  const target = { link: "link", tab: "tab", folder: "folder" }[field];
  if (!target) {
    $("action-note").textContent = message;
    $("action-note").hidden = false;
    return;
  }
  invalid(target, true);
  note(target + "-note", "err", message);
  $(target === "folder" ? "choose" : target).focus();
}

function stop() {
  if (!run || run.stopping || (state !== "downloading" && state !== "running")) return;
  run.stopping = true;
  $("stop").disabled = true;
  api.stop();
}

// --- events from Python ------------------------------------------------------------
function addRow(at, verb, detail) {
  const row = el("li");
  row.append(el("time", "", at), el("span", verb, verb), el("span", "detail", detail));
  const log = $("log");
  log.prepend(row);                  // newest first, so the latest is always in view
  while (log.children.length > LOG_ROWS) log.lastChild.remove();
}

function clock() { return new Date().toTimeString().slice(0, 8); }

window.onEvent = function (event) {
  if (!run) return;
  switch (event.type) {
    case "downloading":
      if (!run.started) {
        run.started = true;
        const every = run.interval ? "every " + run.interval + " s" : "once";
        addRow(clock(), "fetch", run.tab + " → " + $("sum-file").textContent + ", " + every);
        $("stop").disabled = false;
      }
      if (!run.stopping) setState("downloading");
      break;
    case "saved":
      lastSaved = event.at;
      run.failure = null;
      addRow(event.at, "saved", event.path.split(/[\\/]/).pop());
      $("open-file").disabled = $("reveal").disabled = false;
      $("subtitle").textContent = "Last saved " + lastSaved;
      break;
    case "failed":
      run.failure = event;
      addRow(event.at, "failed", event.message);
      break;
    case "wait":
      deadline = event.deadline_ms;
      run.interval = event.interval;
      if (!run.stopping) setState("running");
      break;
    case "done": {
      const finished = run;
      run = null;
      deadline = null;
      if (finished.stopping) setState("setup");
      else if (finished.failure) showError(finished.failure);
      else setState("setup", "saved");
      $("primary").focus({ preventScroll: true });   // the Stop button that had focus is gone
      window.scrollTo(0, 0);         // the alert and status word, not the button, come first
      break;
    }
  }
};

function showError(failure) {
  const isPrivate = failure.kind === "private";
  $("alert-title").textContent = ALERT_TITLE[failure.kind] || ALERT_TITLE.unexpected;
  $("alert-body").textContent = isPrivate
    ? "csvSync can only read sheets that anyone with the link can view. Your file was not changed."
    // A write error may have landed the live file and failed on the backup, so no promise.
    : failure.message + (failure.kind === "write" ? "" : " Your file was not changed.");
  $("alert-steps").hidden = $("open-sheet").hidden = !isPrivate;
  clearFieldErrors();
  if (isPrivate) {
    showLookup({ kind: "private", message: failure.message });
  } else if (failure.kind === "http") {
    invalid("link", true);
    note("link-note", "err", failure.message);
  } else if (failure.kind === "input") {
    invalid("tab", true);
    note("tab-note", "err", failure.message);
  } else if (failure.kind === "write" || failure.kind === "unexpected") {
    invalid("folder", true);
    note("folder-note", "err", failure.message);
  }
  setState("error");
}

// --- the countdown bar ------------------------------------------------------------
function renderBar() {
  const bar = $("bar"), fill = bar.firstElementChild;
  const every = run && run.interval ? "every " + run.interval + " s" : "";
  $("bar-right").textContent = every;
  if (state === "downloading") {
    bar.removeAttribute("aria-valuenow");
    fill.style.width = "";
    $("bar-left").textContent = "Downloading tab " + (run ? run.tab : "") + " from Google Sheets…";
  } else if (state === "running" && deadline) {
    const total = run.interval * 1000;
    const left = Math.max(0, deadline - Date.now());
    const done = Math.round(100 * (1 - Math.min(1, left / total)));
    fill.style.width = done + "%";
    bar.setAttribute("aria-valuenow", String(done));
    $("bar-left").textContent = "Next sync in " + Math.ceil(left / 1000) + " s";
  }
}
setInterval(() => { if (state === "running") renderBar(); }, 200);

// --- menu and keys ------------------------------------------------------------------
window.onMenu = function (name) {
  if (!api) return;
  const setupLike = state === "setup" || state === "error";
  switch (name) {
    case "settings":
      if (setupLike) $("link").focus(); else $("stop").focus();
      break;
    case "start": start(); break;
    case "stop": stop(); break;
    case "open": if (!$("open-file").disabled) api.open_file(); break;
    case "reveal": if (!$("reveal").disabled) api.show_in_folder(); break;
    case "folder": chooseFolder(); break;
  }
};

// macOS gets these from native menu key equivalents (main/__main__.py); Windows menus
// can't carry shortcuts through pywebview, so the page handles Ctrl+key itself.
// preventDefault also stops WebView2's own Ctrl+R reload.
const KEYS = { ",": "settings", "r": "start", ".": "stop", "o": "open", "R": "reveal", "O": "folder" };

document.addEventListener("keydown", (e) => {
  if (e.isComposing) return;         // Enter that confirms an IME candidate isn't a submit
  if (!MAC && e.ctrlKey && !e.altKey && !e.metaKey) {
    const key = e.shiftKey ? e.key.toUpperCase() : e.key.toLowerCase();
    if (KEYS[key]) {
      e.preventDefault();
      onMenu(KEYS[key]);
      return;
    }
  }
  // Return triggers the default button, except where Return already means something.
  if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey &&
      !e.target.closest("button, select, a, .log")) {
    if (state === "setup" || state === "error") { e.preventDefault(); start(); }
  }
});

// --- wiring ---------------------------------------------------------------------------
async function init() {
  api = window.pywebview.api;
  if (!MAC) $("reveal").textContent = "Show in Folder";
  const settings = await api.load_settings();
  $("link").value = settings.sheet_id;
  $("filename").value = settings.filename;
  folder = settings.folder;
  folderDisplay = settings.folder_display;
  interval = settings.interval;
  custom = ![...document.querySelectorAll(".segments button")].some((b) => Number(b.dataset.interval) === interval);
  if (custom) $("custom-seconds").value = interval;
  tab = settings.tab;
  tabsHint = settings.sheet_id.trim() ? "Looking up tabs…" : "";
  renderTabs();
  renderSaves();
  renderInterval();
  setState("setup");

  // Saved on every edit, not on blur: closing the window must not lose what was typed.
  $("link").addEventListener("input", () => { scheduleLookup(); save(); });
  $("tab").addEventListener("change", () => {
    tab = $("tab").value;
    invalid("tab", false);
    note("tab-note", "", "");
    renderTabs();                    // drops a "(not in this sheet)" entry once moved off
    save();
  });
  $("filename").addEventListener("input", () => { renderSaves(); save(); });
  $("choose").addEventListener("click", chooseFolder);
  $("primary").addEventListener("click", start);
  $("stop").addEventListener("click", stop);
  $("open-file").addEventListener("click", () => api.open_file());
  $("reveal").addEventListener("click", () => api.show_in_folder());
  $("open-sheet").addEventListener("click", () => api.open_sheet($("link").value));
  for (const button of document.querySelectorAll(".segments button")) {
    button.addEventListener("click", () => {
      if (button.dataset.interval === "custom") {
        custom = true;
        if (!$("custom-seconds").value && interval) $("custom-seconds").value = interval;
        renderInterval();
        applyCustom();                 // a value typed earlier becomes the interval again
        $("custom-seconds").focus();
        return;
      }
      custom = false;
      invalid("custom-seconds", false);
      note("custom-note", "", "");
      interval = Number(button.dataset.interval);
      renderInterval();
      save();
    });
  }
  $("custom-seconds").addEventListener("input", applyCustom);
  if (settings.sheet_id.trim()) lookup();
  $("link").focus();
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init, { once: true });
