/* step3-targets.js — Set Targets */
const Step3 = (() => {
  function html() {
    return `
<div class="page" id="page-2">
  <div class="page-header">
    <h2>Set Targets</h2>
    <p>Configure the F1 target score and maximum optimisation loops.</p>
  </div>
  <div class="card">
    <div class="card-title">Optimisation Parameters</div>
    <div class="card-sub">The engine will loop until the F1 score on the validation set exceeds the target, or max loops is reached.</div>
    <div class="slider-row">
      <span class="slider-lbl">Target F1 Score</span>
      <input type="range" min="50" max="100" step="1" id="slider-target" value="80"
             oninput="Step3.updateTarget(this.value)"/>
      <span class="slider-val" id="val-target">80%</span>
    </div>
    <div class="slider-row">
      <span class="slider-lbl">Max Optimisation Loops</span>
      <input type="range" min="1" max="10" step="1" id="slider-loops" value="5"
             oninput="Step3.updateLoops(this.value)"/>
      <span class="slider-val" id="val-loops">5</span>
    </div>
    <div class="divider"></div>
    <div class="three-col" style="margin-top:4px">
      <div class="split-stat-item">
        <div class="split-stat-val" id="disp-target" style="color:var(--accent2)">80%</div>
        <div class="split-stat-lbl">F1 Target</div>
      </div>
      <div class="split-stat-item">
        <div class="split-stat-val" id="disp-loops" style="color:var(--cyan)">5</div>
        <div class="split-stat-lbl">Max Loops</div>
      </div>
      <div class="split-stat-item">
        <div class="split-stat-val" id="disp-stage" style="color:var(--green);font-size:11px;word-break:break-all">—</div>
        <div class="split-stat-lbl">KM Stage</div>
      </div>
    </div>
  </div>
  <div class="info-row">
    <span>ℹ</span>
    <span>Each loop: FAB agent tags the learn set → F1 computed vs GT → failures sent to improve agent → improved KM validated on val set.</span>
  </div>
  <div style="display:flex;gap:10px;margin-top:4px">
    <button class="btn" onclick="Nav.go(1)">← Back</button>
    <button class="btn btn-accent" onclick="Step3.next()">Continue →</button>
  </div>
</div>`;
  }
  function init() {
    const t = State.get("targetScore") || 80;
    const l = State.get("maxLoops")    || 5;
    const s = State.get("kmStage")     || "—";
    document.getElementById("slider-target").value = t;
    document.getElementById("slider-loops").value  = l;
    updateTarget(t);
    updateLoops(l);
    document.getElementById("disp-stage").textContent = s;
  }
  function updateTarget(v) {
    State.set("targetScore", +v);
    document.getElementById("val-target").textContent  = v + "%";
    document.getElementById("disp-target").textContent = v + "%";
  }
  function updateLoops(v) {
    State.set("maxLoops", +v);
    document.getElementById("val-loops").textContent  = v;
    document.getElementById("disp-loops").textContent = v;
  }
  function next() { Nav.next(); }
  return { html, init, updateTarget, updateLoops, next };
})();