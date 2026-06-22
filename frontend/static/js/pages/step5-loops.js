/* step5-loops.js — Run Optimisation Loops */
const Step5 = (() => {

  let currentKM    = "";
  let loopResults  = [];
  let bestIdx      = 0;
  let loopNum      = 0;
  let running      = false;
  let stopFlag     = false;
  let hasActiveRun = false;

  function html() {
    return `
<div class="page" id="page-4">
  <div class="page-header">
    <h2>Run Optimisation Loops</h2>
    <p>Each loop: FAB agent classifies learn docs → F1 scored vs GT → failures sent to improve agent → improved KM validated on val set.</p>
  </div>

  <div class="two-col">
    <div>
      <div class="card" style="margin-bottom:12px">
        <div class="card-title">Controls</div>
        <div style="margin-bottom:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="gt-col-pill" id="stage-pill">—</span>
          <span style="font-size:10px;color:var(--text3)">→</span>
          <span class="gt-col-pill" id="gtcol-pill">—</span>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-accent" id="btn-run"   onclick="Step5.startRun()">▶ Start Loops</button>
          <button class="btn btn-red"    id="btn-stop"  onclick="Step5.stopRun()"  disabled>■ Stop</button>
          <button class="btn"            id="btn-reset" onclick="Step5.resetRun()">↺ Reset</button>
        </div>
        <div style="margin-top:14px">
          <div style="font-size:10px;color:var(--text3);margin-bottom:4px;font-family:var(--mono)" id="loop-progress-label">Loop 0 / 0</div>
          <div class="progress-wrap"><div class="progress-fill" id="loop-progress" style="width:0%"></div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">System Log</div>
        <div class="log-box" id="log-box"></div>
      </div>
    </div>

    <div>
      <div class="card" style="margin-bottom:12px">
        <div class="card-title">Loop Results</div>
        <div class="card-sub">Best loop highlighted. P = Precision, R = Recall.</div>
        <div id="loop-list"><div style="font-size:12px;color:var(--text3)">No loops run yet.</div></div>
      </div>

      <div class="card">
        <div class="card-title">KM Versions</div>
        <div class="card-sub">Click a version to preview the KM JSON.</div>
        <div id="ver-list"></div>
        <div class="code-block" id="ver-preview" style="margin-top:10px;display:none"></div>
      </div>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-top:4px">
    <button class="btn" onclick="Nav.go(3)">← Back</button>
    <button class="btn btn-accent" id="btn-next5" disabled onclick="Step5.next()">Run Final Evaluation →</button>
  </div>
</div>`;
  }

  function init() {
    if (running) return;
    if (hasActiveRun) return;

    loopResults = [];
    loopNum     = 0;
    bestIdx     = 0;
    currentKM   = State.get("kmJson") || "";

    const stagePill = document.getElementById("stage-pill");
    const colPill   = document.getElementById("gtcol-pill");
    if (stagePill) stagePill.textContent = State.get("kmStage") || "—";
    if (colPill)   colPill.textContent   = State.get("gtColumn") || "—";

    renderLoops();
    renderVersions();
    const nb = document.getElementById("btn-next5");
    if (nb) nb.disabled = true;
    const lb = document.getElementById("log-box");
    if (lb) lb.innerHTML = "";
    const pf = document.getElementById("loop-progress");
    if (pf) pf.style.width = "0%";
    const pl = document.getElementById("loop-progress-label");
    if (pl) pl.textContent = "Loop 0 / 0";
  }

  function log(msg, type = "info") {
    const box  = document.getElementById("log-box");
    if (!box) return;
    const ts   = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = `log-line ${type}`;
    line.innerHTML = `<span class="log-ts">${ts}</span><span class="log-msg">${msg}</span>`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
  }

  async function startRun() {
    if (running) return;
    running  = true;
    stopFlag = false;

    document.getElementById("btn-run").disabled  = true;
    document.getElementById("btn-stop").disabled = false;
    document.getElementById("sysStatus").textContent = "running loops…";

    const split      = State.get("splitData");
    const target     = State.get("targetScore");
    const maxLoops   = State.get("maxLoops");
    const kmStage    = State.get("kmStage");
    const gtCol      = State.get("gtColumn");
    const learnPairs = split.pairs.filter(p => p.set === "learn");
    const valPairs   = split.pairs.filter(p => p.set === "val");

    if (!currentKM) currentKM = State.get("kmJson") || "";

    if (!hasActiveRun) {
      const runId = `run_${Date.now()}`;
      State.set("currentRunId", runId);
      loopResults = []; loopNum = 0; bestIdx = 0;
      renderLoops(); renderVersions();
      API.markRunStatus({ run_id: runId, status: "running" }).catch(() => {});
    }
    hasActiveRun = true;

    log(`Stage: ${kmStage} | GT col: ${gtCol} | Target: ${target}% | Max loops: ${maxLoops}`, "info");
    log(`Learn: ${learnPairs.length} docs | Val: ${valPairs.length} docs`, "muted");

    for (let i = 0; i < maxLoops; i++) {
      if (stopFlag) { log("Stop requested.", "warn"); break; }

      loopNum = loopResults.length + 1;
      updateProgress(i, maxLoops);
      log(`── Loop ${loopNum} ──`, "info");

      // Score learn set with retry
      log(`Scoring ${learnPairs.length} learn docs…`, "muted");
      let learnRes;
      {
        let lastErr;
        for (let retry = 0; retry < 3; retry++) {
          try {
            learnRes = await API.scoreBatch({
              pairs:     learnPairs,
              km_stage:  kmStage,
              km_json:   currentKM,
              gt_column: gtCol,
            });
            lastErr = null;
            break;
          } catch(e) {
            lastErr = e;
            const wait = (retry + 1) * 10;
            log(`Learn batch attempt ${retry+1} failed: ${e.message} — retrying in ${wait}s…`, "warn");
            await new Promise(r => setTimeout(r, wait * 1000));
          }
        }
        if (lastErr) { log("Learn batch failed after 3 attempts: " + lastErr.message, "err"); break; }
      }

      const learnScore = learnRes.average_score;
      const learnPrec  = learnRes.avg_precision || 0;
      const learnRec   = learnRes.avg_recall    || 0;
      log(`Learn F1: ${learnScore}% (P:${learnPrec}% R:${learnRec}%) · Failures: ${learnRes.failure_count}`,
          learnScore >= target ? "ok" : "warn");

      // Improve KM
      log("Improving KM…", "muted");
      try {
        const imp = await API.improveKM({
          current_km:   currentKM,
          km_stage:     kmStage,
          loop_num:     loopNum,
          learn_score:  learnScore,
          target_score: target,
          n_learn_docs: learnPairs.length,
          failures:     learnRes.failures,
          all_results:  learnRes.results,
          gt_column:    gtCol,
        });
        if (imp.improved_km && imp.improved_km !== currentKM) {
          currentKM = imp.improved_km;
          State.set("kmJson", currentKM);
          log("KM improved.", "ok");
        } else {
          log("KM unchanged.", "warn");
        }
      } catch(e) {
        log("KM improvement failed: " + e.message, "warn");
      }

      if (stopFlag) { log("Stopped before validation.", "warn"); break; }

      // Brief pause before validation to avoid overwhelming the FAB agent
      await new Promise(r => setTimeout(r, 3000));

      // Validate with retry
      log(`Validating on ${valPairs.length} val docs…`, "muted");
      let valRes;
      {
        let lastErr;
        for (let retry = 0; retry < 3; retry++) {
          try {
            valRes = await API.scoreBatch({
              pairs:     valPairs,
              km_stage:  kmStage,
              km_json:   currentKM,
              gt_column: gtCol,
            });
            lastErr = null;
            break;
          } catch(e) {
            lastErr = e;
            const wait = (retry + 1) * 10;
            log(`Val batch attempt ${retry+1} failed: ${e.message} — retrying in ${wait}s…`, "warn");
            await new Promise(r => setTimeout(r, wait * 1000));
          }
        }
        if (lastErr) { log("Val batch failed after 3 attempts: " + lastErr.message, "err"); break; }
      }

      const valScore = valRes.average_score;
      const valPrec  = valRes.avg_precision || 0;
      const valRec   = valRes.avg_recall    || 0;
      log(`Val F1: ${valScore}% (P:${valPrec}% R:${valRec}%)`, valScore >= target ? "ok" : "warn");

      // Regression guard
      const prevBest = loopResults.length > 0 ? loopResults[bestIdx].val_score : 0;
      if (valScore < prevBest) {
        log(`Regression (${valScore}% < ${prevBest}%) — reverting KM.`, "warn");
        currentKM = loopResults[bestIdx].km_json;
        State.set("kmJson", currentKM);
      }

      const result = {
        loop:          loopNum,
        learn_score:   learnScore,
        val_score:     valScore,
        km_stage:      kmStage,
        km_json:       currentKM,
        km_version:    `v${loopNum}`,
        failure_count: learnRes.failure_count,
        precision:     valPrec,
        recall:        valRec,
      };

      loopResults.push(result);
      if (loopResults.length === 1) { bestIdx = 0; }
      else if (valScore >= loopResults[bestIdx].val_score) { bestIdx = loopResults.length - 1; }

      State.set("loopResults", loopResults);
      State.set("bestLoopIdx", bestIdx);
      renderLoops();
      renderVersions();

      API.saveVersion({
        km_json:    currentKM,
        km_stage:   kmStage,
        val_score:  valScore,
        precision:  valPrec,
        recall:     valRec,
        label:      `Loop ${loopNum} — val F1: ${valScore}%`,
        run_id:     State.get("currentRunId"),
        loop_num:   loopNum,
      }).catch(() => {});

      if (valScore >= target) {
        log(`Target reached at loop ${loopNum}! F1: ${valScore}%`, "ok");
        break;
      }
    }

    const finalStatus = stopFlag ? "stopped" : "completed";
    API.markRunStatus({ run_id: State.get("currentRunId"), status: finalStatus }).catch(() => {});
    running = false;
    updateProgress(loopResults.length, State.get("maxLoops"));
    document.getElementById("btn-run").disabled   = false;
    document.getElementById("btn-stop").disabled  = true;
    document.getElementById("btn-next5").disabled = loopResults.length === 0;
    document.getElementById("sysStatus").textContent = "loops complete";
    log("Optimisation complete.", "ok");
  }

  function stopRun() {
    stopFlag = true;
    document.getElementById("btn-stop").disabled = true;
    log("Stop requested — will halt after current operation.", "warn");
  }

  function resetRun() {
    if (running) return;
    loopResults  = []; bestIdx = 0; loopNum = 0; stopFlag = false;
    currentKM    = State.get("kmJson") || "";
    hasActiveRun = false;
    State.set("loopResults", []); State.set("currentRunId", null);
    document.getElementById("btn-run").disabled   = false;
    document.getElementById("btn-stop").disabled  = true;
    document.getElementById("btn-next5").disabled = true;
    document.getElementById("loop-progress").style.width   = "0%";
    document.getElementById("loop-progress-label").textContent = "Loop 0 / 0";
    document.getElementById("log-box").innerHTML  = "";
    document.getElementById("sysStatus").textContent = "system ready";
    renderLoops(); renderVersions();
  }

  function updateProgress(done, total) {
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    document.getElementById("loop-progress").style.width       = pct + "%";
    document.getElementById("loop-progress-label").textContent = `Loop ${done} / ${total}`;
  }

  function renderLoops() {
    const target = State.get("targetScore");
    const list   = document.getElementById("loop-list");
    if (!list) return;
    if (loopResults.length === 0) {
      list.innerHTML = `<div style="font-size:12px;color:var(--text3)">No loops run yet.</div>`;
      return;
    }
    list.innerHTML = loopResults.map((r, i) => {
      const isBest  = i === bestIdx;
      const prev    = i > 0 ? loopResults[i-1].val_score : null;
      const delta   = prev !== null ? (r.val_score - prev).toFixed(1) : null;
      const dClass  = delta === null ? "d-base" : +delta > 0 ? "d-pos" : +delta < 0 ? "d-neg" : "d-base";
      const dLabel  = delta === null ? "base" : (+delta > 0 ? "+" : "") + delta;
      const barColor= r.val_score >= target ? "var(--green)" : "var(--accent)";
      return `<div class="loop-item ${isBest ? "best" : ""}">
        <span class="loop-num">Loop ${r.loop}</span>
        <div style="flex:1">
          <div class="loop-bar-wrap">
            <div class="loop-bar-fill" style="width:${Math.min(100,r.val_score)}%;background:${barColor}"></div>
          </div>
          <div class="pr-row">
            <span class="pr-pill pr-prec">P:${r.precision||0}%</span>
            <span class="pr-pill pr-rec">R:${r.recall||0}%</span>
          </div>
        </div>
        <span class="loop-score" style="color:${r.val_score>=target?"var(--green)":"var(--text)"}">${r.val_score}%</span>
        <span class="loop-delta ${dClass}">${dLabel}</span>
      </div>`;
    }).join("");
  }

  function renderVersions() {
    const list = document.getElementById("ver-list");
    if (!list) return;
    list.innerHTML = loopResults.map((r, i) => {
      const isBest = i === bestIdx;
      return `
        <div class="ver-row ${isBest ? "active-ver" : ""}" onclick="Step5.previewVer(${i})">
          <span class="ver-badge ${isBest ? "best" : ""}">Loop ${r.loop}</span>
          <span class="ver-score" style="color:${isBest?"var(--accent2)":"var(--text2)"}">${r.val_score}%</span>
          <span class="ver-preview">${JSON.stringify(r.km_json || "").slice(0, 80)}</span>
        </div>
        <div id="ver-exp-${i}" style="display:none">
          <div class="code-block" style="margin-bottom:8px;white-space:pre-wrap">${r.km_json ? r.km_json.slice(0, 2000) : ""}</div>
        </div>`;
    }).join("") || `<div style="font-size:12px;color:var(--text3)">No versions yet.</div>`;
  }

  function previewVer(idx) {
    const el = document.getElementById(`ver-exp-${idx}`);
    if (!el) return;
    el.style.display = el.style.display === "none" ? "block" : "none";
  }

  function next() {
    if (loopResults.length > 0) {
      State.set("bestKM",      loopResults[bestIdx].km_json);
      State.set("bestLoopIdx", bestIdx);
    }
    Nav.next();
  }

  function isRunning() { return running; }

  return { html, init, startRun, stopRun, resetRun, previewVer, next, isRunning };
})();