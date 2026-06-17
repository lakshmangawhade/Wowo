/* nav.js — TagForge */
const Nav = (() => {
  const titles = [
    ["Upload & Ingest",   "Step 1 of 6 — load input documents and ground-truth CSV"],
    ["Select KM Stage",   "Step 2 of 6 — choose the pipeline stage to optimise"],
    ["Set Targets",       "Step 3 of 6 — configure score target and loop count"],
    ["Data Split",        "Step 4 of 6 — partition documents into sets"],
    ["Run Loops",         "Step 5 of 6 — iterative KM optimisation"],
    ["Final Results",     "Step 6 of 6 — unseen evaluation & best KM"],
  ];
  function go(idx) {
    const cur = State.get("currentStep");
    if (idx === cur) return;
    if (idx > cur && !State.isDone(cur)) return;
    State.set("currentStep", idx);
    render();
    if (idx === 4 && !Step5.isRunning()) Step5.init();
  }
  function next() {
    const cur = State.get("currentStep");
    State.markDone(cur);
    go(cur + 1);
  }
  function render() {
    const cur = State.get("currentStep");
    document.getElementById("topTitle").textContent = titles[cur][0];
    document.getElementById("topSub").textContent   = titles[cur][1];
    for (let i = 0; i < 6; i++) {
      const nb = document.getElementById(`nav-${i}`);
      const sb = document.getElementById(`snav-${i}`);
      if (!nb) continue;
      nb.className = "sbar-step";
      if (sb) sb.className = "sidebar-step";
      if (i === cur) {
        nb.classList.add("active");
        if (sb) sb.classList.add("active");
      } else if (State.isDone(i)) {
        nb.classList.add("done");
        if (sb) { sb.classList.add("done"); }
      } else {
        nb.classList.add("locked");
        if (sb) sb.classList.add("locked");
      }
    }
    document.querySelectorAll(".page").forEach((p, i) => {
      p.classList.toggle("active", i === cur);
    });
  }
  return { go, next, render };
})();