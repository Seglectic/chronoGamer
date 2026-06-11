/* chronoGamer — retro game timeline browser */

// ─── Constants ───────────────────────────────────────────────────────────────

const SEARCH_DEBOUNCE  = 150;
const ROW_HEIGHT_GAME  = 46;
const ROW_HEIGHT_HDR   = 34;

const MANUFACTURERS = [
  { name: "Atari",    consoles: ["Atari 2600", "Atari 7800"] },
  { name: "Nintendo", consoles: ["NES", "Game Boy", "SNES", "N64", "Game Boy Color"] },
  { name: "Sega",     consoles: ["SMS", "Genesis", "Sega CD", "32X", "Saturn", "Dreamcast"] },
  { name: "NEC",      consoles: ["TurboGrafx-16"] },
  { name: "SNK",      consoles: ["Neo Geo"] },
  { name: "3DO",      consoles: ["3DO"] },
  { name: "Sony",     consoles: ["PlayStation"] },
];

const CONSOLE_COLORS = {
  "Atari 2600":    "#e03a3a",
  "Atari 7800":    "#c94040",
  "NES":           "#e60012",
  "SMS":           "#1a6bbf",
  "TurboGrafx-16": "#9e9e9e",
  "Game Boy":      "#8bac0f",
  "Genesis":       "#0077cc",
  "SNES":          "#9400d3",
  "Neo Geo":       "#ff8c00",
  "Sega CD":       "#005b9a",
  "3DO":           "#c8960c",
  "32X":           "#0099cc",
  "PlayStation":   "#0070d1",
  "Saturn":        "#3949ab",
  "N64":           "#e4000f",
  "Game Boy Color":"#f0a500",
  "Dreamcast":     "#e45c00",
};

// ─── State ───────────────────────────────────────────────────────────────────

const REGIONS = ["NA", "JP", "PAL"];

const REGION_LABELS = { NA: "NA", JP: "JP", PAL: "PAL" };

const state = {
  allGames:       [],
  allConsoles:    [],
  filtered:       [],
  activeConsoles: new Set(),
  activeRegions:  new Set(REGIONS),
  searchQuery:    "",
  dateFrom:       null,
  rows:           [],   // flat pre-computed [{type,data,offset}]
  yearOffsets:    {},
  totalHeight:    0,
};

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const scrollContainer   = document.getElementById("scroll-container");
const gameList          = document.getElementById("game-list");
const timelineBar       = document.getElementById("timeline-bar");
const timelineLabels    = document.getElementById("timeline-labels");
const timelineHandle    = document.getElementById("timeline-handle");
const regionFilters     = document.getElementById("region-filters");
const gameCount         = document.getElementById("game-count");
const loading           = document.getElementById("loading");
const wordmark          = document.getElementById("wordmark");
const toolbar           = document.getElementById("toolbar");
const filterToggle      = document.getElementById("filter-toggle");
const consoleBtnEl      = document.getElementById("console-btn");
const consoleModal      = document.getElementById("console-modal");
const consoleModalBody  = document.getElementById("console-modal-body");

// ─── Persistence ──────────────────────────────────────────────────────────────

const STORAGE_KEY = "chronogamer_prefs";

function savePrefs() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      activeConsoles:  [...state.activeConsoles],
      activeRegions:   [...state.activeRegions],
      searchQuery:     state.searchQuery,
      dateFrom:        state.dateFrom ? state.dateFrom.toISOString().slice(0, 10) : null,
      scrollTop:       scrollContainer.scrollTop,
      filtersOpen:     toolbar.classList.contains("filters-open"),
    }));
  } catch (_) {}
}

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"); }
  catch (_) { return null; }
}

// ─── Data loading ─────────────────────────────────────────────────────────────

