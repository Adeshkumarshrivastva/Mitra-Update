(() => {
  // Dashboard: reads the submissions saved by mindcheck.js, with search, filters, priority and follow-up tracking.
  const { maxScore } = window.MC;
  const { buildReport, istStamp, progress, TIER_LABEL } = window.MCReport;

  // Rows saved before the priority tier existed fall back to the band, so old data still sorts sensibly.
  function tierOf(row) {
    if (row.tier) return row.tier;
    if (row.band === "Severe" || row.band === "Moderately severe") return "urgent";
    return row.band === "Moderate" ? "elevated" : "normal";
  }

  function csvChange(row) {
    const moved = progress(row.prevScore, row.score);
    if (!moved) return "";
    if (moved.dir === "same") return "0";
    return moved.pct === null ? "up" : `${moved.dir === "better" ? "-" : "+"}${moved.pct}`;
  }

  const isDue = (row) => Boolean(row.followUpAt) && new Date(row.followUpAt).getTime() <= Date.now();

  // A spreadsheet runs any cell starting with = + - @ as a formula, so prefix a quote to keep it plain text.
  function csvCell(value) {
    const text = String(value ?? "");
    const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
    return `"${safe.replaceAll('"', '""')}"`;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  let rows = [];
  const search = document.getElementById("search");
  const tierFilter = document.getElementById("tierFilter");
  const kindFilter = document.getElementById("kindFilter");
  const dueFilter = document.getElementById("dueFilter");
  let visible = [];

  function renderStats() {
    const stats = [
      [rows.length, "Total screenings"],
      [rows.filter((r) => r.kind === "anxiety").length, "Anxiety / GAD-7"],
      [rows.filter((r) => r.kind === "depression").length, "Depression / PHQ-9"],
      [rows.filter((r) => tierOf(r) === "urgent").length, "Urgent"],
      [rows.filter(isDue).length, "Follow-up due"],
    ];
    const box = document.getElementById("stats");
    box.replaceChildren(...stats.map(([value, label]) => {
      const card = el("div");
      card.append(el("strong", "", String(value)), el("span", "", label));
      return card;
    }));
  }

  function applyFilters() {
    const query = search.value.trim().toLowerCase();
    visible = rows.filter((row) => {
      if (query && !`${row.name || ""} ${row.mobile || ""}`.toLowerCase().includes(query)) return false;
      if (tierFilter.value && tierOf(row) !== tierFilter.value) return false;
      if (kindFilter.value && row.kind !== kindFilter.value) return false;
      if (dueFilter.value === "due" && !isDue(row)) return false;
      return true;
    });
    renderRows();
  }

  function renderRows() {
    const tbody = document.getElementById("rows");
    tbody.replaceChildren();
    for (const row of visible) {
      const tr = document.createElement("tr");
      const person = el("td");
      person.append(el("strong", "", row.name || ""), document.createElement("br"), el("small", "", [row.mobile, row.email].filter(Boolean).join(" / ")));

      const tier = tierOf(row);
      const priority = el("td");
      priority.append(el("span", `dash-badge ${tier}`, TIER_LABEL[tier]));

      const follow = el("td");
      if (row.followUpAt) {
        const date = new Date(row.followUpAt).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
        follow.append(el("span", isDue(row) ? "dash-badge due" : "", isDue(row) ? `Due ${date}` : date));
      } else {
        follow.textContent = "-";
      }

      const change = el("td");
      const moved = progress(row.prevScore, row.score);
      if (!moved) change.textContent = "-";
      else if (moved.dir === "same") change.textContent = "No change";
      else change.append(el("span", `dash-badge ${moved.dir === "better" ? "" : "urgent"}`, `${moved.dir === "better" ? "\u25BC" : "\u25B2"} ${moved.pct === null ? "up" : `${moved.pct}%`}`));

      const report = el("td");
      const btn = el("button", "mc-secondary", "PDF");
      btn.type = "button";
      btn.addEventListener("click", async () => {
        // The stored report also holds the answers; fall back to the list row if it cannot be read.
        const full = (await window.MCStore.report(row.id)) || row;
        buildReport({
          kind: full.kind, name: full.name, email: full.email, mobile: full.mobile, score: full.score, band: full.band,
          distribution: full.distribution || [], dominant: full.expression || "", selfHarm: Boolean(full.selfHarm), createdAt: full.createdAt,
          answers: full.answers || [], tier: full.tier, followUpAt: full.followUpAt, prevScore: full.prevScore, prevBand: full.prevBand,
          prevAt: full.prevAt, insightText: full.insightText || "", safetyText: full.safetyText || "",
        }).then((pdf) => pdf.save(`screening-report-${(row.name || "participant").replace(/\W+/g, "-").toLowerCase()}.pdf`));
      });
      report.append(btn);

      tr.append(
        el("td", "", istStamp(row.createdAt)), el("td", "", row.kind), person,
        el("td", "", `${row.score}/${maxScore[row.kind] ?? 21}`), el("td", "", row.band), change, priority, follow,
        el("td", "", row.expression || "-"), el("td", "", typeof row.cameraPct === "number" ? `${row.cameraPct}%` : "-"), report,
      );
      tbody.append(tr);
    }
    const empty = document.getElementById("empty");
    empty.hidden = visible.length > 0;
    empty.textContent = rows.length ? "No submissions match these filters." : "No submissions yet. Complete a Mind Check to see it here.";
  }

  [search, tierFilter, kindFilter, dueFilter].forEach((control) => control.addEventListener("input", applyFilters));

  document.getElementById("exportCsv").addEventListener("click", () => {
    const header = "Date,Type,Name,Mobile,Email,Score,Band,Change vs previous %,Priority,Follow-up,Expression,Camera %\n";
    const csv = header + visible.map((r) => [
      istStamp(r.createdAt), r.kind, r.name, r.mobile, r.email, r.score, r.band, csvChange(r), TIER_LABEL[tierOf(r)],
      r.followUpAt ? new Date(r.followUpAt).toISOString().slice(0, 10) : "", r.expression, r.cameraPct,
    ].map(csvCell).join(",")).join("\n");
    const link = document.createElement("a");
    // The byte-order mark makes Excel read the file as UTF-8, so Devanagari names do not turn into mojibake.
    const url = URL.createObjectURL(new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" }));
    link.href = url;
    link.download = "screening-submissions.csv";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  });

  async function init() {
    const source = document.getElementById("source");
    const result = await window.MCStore.list();
    rows = result.items;
    source.textContent = "Showing what this browser has saved (no database is connected).";
    renderStats();
    applyFilters();
  }

  init();
})();
