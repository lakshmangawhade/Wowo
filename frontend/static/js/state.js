/* state.js — TagForge */
const State = (() => {
  let s = {
    currentStep:    0,
    completedSteps: new Set(),
    // Step 1
    evalScript:  null,
    docsLoaded:  false,
    // Step 2
    kmStage:   "km_01z_specific_topic_reconciler",
    gtColumn:  "SpecificTopic",
    kmJson:    "",    // current KM JSON text (may be modified during loops)
    // Step 3
    targetScore: 80,
    maxLoops:    5,
    // Step 4
    splitData: null,
    // Step 5
    loopResults:  [],
    bestLoopIdx:  0,
    currentRunId: null,
    // Step 6
    finalScore: null,
  };
  return {
    get:     (k)    => s[k],
    set:     (k, v) => { s[k] = v; },
    getAll:  ()     => s,
    markDone:(step) => s.completedSteps.add(step),
    isDone:  (step) => s.completedSteps.has(step),
  };
})();