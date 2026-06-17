/* main.js — TagForge bootstrap */
(async () => {
  const container = document.getElementById("pages-container");

  container.innerHTML = [
    Step1.html(),
    Step2.html(),
    Step3.html(),
    Step4.html(),
    Step5.html(),
    Step6.html(),
  ].join("\n");

  Nav.render();

  Step1.init();
  Step2.init();
  Step3.init();
  Step4.init();
  Step5.init();
  Step6.init();

  // Health check
  try {
    await API.health();
    document.getElementById("sysStatus").textContent = "system ready";
  } catch (e) {
    document.getElementById("sysStatus").textContent = "backend offline";
  }

  // Load history panel
  try {
    HistoryPanel.init();
  } catch (e) {
    console.warn("HistoryPanel init error:", e);
  }
})();