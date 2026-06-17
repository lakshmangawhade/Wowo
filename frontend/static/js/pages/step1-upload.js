/* step1-upload.js — Upload & Ingest */
const Step1 = (() => {

  function html() {
    return `
<div class="page active" id="page-0">
  <div class="page-header">
    <h2>Upload &amp; Ingest</h2>
    <p>Upload your input JSON documents and the ground-truth CSV. Then load an evaluation script (or use the built-in F1 scorer).</p>
  </div>

  <div class="two-col" style="margin-bottom:0">

    <div>
      <div class="card">
        <div class="card-title">Input Documents</div>
        <div class="card-sub">Upload JSON files (one per regulatory document). They go into <code style="font-family:var(--mono);color:var(--accent2)">products/tagging/input/</code></div>
        <div class="upload-zone" id="doc-zone">
          <input type="file" accept=".json" multiple id="doc-input"/>
          <div class="upload-title">Drop JSON document(s) here</div>
          <div class="upload-hint">or click to browse — .json files</div>
          <div id="doc-chip"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Ground-Truth CSV</div>
        <div class="card-sub">Upload the ground_truth.csv file. Must contain <code style="font-family:var(--mono);color:var(--accent2)">input_doc_id</code>, <code style="font-family:var(--mono);color:var(--accent2)">SpecificTopic</code>, <code style="font-family:var(--mono);color:var(--accent2)">SpecificTopicFamily</code>, <code style="font-family:var(--mono);color:var(--accent2)">ApplicableSectors</code>, <code style="font-family:var(--mono);color:var(--accent2)">ClosestESRSTopics</code> columns.</div>
        <div class="upload-zone" id="gt-zone">
          <input type="file" accept=".csv" id="gt-input"/>
          <div class="upload-title">Drop ground_truth.csv here</div>
          <div class="upload-hint">or click to browse — .csv file</div>
          <div id="gt-chip"></div>
        </div>
      </div>
    </div>

    <div>
      <div class="card">
        <div class="card-title">Evaluation Script</div>
        <div class="card-sub">Upload a Python file with <code style="font-family:var(--mono);color:var(--accent2)">evaluate(ai_output, gt_output) → 0–100</code>. Or use the built-in label F1 scorer.</div>
        <div class="upload-zone" id="eval-zone">
          <input type="file" accept=".py" id="eval-input"/>
          <div class="upload-title">Drop .py eval script here</div>
          <div class="upload-hint">or click to browse</div>
          <div id="eval-chip"></div>
        </div>
        <button class="btn" style="margin-top:10px;width:100%" onclick="Step1.useDemo()">
          Use Built-in Label F1 Scorer
        </button>
      </div>

      <div class="card">
        <div class="card-title">Current Status</div>
        <div id="status-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
          <div class="split-stat-item">
            <div class="split-stat-val" id="cnt-docs" style="color:var(--accent2)">—</div>
            <div class="split-stat-lbl">Input Docs</div>
          </div>
          <div class="split-stat-item">
            <div class="split-stat-val" id="cnt-gt" style="color:var(--green)">—</div>
            <div class="split-stat-lbl">GT Rows</div>
          </div>
          <div class="split-stat-item">
            <div class="split-stat-val" id="cnt-pairs" style="color:var(--cyan)">—</div>
            <div class="split-stat-lbl">Matched Pairs</div>
          </div>
          <div class="split-stat-item">
            <div class="split-stat-val" id="cnt-script" style="color:var(--amber)">—</div>
            <div class="split-stat-lbl">Eval Script</div>
          </div>
        </div>
        <div id="gt-sample-wrap" style="margin-top:14px;display:none">
          <div style="font-size:11px;color:var(--text3);margin-bottom:6px">GT sample (first 3 rows)</div>
          <div class="code-block" id="gt-sample" style="max-height:140px"></div>
        </div>
      </div>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-top:4px;align-items:center">
    <button class="btn btn-accent" id="btn-next1" disabled onclick="Step1.next()">Continue →</button>
    <span id="next1-hint" style="font-size:11px;color:var(--text3)">Need ≥1 input doc and ≥1 GT row</span>
  </div>
</div>`;
  }

  function init() {
    loadStatus();
    loadActiveScript();
    setupDocUpload();
    setupGtUpload();
    setupEvalUpload();
  }

  async function refresh() { await loadStatus(); }

  async function loadStatus() {
    try {
      const d = await API.listDocs();
      document.getElementById("cnt-docs").textContent  = d.total_input;
      document.getElementById("cnt-gt").textContent    = d.total_gt;
      document.getElementById("cnt-pairs").textContent = d.pairs;
      State.set("docsLoaded", d.total_input > 0 && d.total_gt > 0);
      checkCanContinue();

      if (d.total_gt > 0) {
        loadGtSample();
      }
    } catch(e) {
      document.getElementById("cnt-docs").textContent = "err";
    }
  }

  async function loadGtSample() {
    try {
      const d = await API.gtPreview();
      if (d.sample && d.sample.length > 0) {
        const wrap = document.getElementById("gt-sample-wrap");
        wrap.style.display = "block";
        document.getElementById("gt-sample").textContent =
          d.sample.slice(0, 3).map(r =>
            `${r.doc_id}:\n  SpecificTopic: ${r.gt.SpecificTopic}\n  SpecificTopicFamily: ${r.gt.SpecificTopicFamily}\n`
          ).join("\n");
      }
    } catch(_) {}
  }

  async function loadActiveScript() {
    try {
      const d = await API.getEvalScript();
      document.getElementById("cnt-script").textContent = "✓";
      document.getElementById("eval-chip").innerHTML =
        `<div class="file-chip">✓ ${d.filename}</div>`;
      State.set("evalScript", d);
      checkCanContinue();
    } catch(_) {
      document.getElementById("cnt-script").textContent = "—";
    }
  }

  function setupDocUpload() {
    const zone  = document.getElementById("doc-zone");
    const input = document.getElementById("doc-input");
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("dragover");
      uploadDocs(Array.from(e.dataTransfer.files));
    });
    input.addEventListener("change", () => uploadDocs(Array.from(input.files)));
  }

  async function uploadDocs(files) {
    let count = 0;
    for (const f of files) {
      if (!f.name.endsWith(".json")) continue;
      const fd = new FormData(); fd.append("file", f);
      try { await API.uploadDoc(fd); count++; } catch(_) {}
    }
    if (count > 0) {
      document.getElementById("doc-chip").innerHTML =
        `<div class="file-chip">✓ ${count} doc(s) uploaded</div>`;
      await loadStatus();
    }
  }

  function setupGtUpload() {
    const zone  = document.getElementById("gt-zone");
    const input = document.getElementById("gt-input");
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("dragover");
      if (e.dataTransfer.files[0]) uploadGt(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => { if (input.files[0]) uploadGt(input.files[0]); });
  }

  async function uploadGt(file) {
    const fd = new FormData(); fd.append("file", file);
    try {
      const d = await API.uploadGtCsv(fd);
      document.getElementById("gt-chip").innerHTML =
        `<div class="file-chip">✓ ${file.name} · ${d.row_count} rows</div>`;
      await loadStatus();
    } catch(e) {
      alert("GT upload failed: " + e.message);
    }
  }

  function setupEvalUpload() {
    const zone  = document.getElementById("eval-zone");
    const input = document.getElementById("eval-input");
    zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("dragover"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", e => {
      e.preventDefault(); zone.classList.remove("dragover");
      if (e.dataTransfer.files[0]) uploadEval(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => { if (input.files[0]) uploadEval(input.files[0]); });
  }

  async function uploadEval(file) {
    const fd = new FormData(); fd.append("file", file);
    try {
      const d = await API.uploadEvalScript(fd);
      document.getElementById("eval-chip").innerHTML =
        `<div class="file-chip">✓ ${d.filename} · ${d.metric}</div>`;
      document.getElementById("cnt-script").textContent = "✓";
      State.set("evalScript", d);
      checkCanContinue();
    } catch(e) {
      alert("Eval upload failed: " + e.message);
    }
  }

  async function useDemo() {
    try {
      const d = await API.useDemoScript();
      document.getElementById("eval-chip").innerHTML =
        `<div class="file-chip">✓ ${d.filename} · ${d.metric}</div>`;
      document.getElementById("cnt-script").textContent = "✓";
      State.set("evalScript", d);
      checkCanContinue();
    } catch(e) {
      alert("Error: " + e.message);
    }
  }

  function checkCanContinue() {
    const docs   = parseInt(document.getElementById("cnt-docs").textContent) || 0;
    const gt     = parseInt(document.getElementById("cnt-gt").textContent)   || 0;
    const script = document.getElementById("cnt-script").textContent;
    const ok     = docs > 0 && gt > 0 && script === "✓";
    document.getElementById("btn-next1").disabled = !ok;
    document.getElementById("next1-hint").style.display = ok ? "none" : "inline";
  }

  function next() { Nav.next(); }

  return { html, init, refresh, useDemo, next };
})();