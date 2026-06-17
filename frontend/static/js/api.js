/* api.js — TagForge */
const API = (() => {
  function authHeaders() {
    const headers = {};
    if (window.__TAGFORGE_API_KEY__) {
      headers["X-TagForge-Key"] = window.__TAGFORGE_API_KEY__;
    }
    return headers;
  }

  async function req(method, path, body, isForm = false) {
    const opts = { method, headers: authHeaders() };
    if (body) {
      if (isForm) {
        opts.body = body;
      } else {
        opts.headers = { ...opts.headers, "Content-Type": "application/json" };
        opts.body    = JSON.stringify(body);
      }
    }
    const res = await fetch(path, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }
  return {
    health:           ()       => req("GET",  "/api/health"),
    listDocs:         ()       => req("GET",  "/api/docs"),
    uploadDoc:        (fd)     => req("POST", "/api/upload-doc",       fd, true),
    uploadGtCsv:      (fd)     => req("POST", "/api/upload-gt-csv",    fd, true),
    uploadEvalScript: (fd)     => req("POST", "/api/upload-eval-script", fd, true),
    useDemoScript:    ()       => req("POST", "/api/use-demo-script"),
    getEvalScript:    ()       => req("GET",  "/api/eval-script"),
    listStages:       ()       => req("GET",  "/api/stages"),
    getKm:            (fn)     => req("GET",  `/api/km/${fn}`),
    kmList:           ()       => req("GET",  "/api/km-list"),
    gtPreview:        (id)     => req("GET",  `/api/gt-preview${id ? "?doc_id=" + id : ""}`),
    split:            (seed)   => req("POST", "/api/split", { seed }),
    scoreBatch:       (payload)=> req("POST", "/api/score-batch", payload),
    improveKM:        (payload)=> req("POST", "/api/improve-km",  payload),
    finalEval:        (pairs, kmStage, kmJson, gtCol) =>
                                  req("POST", "/api/score-batch", {
                                    pairs,
                                    km_stage:  kmStage  || State.get("kmStage"),
                                    km_json:   kmJson   || State.get("kmJson"),
                                    gt_column: gtCol    || State.get("gtColumn"),
                                  }),
    saveVersion:      (payload)=> req("POST", "/api/save-version",    payload),
    getVersions:      ()       => req("GET",  "/api/versions"),
    downloadVersions: (runId)  => window.open(`/api/versions/download?run_id=${runId || ""}`, "_blank"),
    clearVersions:    ()       => req("POST", "/api/clear-versions"),
    markRunStatus:    (payload)=> req("POST", "/api/mark-run-status", payload),
  };
})();