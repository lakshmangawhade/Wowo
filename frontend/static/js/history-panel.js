/* history-panel.js — TagForge run history */
const HistoryPanel = (() => {
  let visible  = false;
  let openStage = null;
  let openRun   = null;

  function init() {
    const toggle = document.querySelector(".sidebar-history-title");
    if (toggle) toggle.addEventListener("click", togglePanel);
  }

  function toggle() { togglePanel(); }

  function togglePanel() {
    visible = !visible;
    const panel = document.getElementById("history-panel");
    if (!panel) return;
    panel.style.display = visible ? "block" : "none";
    if (visible) render();
  }

  async function render() {
    const panel = document.getElementById("history-panel");
    if (!panel) return;
    try {
      const d = await API.getVersions();

      if (!d.versions || d.versions.length === 0) {
        panel.innerHTML = `<div style="font-size:11px;color:var(--text3);padding:4px 0">No run history yet.</div>`;
        return;
      }

      // Group by km_stage → run_id
      const byStage = {};
      d.versions.forEach(v => {
        const stage = v.km_stage || "unknown";
        const rid   = v.run_id   || "legacy";
        if (!byStage[stage])       byStage[stage] = {};
        if (!byStage[stage][rid])  byStage[stage][rid] = [];
        byStage[stage][rid].push(v);
      });

      const STAGE_LABELS = {
        "km_01a_specific_topic_family_router": "Router",
        "km_01z_specific_topic_reconciler":    "Reconciler",
        "km_02_applicable_sectors":            "Sectors",
        "km_03_esrs_mapping":                  "ESRS",
        "km_04_orchestrator_extraction":       "Extraction",
      };

      panel.innerHTML = Object.keys(byStage).sort().map(stage => {
        const runs     = byStage[stage];
        const runIds   = Object.keys(runs).sort();
        const isOpenS  = openStage === stage;
        const label    = STAGE_LABELS[stage] || stage;

        const runRows = isOpenS ? runIds.map((rid, idx) => {
          const versions    = runs[rid];
          const last        = versions[versions.length - 1];
          const status      = last.run_status || "completed";
          const statusCol   = status === "completed" ? "var(--green)" : "var(--amber)";
          const statusText  = status === "completed" ? "✓ Done" : "⏸ Stopped";
          const timestamp   = (last.saved_at || "").slice(0, 16);
          const bestVal     = Math.max(...versions.map(v => v.val_score || 0));
          const isOpenR     = openRun === rid;

          const downloadBtn = isOpenR ? `
            <div style="padding:4px 8px 4px">
              <button class="btn btn-accent" style="width:100%;font-size:11px;padding:5px 8px"
                onclick="HistoryPanel.download('${rid}')">
                ↓ Download History
              </button>
            </div>` : "";

          return `
            <div class="hist-loop" onclick="HistoryPanel.toggleRun('${rid}')"
              style="flex-direction:column;align-items:flex-start;gap:2px;cursor:pointer">
              <div style="display:flex;justify-content:space-between;width:100%">
                <span style="font-weight:600;color:var(--text)">Run ${idx + 1}</span>
                <span style="color:${statusCol};font-size:10px;font-weight:700">${statusText}</span>
              </div>
              <div style="font-size:10px;color:var(--text3);font-family:var(--mono)">${timestamp}</div>
              <div style="font-size:10px;color:var(--accent2)">Best val: ${bestVal.toFixed(1)}%</div>
            </div>
            ${downloadBtn}`;
        }).join("") : "";

        return `
          <div class="hist-run">
            <div class="hist-run-header"
              onclick="HistoryPanel.toggleStage('${stage}')"
              style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;padding:6px 0">
              <span style="color:var(--text);font-weight:600;font-size:12px">${label}</span>
              <span style="color:var(--text3);font-size:11px">${isOpenS ? "▲" : "▼"} ${runIds.length} run${runIds.length !== 1 ? "s" : ""}</span>
            </div>
            ${runRows}
          </div>`;
      }).join("");

    } catch (e) {
      panel.innerHTML = `<div style="font-size:11px;color:var(--red)">Could not load history.</div>`;
    }
  }

  function toggleStage(stage) {
    openStage = openStage === stage ? null : stage;
    openRun   = null;
    render();
  }

  function toggleRun(rid) {
    openRun = openRun === rid ? null : rid;
    render();
  }

  function download(runId) {
    API.downloadVersions(runId);
  }

  // Auto-refresh every 30s when visible
  setInterval(() => { if (visible) render(); }, 30000);

  return { init, toggle, render, toggleStage, toggleRun, download };
})();