async function loadGames() {
  const res = await fetch("games.json");
  state.allGames = await res.json();

  const consoles = [...new Set(state.allGames.map(g => g.console))].sort();
  state.allConsoles = consoles;
  const prefs = loadPrefs();

  if (prefs) {
    const validConsoles = new Set(consoles);
    state.activeConsoles = new Set((prefs.activeConsoles || []).filter(c => validConsoles.has(c)));
    state.activeRegions  = new Set((prefs.activeRegions  || []).filter(r => REGIONS.includes(r)));
    state.searchQuery    = prefs.searchQuery || "";
    state.dateFrom       = prefs.dateFrom ? new Date(prefs.dateFrom + "T00:00:00") : null;
    if (!state.activeConsoles.size) state.activeConsoles = new Set(consoles);
    if (!state.activeRegions.size)  state.activeRegions  = new Set(REGIONS);
  } else {
    state.activeConsoles = new Set(consoles);
  }

  buildConsoleModal(consoles);
  buildRegionFilters();

  if (prefs?.searchQuery)  document.getElementById("search-input").value = prefs.searchQuery;
  if (prefs?.dateFrom)     document.getElementById("date-from").value    = prefs.dateFrom;
  setFiltersOpen(prefs?.filtersOpen ?? true);

  initTimeline();
  applyFilters();

  if (prefs?.scrollTop) {
    scrollContainer.scrollTop = prefs.scrollTop;
    syncTimelineHandle();
    positionTimelineLabels();
  }

  loading.style.display = "none";
}

// ─── Filtering & rendering ────────────────────────────────────────────────────

function applyFilters() {
  const q       = state.searchQuery.toLowerCase();
  const fromISO = state.dateFrom ? state.dateFrom.toISOString().slice(0, 10) : null;

  state.filtered = state.allGames.filter(g => {
    if (!state.activeConsoles.has(g.console)) return false;
    if (fromISO && g.releaseDate < fromISO) return false;
    if (q && !g.title.toLowerCase().includes(q)) return false;
    const gameRegions = g.regions || ["NA"];
    if (!gameRegions.some(r => state.activeRegions.has(r))) return false;
    return true;
  });

  gameCount.textContent = state.filtered.length.toLocaleString() + " games";
  updateConsoleBtnLabel();
  renderList();
  syncTimelineHandle();
  savePrefs();
}

// ─── Virtual scroller ────────────────────────────────────────────────────────

const OVERSCAN_PX = 600;
let renderedRange = { start: 0, end: 0 };

function buildRowIndex() {
  const rows = [];
  const yearOffsets = {};
  let offset = 0;
  let lastYear = null;

  for (const g of state.filtered) {
    const year = g.releaseDate.slice(0, 4);
    if (year !== lastYear) {
      yearOffsets[year] = offset;
      rows.push({ type: "header", year, offset });
      offset += ROW_HEIGHT_HDR;
      lastYear = year;
    }
    rows.push({ type: "game", game: g, offset });
    offset += ROW_HEIGHT_GAME;
  }

  state.rows = rows;
  state.yearOffsets = yearOffsets;
  state.totalHeight = offset;
  gameList.style.height = offset + "px";
}

function renderVisible() {
  const scrollTop  = scrollContainer.scrollTop;
  const viewHeight = scrollContainer.clientHeight;
  const top        = scrollTop - OVERSCAN_PX;
  const bottom     = scrollTop + viewHeight + OVERSCAN_PX;
  const rows       = state.rows;

  // Binary search for first row in the window
  let lo = 0, hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const r   = rows[mid];
    const rh  = r.type === "header" ? ROW_HEIGHT_HDR : ROW_HEIGHT_GAME;
    if (r.offset + rh <= top) lo = mid + 1; else hi = mid;
  }
  const start = lo;
  let end = start;
  while (end < rows.length && rows[end].offset < bottom) end++;

  if (start === renderedRange.start && end === renderedRange.end) return;
  renderedRange = { start, end };

  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const r  = rows[i];
    const el = r.type === "header" ? createHeaderRow(r.year) : createGameRow(r.game);
    el.style.top = r.offset + "px";
    frag.appendChild(el);
  }
  gameList.textContent = "";
  gameList.appendChild(frag);
}

function renderList() {
  buildRowIndex();
  renderedRange = { start: -1, end: -1 }; // force fresh render
  renderVisible();
  positionTimelineLabels();
}

function createHeaderRow(year) {
  const row = document.createElement("div");
  row.className = "year-header";
  row.dataset.year = year;
  row.textContent = year;
  return row;
}

