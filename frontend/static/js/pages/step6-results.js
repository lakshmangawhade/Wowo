const Step6 = (() => {

  function html() {
    return `
<div class="page" id="page-5">
  <div class="page-header">
    <h2>Final Results</h2>
    <p>Run the best KM prompt on the unseen evaluation set for the definitive score.</p>
  </div>

  <div id="final-run-section">
    <div class="warn-row">
      <span></span>
      <span>The unseen set has not been touched during training. This score is the true measure of your KM prompt's generalisation ability.</span>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:20px">
      <button class="btn btn-accent" id="btn-final-run" onclick="Step6.runFinal()">Run Final Evaluation</button>
      <button class="btn btn-green"  id="btn-save"      onclick="Step6.saveVersion()" disabled>Save as New KM Prompt</button>
      <button class="btn"            id="btn-download"  onclick="Step6.downloadReport()" disabled>Download Report</button>
    </div>
  </div>

  <!-- final score -->
  <div id="final-score-wrap" style="display:none">
    <div class="final-card">
      <div class="final-icon"></div>
      <div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:4px;font-family:var(--mono)">FINAL SCORE — UNSEEN SET</div>
        <div class="final-score" id="final-score-val">—</div>
        <div style="font-size:12px;color:var(--text2);margin-top:6px" id="final-score-sub"></div>
      </div>
    </div>
  </div>

  <!-- stats grid -->
  <div class="stats-grid" id="stats-grid" style="display:none">
    <div class="stat-card">
      <div class="stat-lbl">Best Loop</div>
      <div class="stat-val" id="stat-best-loop" style="color:var(--accent2)">—</div>
      <div class="stat-sub" id="stat-best-loop-sub"></div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">Best Val Score</div>
      <div class="stat-val" id="stat-best-val" style="color:var(--green)">—</div>
      <div class="stat-sub">validation set</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">Total Loops</div>
      <div class="stat-val" id="stat-total-loops" style="color:var(--cyan)">—</div>
      <div class="stat-sub">iterations run</div>
    </div>
    <div class="stat-card">
      <div class="stat-lbl">Unseen Docs</div>
      <div class="stat-val" id="stat-unseen-docs" style="color:var(--amber)">—</div>
      <div class="stat-sub">final eval set</div>
    </div>
  </div>

  <!-- loop score table -->
  <div class="card" id="loop-report-card" style="display:none">
    <div class="card-title">Loop Score Report</div>
    <div class="card-sub">Every loop's scores and delta from previous.</div>
    <table class="doc-table" id="loop-report-table">
      <thead>
        <tr>
          <th>Loop</th><th>Version</th><th>Learn Score</th><th>Val Score</th><th>Δ Val</th><th>Failures</th><th>Status</th>
        </tr>
      </thead>
      <tbody id="loop-report-body"></tbody>
    </table>
  </div>

  <!-- best KM -->
  <div class="card" id="best-km-card" style="display:none">
    <div class="card-title">Best KM Prompt</div>
    <div class="card-sub" id="best-km-sub"></div>
    <div class="code-block" id="best-km-text"></div>
  </div>

  <!-- version history -->
  <div class="card" id="ver-history-card" style="display:none">
    <div class="card-title">Version History</div>
    <div class="card-sub">All saved KM versions from previous runs.</div>
    <div id="ver-history-list"><div style="font-size:12px;color:var(--text3)">Loading…</div></div>
  </div>

  <div style="display:flex;gap:10px;margin-top:4px">
    <button class="btn" onclick="Nav.go(4)">← Back to Loops</button>
  </div>
</div>`;
  }

  function init() {
    loadVersionHistory();
    const loopResults = State.get("loopResults") || [];
    const bestIdx     = State.get("bestLoopIdx") || 0;
    if (loopResults.length > 0) {
      populateLoopReport(loopResults, bestIdx);
      populateBestKM(loopResults[bestIdx]);
    }
    setInterval(loadVersionHistory, 30000);
  }

  async function runFinal() {
    const split      = State.get("splitData");
    const loopResults= State.get("loopResults") || [];
    const bestIdx    = State.get("bestLoopIdx") || 0;

    if (!split || loopResults.length === 0) {
      alert("Run the loops first before final evaluation."); return;
    }

    const unseenPairs = split.pairs.filter(p => p.set === "unseen");
    document.getElementById("btn-final-run").disabled = true;
    document.getElementById("btn-final-run").textContent = "Running…";

    try {
      const res = await API.finalEval(unseenPairs);
      const score = res.average_score;
      State.set("finalScore", score);
      document.getElementById("final-score-wrap").style.display = "block";
      document.getElementById("final-score-val").textContent    = score + "%";
      const target = State.get("targetScore");
      document.getElementById("final-score-sub").textContent =
        score >= target
          ? `Target of ${target}% achieved!`
          : `Target was ${target}% — ${(target - score).toFixed(1)}% below target`;
      document.getElementById("final-score-sub").style.color =
        score >= target ? "var(--green)" : "var(--amber)";
      document.getElementById("stats-grid").style.display = "grid";
      const best = loopResults[bestIdx];
      document.getElementById("stat-best-loop").textContent     = `Loop ${best.loop}`;
      document.getElementById("stat-best-loop-sub").textContent = best.km_version;
      document.getElementById("stat-best-val").textContent      = best.val_score + "%";
      document.getElementById("stat-total-loops").textContent   = loopResults.length;
      document.getElementById("stat-unseen-docs").textContent   = unseenPairs.length;

      populateLoopReport(loopResults, bestIdx);
      populateBestKM(best);

      document.getElementById("btn-save").disabled     = false;
      document.getElementById("btn-download").disabled = false;

    } catch(e) {
      alert("Final eval failed: " + e.message);
    } finally {
      document.getElementById("btn-final-run").disabled    = false;
      document.getElementById("btn-final-run").textContent = "Run Final Evaluation";
    }
  }

  function populateLoopReport(loopResults, bestIdx) {
    const target = State.get("targetScore");
    document.getElementById("loop-report-card").style.display = "block";
    const tbody = document.getElementById("loop-report-body");
    tbody.innerHTML = loopResults.map((r, i) => {
      const isBest = i === bestIdx;
      const prev   = i > 0 ? loopResults[i-1].val_score : null;
      const delta  = prev !== null ? (r.val_score - prev).toFixed(1) : "—";
      const dColor = delta === "—" ? "var(--text3)" : +delta > 0 ? "var(--green)" : +delta < 0 ? "var(--red)" : "var(--text3)";
      const hitTarget = r.val_score >= target;
      return `<tr style="${isBest ? "background:var(--gdim)" : ""}">
        <td style="color:var(--text)">${r.loop}</td>
        <td>${r.km_version}</td>
        <td style="color:var(--cyan)">${r.learn_score}%</td>
        <td style="color:${hitTarget ? "var(--green)" : "var(--text)"}">${r.val_score}%</td>
        <td style="color:${dColor}">${delta !== "—" && +delta > 0 ? "+" : ""}${delta}</td>
        <td style="color:var(--amber)">${r.failure_count}</td>
        <td>
          ${isBest ? '<span class="tag tag-green">BEST</span>' : ""}
          ${hitTarget ? '<span class="tag tag-accent" style="margin-left:4px">TARGET ✓</span>' : ""}
        </td>
      </tr>`;
    }).join("");
  }

  function populateBestKM(best) {
    document.getElementById("best-km-card").style.display = "block";
    document.getElementById("best-km-sub").textContent    =
      `${best.km_version} — Val score: ${best.val_score}%`;
    document.getElementById("best-km-text").textContent   = best.km_text;
  }

  async function saveVersion() {
    const loopResults = State.get("loopResults") || [];
    const bestIdx     = State.get("bestLoopIdx") || 0;
    const best        = loopResults[bestIdx];
    if (!best) return;

    State.set("kmPrompt", best.km_text);
    const ta = document.getElementById("km-editor");
    if (ta) {
      ta.value = best.km_text;
      ta.dispatchEvent(new Event("input"));
    }
    alert(`Best KM (Loop ${best.loop}, ${best.val_score}%) saved as your new starting prompt on Step 2.`);
  }

  async function loadVersionHistory() {
    try {
      const d = await API.getVersions();
      const list = document.getElementById("ver-history-list");
      if (!list) return;
      if (!d.versions || d.versions.length === 0) {
        list.innerHTML = `<div style="color:var(--text3);font-size:12px;padding:12px">No versions saved yet.</div>`;
        return;
      }

      // group by run_id
      const runs = {};
      const runOrder = [];
      d.versions.forEach(v => {
        const rid = v.run_id || "legacy";
        if (!runs[rid]) {
          runs[rid] = [];
          runOrder.push(rid);
        }
        runs[rid].push(v);
      });

      list.innerHTML = runOrder.slice().reverse().map(rid => {
        const versions = runs[rid];
        const first    = versions[0];
        const best     = versions.reduce((a, b) => (b.val_score > a.val_score ? b : a), versions[0]);
        const product  = first.product || "banking";
        const date     = first.saved_at || "";

        const rows = versions.map((v, i) => {
          const globalIdx = `${rid}_${i}`;
          return `
            <div class="ver-row" onclick="Step6.togglePrompt('${globalIdx}')">
              <span class="ver-badge ${v === best ? 'best' : ''}">${v.label}</span>
              <span class="ver-score" style="color:var(--green)">${v.val_score}%</span>
              <span class="ver-preview">${v.km_text.replace(/\n/g," ").slice(0,80)}</span>
              <span style="font-size:10px;color:var(--text3);font-family:var(--mono)">${v.saved_at || ""}</span>
            </div>
            <div id="prompt-preview-${globalIdx}" style="display:${openPrompts.has(globalIdx) ? 'block' : 'none'}">
              <div class="code-block" style="margin-bottom:8px;white-space:pre-wrap">${v.km_text}</div>
            </div>`;
        }).join("");

        return `
          <div style="margin-bottom:20px">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border)">
              <span style="font-size:11px;font-weight:700;color:var(--text)">${date.slice(0,16)}</span>
              <span style="font-size:11px;color:var(--green);font-weight:600">best: ${best.val_score}%</span>
            </div>
            ${rows}
          </div>`;
      }).join("");

    } catch(e) {
      console.error("loadVersionHistory error", e);
    }
  }

  function downloadReport() {
    const loopResults = State.get("loopResults") || [];
    const bestIdx     = State.get("bestLoopIdx") || 0;
    const report = {
      generated:   new Date().toISOString(),
      config: {
        target_score: State.get("targetScore"),
        max_loops:    State.get("maxLoops"),
      },
      final_score:  State.get("finalScore"),
      loop_results: loopResults.map(r => ({
        loop: r.loop, learn_score: r.learn_score, val_score: r.val_score,
        failure_count: r.failure_count, km_version: r.km_version,
      })),
      best_loop_idx: bestIdx,
      best_km: loopResults[bestIdx]?.km_text || "",
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = `evalforge-report-${Date.now()}.json`;
    a.click();
  }

  const openPrompts = new Set();

  function togglePrompt(id) {
    const el = document.getElementById(`prompt-preview-${id}`);
    if (!el) return;
    if (openPrompts.has(id)) {
      openPrompts.delete(id);
      el.style.display = "none";
    } else {
      openPrompts.add(id);
      el.style.display = "block";
    }
  }

  return { html, init, runFinal, saveVersion, downloadReport, togglePrompt };
})();