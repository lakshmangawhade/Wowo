/* step4-split.js — Data Split */
const Step4 = (() => {

  function html() {
    return `
<div class="page" id="page-3">
  <div class="page-header">
    <h2>Data Split</h2>
    <p>Documents are split 50% unseen / 20% learn / 30% validation. Each doc is matched to its GT row by doc ID.</p>
  </div>

  <div class="card">
    <div class="card-title">Split Configuration</div>
    <div class="card-sub">A random seed ensures reproducible splits.</div>
    <div style="display:flex;gap:12px;align-items:center;margin-bottom:16px">
      <label style="font-size:12px;color:var(--text2)">Random Seed</label>
      <input class="inp" style="width:100px" type="number" id="split-seed" value="42"/>
      <button class="btn btn-accent" onclick="Step4.runSplit()">Generate Split</button>
    </div>

    <div class="split-bar" id="split-bar" style="display:none">
      <div class="split-seg" id="seg-unseen" style="background:var(--accent2)"></div>
      <div class="split-seg" id="seg-learn"  style="background:var(--cyan)"></div>
      <div class="split-seg" id="seg-val"    style="background:var(--green)"></div>
    </div>
    <div class="split-legend" id="split-legend" style="display:none;margin-bottom:10px">
      <div class="leg-item"><div class="leg-dot" style="background:var(--accent2)"></div>Unseen (50%)</div>
      <div class="leg-item"><div class="leg-dot" style="background:var(--cyan)"></div>Learn (20%)</div>
      <div class="leg-item"><div class="leg-dot" style="background:var(--green)"></div>Validation (30%)</div>
    </div>
    <div class="split-stat" id="split-stat" style="display:none">
      <div class="split-stat-item">
        <div class="split-stat-val" id="cnt-unseen" style="color:var(--accent2)">—</div>
        <div class="split-stat-lbl">Unseen</div>
      </div>
      <div class="split-stat-item">
        <div class="split-stat-val" id="cnt-learn" style="color:var(--cyan)">—</div>
        <div class="split-stat-lbl">Learn</div>
      </div>
      <div class="split-stat-item">
        <div class="split-stat-val" id="cnt-val" style="color:var(--green)">—</div>
        <div class="split-stat-lbl">Validation</div>
      </div>
    </div>
  </div>

  <div class="card" id="split-table-card" style="display:none">
    <div class="card-title">Document Mapping</div>
    <div class="card-sub" id="split-table-sub"></div>
    <div style="max-height:320px;overflow-y:auto">
      <table class="doc-table" id="doc-table">
        <thead><tr><th>#</th><th>Doc ID</th><th>GT: SpecificTopic</th><th>GT: SpecificTopicFamily</th><th>Set</th></tr></thead>
        <tbody id="doc-tbody"></tbody>
      </table>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-top:4px">
    <button class="btn" onclick="Nav.go(2)">← Back</button>
    <button class="btn btn-accent" id="btn-next4" disabled onclick="Step4.next()">Continue →</button>
  </div>
</div>`;
  }

  function init() {
    const saved = State.get("splitData");
    if (saved) renderSplit(saved);
  }

  async function runSplit() {
    const seed = +document.getElementById("split-seed").value;
    try {
      const d = await API.split(seed);
      State.set("splitData", d);
      renderSplit(d);
    } catch(e) {
      alert("Split failed: " + e.message);
    }
  }

  function renderSplit(d) {
    document.getElementById("split-bar").style.display    = "flex";
    document.getElementById("split-legend").style.display = "flex";
    document.getElementById("split-stat").style.display   = "grid";
    document.getElementById("split-table-card").style.display = "block";
    document.getElementById("btn-next4").disabled         = false;

    const pct = (n) => (n / d.total * 100).toFixed(1) + "%";
    document.getElementById("seg-unseen").style.width = pct(d.unseen);
    document.getElementById("seg-learn").style.width  = pct(d.learn);
    document.getElementById("seg-val").style.width    = pct(d.val);
    document.getElementById("cnt-unseen").textContent = d.unseen;
    document.getElementById("cnt-learn").textContent  = d.learn;
    document.getElementById("cnt-val").textContent    = d.val;
    document.getElementById("split-table-sub").textContent =
      `${d.total} docs — ${d.unseen} unseen, ${d.learn} learn, ${d.val} validation`;

    const tbody = document.getElementById("doc-tbody");
    tbody.innerHTML = d.pairs.map((p, i) => {
      const cls = p.set === "unseen" ? "set-unseen" : p.set === "learn" ? "set-learn" : "set-val";
      const gt  = p.gt || {};
      return `<tr>
        <td>${i+1}</td>
        <td title="${p.doc_id}">${p.doc_id.slice(0, 30)}…</td>
        <td title="${gt.SpecificTopic || ""}">${(gt.SpecificTopic || "—").slice(0, 40)}</td>
        <td>${gt.SpecificTopicFamily || "—"}</td>
        <td><span class="set-badge ${cls}">${p.set}</span></td>
      </tr>`;
    }).join("");
  }

  function next() { Nav.next(); }

  return { html, init, runSplit, next };
})();