function createGameRow(game) {
  const row = document.createElement("div");
  row.className = "game-row";

  const dateEl = document.createElement("span");
  dateEl.className = "col-date";
  dateEl.textContent = formatDate(game.releaseDate);

  const badge = document.createElement("span");
  badge.className = "console-badge col-console";
  badge.textContent = game.console;
  badge.style.setProperty("--badge-color", CONSOLE_COLORS[game.console] || "#888");

  const titleEl = document.createElement("span");
  titleEl.className = "col-title";
  titleEl.textContent = game.title;

  row.appendChild(dateEl);
  row.appendChild(badge);
  row.appendChild(titleEl);
  return row;
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const month = months[parseInt(m, 10) - 1];
  if (d === "01" && iso.endsWith("-01")) return `${month} ${y}`;
  return `${month} ${parseInt(d, 10)}, ${y}`;
}

// ─── Timeline slider ─────────────────────────────────────────────────────────
//
// Labels are placed at even year intervals (1977–2000).
// The handle and drag both work in that same even year-space so clicking
// on "1991" actually scrolls to 1991, not to 61% of content height.
//
// yearToBarFrac  : year  → 0-1 even position on the bar
// scrollToBarFrac: scrollTop → 0-1 by interpolating between known year offsets
// barFracToScroll: 0-1 bar fraction → scrollTop by reverse interpolation

const YEAR_MIN = 1977;
const YEAR_MAX = 2000;

function yearToBarFrac(year) {
  return (year - YEAR_MIN) / (YEAR_MAX - YEAR_MIN);
}

function sortedYears() {
  return Object.keys(state.yearOffsets).map(Number).sort((a, b) => a - b);
}

// Converts current scrollTop → bar fraction in even year-space
function scrollToBarFrac() {
  const scrollTop = scrollContainer.scrollTop;
  const years = sortedYears();
  if (!years.length) return 0;

  // Find the last year whose offset is ≤ scrollTop
  let loIdx = 0;
  for (let i = 0; i < years.length; i++) {
    if (state.yearOffsets[years[i]] <= scrollTop + 1) loIdx = i;
    else break;
  }
  const hiIdx = Math.min(loIdx + 1, years.length - 1);
  if (loIdx === hiIdx) return yearToBarFrac(years[loIdx]);

  const loYear = years[loIdx], hiYear = years[hiIdx];
  const loOff  = state.yearOffsets[loYear], hiOff = state.yearOffsets[hiYear];
  const t = hiOff === loOff ? 0 : (scrollTop - loOff) / (hiOff - loOff);
  return yearToBarFrac(loYear) + t * (yearToBarFrac(hiYear) - yearToBarFrac(loYear));
}

// Converts a bar fraction (drag position) → scrollTop via year interpolation
function barFracToScroll(frac) {
  const yearF = YEAR_MIN + frac * (YEAR_MAX - YEAR_MIN);
  const years = sortedYears();
  if (!years.length) return 0;

  // Find surrounding known years
  let loYear = years[0];
  for (const y of years) {
    if (y <= yearF) loYear = y;
  }
  const loIdx = years.indexOf(loYear);
  const hiIdx = Math.min(loIdx + 1, years.length - 1);
  if (loIdx === hiIdx) return state.yearOffsets[loYear];

  const hiYear = years[hiIdx];
  const t = (yearF - loYear) / (hiYear - loYear);
  return state.yearOffsets[loYear] + t * (state.yearOffsets[hiYear] - state.yearOffsets[loYear]);
}

function initTimeline() {
  for (let year = YEAR_MIN; year <= YEAR_MAX; year++) {
    const label = document.createElement("span");
    label.className = "tl-label";
    label.dataset.year = year;
    label.textContent = year;
    label.addEventListener("click", e => {
      e.stopPropagation();
      const offset = state.yearOffsets[String(year)];
      if (offset !== undefined) scrollContainer.scrollTop = offset;
    });
    timelineLabels.appendChild(label);
  }

  timelineBar.addEventListener("pointerdown", startDrag);

  timelineHandle.addEventListener("keydown", e => {
    const delta = e.key === "ArrowUp" ? -1 : e.key === "ArrowDown" ? 1 : 0;
    if (!delta) return;
    e.preventDefault();
    const next = currentYear() + delta;
    const offset = state.yearOffsets[String(next)];
    if (offset !== undefined) scrollContainer.scrollTop = offset;
  });
}

