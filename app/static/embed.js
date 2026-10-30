/* Baza NISR embed: add <script src="https://YOUR-BAZA-URL/embed.js" defer></script> to any page.
   It adds an "Ask NISR data" button that opens the Baza agent in a side panel. No cookies, no tracking. */
(function () {
  "use strict";
  if (window.__bazaEmbed) return;
  window.__bazaEmbed = true;
  var script = document.currentScript || document.querySelector('script[src*="embed.js"]');
  var origin = new URL(script ? script.src : "/", window.location.href).origin;

  var css = [
    ".baza-launch{position:fixed;right:20px;bottom:20px;z-index:2147483000;display:flex;align-items:center;gap:8px;",
    "border:0;border-radius:999px;padding:12px 18px;font:600 14px system-ui,sans-serif;color:#fff;cursor:pointer;",
    "background:linear-gradient(135deg,#5b86ff,#2f5bff);box-shadow:0 0 0 1px rgba(79,124,255,.4),0 8px 30px rgba(47,91,255,.45)}",
    ".baza-launch:focus-visible{outline:2px solid #cfe0ff;outline-offset:3px}",
    ".baza-launch i{width:8px;height:8px;border-radius:50%;background:#cfe0ff;box-shadow:0 0 8px #cfe0ff}",
    ".baza-panel{position:fixed;top:0;right:0;z-index:2147483001;width:min(480px,100vw);height:100vh;",
    "background:#05070d;box-shadow:-20px 0 60px rgba(0,0,0,.5);transform:translateX(100%);transition:transform .25s ease}",
    ".baza-panel.open{transform:none}",
    ".baza-panel iframe{border:0;width:100%;height:calc(100% - 44px)}",
    ".baza-bar{height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;",
    "font:500 11px ui-monospace,Menlo,monospace;letter-spacing:.08em;color:#7fa3ff;border-bottom:1px solid rgba(120,150,255,.2)}",
    ".baza-bar button{border:0;background:transparent;color:#cfe0ff;font-size:20px;cursor:pointer;line-height:1}",
    "@media (prefers-reduced-motion:reduce){.baza-panel{transition:none}}",
  ].join("");
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  var launch = document.createElement("button");
  launch.type = "button";
  launch.className = "baza-launch";
  launch.setAttribute("aria-expanded", "false");
  launch.innerHTML = "<i></i>Ask NISR data";

  var panel = document.createElement("aside");
  panel.className = "baza-panel";
  panel.setAttribute("aria-label", "Baza NISR assistant");
  panel.innerHTML = '<div class="baza-bar"><span>BAZA NISR · OFFICIAL STATISTICS AGENT</span>' +
    '<button type="button" aria-label="Close">&times;</button></div>';
  var frame = null;

  function open() {
    if (!frame) {
      frame = document.createElement("iframe");
      frame.title = "Baza NISR";
      frame.src = origin + "/?embed=1";
      panel.appendChild(frame);
    }
    panel.classList.add("open");
    launch.setAttribute("aria-expanded", "true");
  }
  function close() {
    panel.classList.remove("open");
    launch.setAttribute("aria-expanded", "false");
    launch.focus();
  }
  launch.addEventListener("click", function () { panel.classList.contains("open") ? close() : open(); });
  panel.querySelector(".baza-bar button").addEventListener("click", close);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.classList.contains("open")) close(); });

  function mount() { document.body.appendChild(launch); document.body.appendChild(panel); }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
