/* Where Mind Check screenings are kept: this browser's localStorage only (no database, for now).
   Used by the Mind Check screen and the dashboard. */
window.MCStore = (() => {
  const LOCAL_KEY = "mws-submissions";
  const LAST_MOBILE_KEY = "mws-last-mobile";

  const digits = (value) => String(value || "").replace(/\D/g, "").slice(-10);

  function readLocal() {
    try {
      const rows = JSON.parse(localStorage.getItem(LOCAL_KEY) || "[]");
      return Array.isArray(rows) ? rows : [];
    } catch { return []; }
  }

  function writeLocal(rows) {
    try { localStorage.setItem(LOCAL_KEY, JSON.stringify(rows)); } catch { /* private mode or quota */ }
  }

  function rememberMobile(mobile) {
    try { localStorage.setItem(LAST_MOBILE_KEY, String(mobile || "")); } catch { /* optional convenience */ }
  }

  function lastMobile() {
    try { return localStorage.getItem(LAST_MOBILE_KEY) || ""; } catch { return ""; }
  }

  // Older rows were saved without a priority tier; derive it from the band the way the dashboard always did.
  function withTier(row) {
    if (row.tier) return row;
    const tier = row.band === "Severe" || row.band === "Moderately severe" ? "urgent" : row.band === "Moderate" ? "elevated" : "normal";
    return { ...row, tier };
  }

  /** Saves one screening in this browser. */
  async function save(row) {
    rememberMobile(row.mobile);
    writeLocal([row, ...readLocal()]);
    return { source: "browser", id: null };
  }

  /** Nothing extra is stored without a database; the list row is enough for the report. */
  async function saveDetails() { return false; }

  async function report() { return null; }

  /** The newest earlier screening of the same test by the same person (same last 10 digits of the mobile), or null. */
  async function previous(kind, mobile) {
    return readLocal().find((row) => row && row.kind === kind && typeof row.score === "number" && digits(row.mobile) === digits(mobile)) || null;
  }

  /** The newest screening of this person, whichever test it was. */
  async function latest(mobile) {
    if (digits(mobile).length !== 10) return null;
    return readLocal().find((row) => row && digits(row.mobile) === digits(mobile)) || null;
  }

  /** All screenings saved in this browser, newest first. */
  async function list() {
    return { items: readLocal().map(withTier), source: "browser" };
  }

  return { save, saveDetails, report, previous, latest, list, lastMobile };
})();