function positionTimelineLabels() {
  const labels = timelineLabels.querySelectorAll(".tl-label");
  const handleFrac = scrollToBarFrac();

  for (const label of labels) {
    const year    = parseInt(label.dataset.year, 10);
    const evenPos = yearToBarFrac(year);
    label.style.top     = (evenPos * 100) + "%";
    label.style.display = "";

    const dist = Math.abs(evenPos - handleFrac);
    const t    = Math.max(0, 1 - dist / 0.15); // 0→1 as dist→0
    label.style.fontSize = (8 + t * 7) + "px"; // 8px → 15px near handle
    label.style.opacity  = 0.4 + t * 0.6;
  }
}

function currentYear() {
  const scrollTop = scrollContainer.scrollTop;
  let best = null;
  for (const [year, offset] of Object.entries(state.yearOffsets)) {
    if (offset <= scrollTop + 1) {
      if (best === null || offset > state.yearOffsets[best]) best = year;
    }
  }
  return best ? parseInt(best, 10) : YEAR_MIN;
}

function syncTimelineHandle() {
  const pct = scrollToBarFrac() * 100;
  timelineHandle.style.top = pct + "%";
  const year = currentYear();
  timelineHandle.setAttribute("aria-valuenow", year);
  timelineHandle.setAttribute("aria-valuetext", year);
}

function railPctFromY(clientY) {
  const rect = timelineBar.getBoundingClientRect();
  return Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
}

function startDrag(e) {
  e.preventDefault();
  timelineBar.setPointerCapture(e.pointerId);

  scrollContainer.scrollTop = barFracToScroll(railPctFromY(e.clientY));

  function onMove(ev) {
    scrollContainer.scrollTop = barFracToScroll(railPctFromY(ev.clientY));
  }

  function onUp() {
    timelineBar.removeEventListener("pointermove", onMove);
    timelineBar.removeEventListener("pointerup", onUp);
  }

  timelineBar.addEventListener("pointermove", onMove);
  timelineBar.addEventListener("pointerup", onUp);
}

// ─── Region filters ──────────────────────────────────────────────────────────

function buildRegionFilters() {
  regionFilters.textContent = "";
  for (const region of REGIONS) {
    const label = document.createElement("label");
    label.className = "region-filter-item";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.activeRegions.has(region);
    cb.dataset.region = region;
    cb.addEventListener("change", () => {
      if (cb.checked) state.activeRegions.add(region);
      else state.activeRegions.delete(region);
      applyFilters();
    });

    const pill = document.createElement("span");
    pill.className = "region-pill";
    pill.dataset.region = region;
    pill.textContent = REGION_LABELS[region];

    label.appendChild(cb);
    label.appendChild(pill);
    regionFilters.appendChild(label);
  }
}

// ─── Console modal ────────────────────────────────────────────────────────────

function updateConsoleBtnLabel() {
  const n = state.activeConsoles.size;
  const total = state.allConsoles.length;
  consoleBtnEl.textContent = `Consoles (${n})`;
  consoleBtnEl.classList.toggle("has-filter", n < total);
}

