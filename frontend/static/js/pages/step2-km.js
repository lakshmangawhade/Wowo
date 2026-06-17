/* step2-km.js — Select KM Stage */
const Step2 = (() => {

  const STAGES = [
    {
      id:      "km_01a_specific_topic_family_router",
      name:    "Specific Topic Family Router",
      gt_col:  "SpecificTopicFamily",
      desc:    "Routes documents to topic families (e.g. climate_energy, water_marine_and_fisheries).",
    },
    {
      id:      "km_01z_specific_topic_reconciler",
      name:    "Specific Topic Reconciler",
      gt_col:  "SpecificTopic",
      desc:    "Reconciles candidate specific topics into a final list (e.g. 'Product Safety; Consumer Protection Laws').",
    },
    {
      id:      "km_02_applicable_sectors",
      name:    "Applicable Sectors",
      gt_col:  "ApplicableSectors",
      desc:    "Classifies which industry sectors are regulated by the document.",
    },
    {
      id:      "km_03_esrs_mapping",
      name:    "ESRS Mapping",
      gt_col:  "ClosestESRSTopics",
      desc:    "Maps the document to the closest ESRS topics (e.g. ESRS E3, ESRS S4).",
    },
    {
      id:      "km_04_orchestrator_extraction",
      name:    "Orchestrator Extraction",
      gt_col:  "SpecificTopic",
      desc:    "Non-tag extraction: dates, titles, type of regulation, sanctions, etc.",
    },
  ];

  function html() {
    return `
<div class="page" id="page-1">
  <div class="page-header">
    <h2>Select KM Stage to Optimise</h2>
    <p>Choose which pipeline stage's knowledge model you want to iteratively improve. Each stage maps to a specific ground-truth column.</p>
  </div>

  <div class="card">
    <div class="card-title">Pipeline Stages</div>
    <div class="card-sub">Click to select. The selected stage's KM JSON will be fed to the FAB agent during loops.</div>
    <div class="stage-grid" id="stage-grid">
      ${STAGES.map(s => `
        <div class="stage-card" id="sc-${s.id}" onclick="Step2.selectStage('${s.id}')">
          <div class="stage-id">${s.id}</div>
          <div class="stage-name">${s.name}</div>
          <div class="stage-col">GT column: ${s.gt_col}</div>
          <div style="font-size:10px;color:var(--text3);margin-top:6px;line-height:1.4">${s.desc}</div>
        </div>
      `).join("")}
    </div>
  </div>

  <div class="card" id="km-preview-card" style="display:none">
    <div class="card-title">Current KM JSON</div>
    <div class="card-sub" id="km-preview-sub">Loaded from disk.</div>
    <div class="code-block" id="km-preview-text" style="max-height:200px"></div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
      <span style="font-size:11px;color:var(--text3)">GT column being evaluated:</span>
      <span class="gt-col-pill" id="gt-col-display">—</span>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-top:4px">
    <button class="btn" onclick="Nav.go(0)">← Back</button>
    <button class="btn btn-accent" id="btn-next2" disabled onclick="Step2.next()">Continue →</button>
  </div>
</div>`;
  }

  function init() {
    const saved = State.get("kmStage");
    if (saved) {
      highlightCard(saved);
    }
  }

  async function selectStage(stageId) {
    const stage = STAGES.find(s => s.id === stageId);
    if (!stage) return;

    State.set("kmStage",  stageId);
    State.set("gtColumn", stage.gt_col);

    highlightCard(stageId);

    document.getElementById("gt-col-display").textContent = stage.gt_col;
    document.getElementById("btn-next2").disabled = false;

    // load KM preview
    try {
      const d = await API.kmList();
      // find matching file
      const kmFile = d.km_files.find(f => f.includes(stageId.replace("km_", "").replace(/_/g, "_")));
      if (kmFile) {
        const km = await API.getKm(kmFile);
        State.set("kmJson", JSON.stringify(km));
        State.set("_kmFile", kmFile);
        const card = document.getElementById("km-preview-card");
        card.style.display = "block";
        document.getElementById("km-preview-sub").textContent =
          `${kmFile} — version: ${km.version || km.km_id || "?"}`;
        document.getElementById("km-preview-text").textContent =
          JSON.stringify(km, null, 2).slice(0, 2000) + "\n…";
      }
    } catch(e) {
      document.getElementById("km-preview-card").style.display = "block";
      document.getElementById("km-preview-text").textContent = "Could not load KM: " + e.message;
    }
  }

  function highlightCard(stageId) {
    document.querySelectorAll(".stage-card").forEach(el => el.classList.remove("selected"));
    const el = document.getElementById("sc-" + stageId);
    if (el) el.classList.add("selected");
  }

  function next() { Nav.next(); }

  return { html, init, selectStage, next };
})();