function buildConsoleModal(consoles) {
  const consoleSet = new Set(consoles);
  consoleModalBody.textContent = "";

  for (const mfr of MANUFACTURERS) {
    const mfrConsoles = mfr.consoles.filter(c => consoleSet.has(c));
    if (!mfrConsoles.length) continue;

    const group = document.createElement("div");
    group.className = "mfr-group";

    const header = document.createElement("div");
    header.className = "mfr-header";

    const nameEl = document.createElement("span");
    nameEl.className = "mfr-name";
    nameEl.textContent = mfr.name;

    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = "mfr-toggle-btn";

    const refreshToggleBtn = () => {
      const allOn = mfrConsoles.every(c => state.activeConsoles.has(c));
      toggleBtn.textContent = allOn ? "None" : "All";
    };
    refreshToggleBtn();

    toggleBtn.addEventListener("click", () => {
      const allOn = mfrConsoles.every(c => state.activeConsoles.has(c));
      mfrConsoles.forEach(c => {
        if (allOn) state.activeConsoles.delete(c);
        else state.activeConsoles.add(c);
      });
      group.querySelectorAll("input[type=checkbox]").forEach(cb => {
        cb.checked = state.activeConsoles.has(cb.dataset.console);
      });
      refreshToggleBtn();
      updateConsoleBtnLabel();
      applyFilters();
    });

    header.appendChild(nameEl);
    header.appendChild(toggleBtn);

    const consolesRow = document.createElement("div");
    consolesRow.className = "mfr-consoles";

    for (const c of mfrConsoles) {
      const label = document.createElement("label");
      label.className = "console-filter-item";

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.activeConsoles.has(c);
      cb.dataset.console = c;
      cb.addEventListener("change", () => {
        if (cb.checked) state.activeConsoles.add(c);
        else state.activeConsoles.delete(c);
        refreshToggleBtn();
        updateConsoleBtnLabel();
        applyFilters();
      });

      const badge = document.createElement("span");
      badge.className = "console-badge";
      badge.textContent = c;
      badge.style.setProperty("--badge-color", CONSOLE_COLORS[c] || "#888");

      label.appendChild(cb);
      label.appendChild(badge);
      consolesRow.appendChild(label);
    }

    group.appendChild(header);
    group.appendChild(consolesRow);
    consoleModalBody.appendChild(group);
  }

  updateConsoleBtnLabel();
}

function openConsoleModal() {
  consoleModal.classList.add("open");
  document.getElementById("console-modal-close").focus();
}

function closeConsoleModal() {
  consoleModal.classList.remove("open");
  consoleBtnEl.focus();
}

consoleBtnEl.addEventListener("click", openConsoleModal);
document.getElementById("console-modal-close").addEventListener("click", closeConsoleModal);
document.getElementById("console-all-btn").addEventListener("click", () => {
  state.allConsoles.forEach(c => state.activeConsoles.add(c));
  consoleModalBody.querySelectorAll("input[type=checkbox]").forEach(cb => { cb.checked = true; });
  consoleModalBody.querySelectorAll(".mfr-toggle-btn").forEach(btn => { btn.textContent = "None"; });
  updateConsoleBtnLabel();
  applyFilters();
});
document.getElementById("console-none-btn").addEventListener("click", () => {
  state.activeConsoles.clear();
  consoleModalBody.querySelectorAll("input[type=checkbox]").forEach(cb => { cb.checked = false; });
  consoleModalBody.querySelectorAll(".mfr-toggle-btn").forEach(btn => { btn.textContent = "All"; });
  updateConsoleBtnLabel();
  applyFilters();
});
consoleModal.addEventListener("click", e => {
  if (e.target === consoleModal) closeConsoleModal();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && consoleModal.classList.contains("open")) closeConsoleModal();
});

// ─── Search & date filter events ─────────────────────────────────────────────

let searchTimer = null;
document.getElementById("search-input").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.searchQuery = e.target.value.trim();
    applyFilters();
  }, SEARCH_DEBOUNCE);
});

document.getElementById("date-from").addEventListener("change", e => {
  const v = e.target.value;
  state.dateFrom = v ? new Date(v + "T00:00:00") : null;
  applyFilters();
});

// ─── Filter panel toggle (mobile) ────────────────────────────────────────────

function setFiltersOpen(open) {
  toolbar.classList.toggle("filters-open", open);
  filterToggle.classList.toggle("active", open);
  filterToggle.setAttribute("aria-expanded", open);
}

filterToggle.addEventListener("click", () => {
  setFiltersOpen(!toolbar.classList.contains("filters-open"));
  savePrefs();
});

// ─── Logo → scroll to top ─────────────────────────────────────────────────────

wordmark.addEventListener("click", () => {
  scrollContainer.scrollTop = 0;
});

// ─── Scroll listener ─────────────────────────────────────────────────────────

let scrollSaveTimer = null;
scrollContainer.addEventListener("scroll", () => {
  renderVisible();
  syncTimelineHandle();
  positionTimelineLabels();
  clearTimeout(scrollSaveTimer);
  scrollSaveTimer = setTimeout(savePrefs, 300);
}, { passive: true });

// ─── Boot ─────────────────────────────────────────────────────────────────────

loadGames();
