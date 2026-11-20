/* 承瑞 問答特訓 · 学习记录
   Shared by every page in /training/. Asks the learner's name once (shared across
   pages in this browser) and reports chapter progress to FOA so admins can see it:
     HTQA.open(module)            entered a chapter (logged once per chapter per visit)
     HTQA.log("finish", module)   completed a chapter
     HTQA.log("exam", null, score, total)  结业测验 result
     HTQA.log("quiz", module, right, total) 视频课 chapter quiz result
   Pages call these through hooks added by scripts/publish_training_page.py (問答特訓)
   and scripts/publish_training_video.py (视频课, folder pages: /training/<slug>/). */
(function () {
  var NAME_KEY = "ht-qa-name", ID_KEY = "ht-qa-visitor";

  function api() {
    var h = location.hostname;
    if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
    if (h.indexOf("app.") === 0) return location.protocol + "//api." + h.slice(4);
    return location.protocol + "//api." + h;
  }
  function get(k) { try { return localStorage.getItem(k) || ""; } catch (e) { return ""; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var visitor = get(ID_KEY);
  if (!/^[A-Za-z0-9-]{8,40}$/.test(visitor)) {
    visitor = "v-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
    set(ID_KEY, visitor);
  }
  var name = get(NAME_KEY);
  // /training/crs-tax-qa.html -> crs-tax-qa ; /training/crs-video/ (or …/index.html) -> crs-video
  var parts = location.pathname.split("/").filter(Boolean);
  var page = (parts.pop() || "").replace(/\.html?$/i, "").toLowerCase();
  if (page === "index" || page === "") page = (parts.pop() || "").toLowerCase();
  var isVideo = /-video$/.test(page);
  var queue = [];          // events raised before the name is entered
  var lastOpen = null;

  function send(body) {
    if (!name) { queue.push(body); return; }
    body.visitor_id = visitor; body.name = name; body.page = page;
    body.page_title = document.title;
    body.module_total = (window.MODULES || []).length || null;
    try {
      fetch(api() + "/public/qa-events", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), keepalive: true, mode: "cors"
      }).catch(function () {});
    } catch (e) {}
  }

  window.HTQA = {
    open: function (m) {
      if (!m || m.id === lastOpen) return;
      lastOpen = m.id;
      send({ event: "open", module_id: m.id, module_name: m.name });
    },
    log: function (event, m, score, total) {
      var b = { event: event };
      if (m) { b.module_id = m.id; b.module_name = m.name; }
      if (event === "exam" || event === "quiz") { b.score = score; b.total = total; }
      send(b);
    },
    name: function () { return name; }
  };

  /* ---------- 姓名 ---------- */
  var css = ".htqa-ov{position:fixed;inset:0;z-index:9999;background:rgba(59,34,15,.55);display:flex;align-items:center;justify-content:center;padding:16px}" +
    ".htqa-box{background:var(--paper,#FFFBF3);color:var(--ink,#3B220F);border-radius:16px;max-width:360px;width:100%;padding:24px 20px;box-shadow:0 12px 40px rgba(0,0,0,.25);font-family:var(--body,sans-serif)}" +
    ".htqa-box h2{margin:0 0 6px;font-family:var(--display,serif);font-size:20px}" +
    ".htqa-box p{margin:0 0 14px;color:var(--muted,#6E5238);font-size:14px;line-height:1.6}" +
    ".htqa-box input{width:100%;box-sizing:border-box;font:inherit;font-size:16px;padding:10px 12px;border:1px solid var(--line,#E7D5B2);border-radius:10px;background:#fff;color:inherit}" +
    ".htqa-box input:focus{outline:2px solid var(--gold,#C9862E);outline-offset:1px}" +
    ".htqa-box .err{color:var(--bad,#A8261A);font-size:13px;min-height:18px;margin:6px 0 0}" +
    ".htqa-box button{margin-top:10px;width:100%;font:inherit;font-weight:700;padding:11px;border:0;border-radius:10px;background:var(--gold-deep,#8A5200);color:#fff;cursor:pointer}" +
    ".htqa-who{margin:10px 0 0;font-size:13px;color:var(--muted,#6E5238)}" +
    ".htqa-who button{font:inherit;font-size:13px;border:0;background:none;color:var(--gold-deep,#8A5200);text-decoration:underline;cursor:pointer;padding:0 0 0 6px}";

  function ask(isChange) {
    var ov = document.createElement("div");
    ov.className = "htqa-ov";
    ov.innerHTML = '<form class="htqa-box" role="dialog" aria-modal="true" aria-labelledby="htqa-t">' +
      '<h2 id="htqa-t">' + (isChange ? "更改姓名" : (isVideo ? "欢迎来到视频课" : "欢迎来到问答特训")) + '</h2>' +
      '<p>请输入你的姓名，方便导师了解你的学习进度。</p>' +
      '<input id="htqa-n" maxlength="40" autocomplete="name" placeholder="你的姓名">' +
      '<p class="err" id="htqa-e"></p><button type="submit">' + (isChange ? "保存" : "开始") + '</button></form>';
    document.body.appendChild(ov);
    var input = ov.querySelector("#htqa-n");
    input.value = name;
    setTimeout(function () { input.focus(); }, 30);
    ov.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var v = input.value.replace(/\s+/g, " ").trim();
      if (!v) { ov.querySelector("#htqa-e").textContent = "请输入姓名"; return; }
      name = v.slice(0, 40); set(NAME_KEY, name);
      ov.parentNode.removeChild(ov);
      who();
      var q = queue; queue = [];
      q.forEach(send);
    });
    if (isChange) ov.addEventListener("click", function (e) { if (e.target === ov) ov.parentNode.removeChild(ov); });
  }

  function who() {
    var bar = document.getElementById("donebar") || document.getElementById("htqa-anchor");
    if (!bar || !name) return;
    var p = document.getElementById("htqa-who");
    if (!p) {
      p = document.createElement("p"); p.id = "htqa-who"; p.className = "htqa-who";
      bar.parentNode.insertBefore(p, bar.nextSibling);
    }
    p.textContent = "学员：" + name;
    var b = document.createElement("button");
    b.type = "button"; b.textContent = "更改";
    b.addEventListener("click", function () { ask(true); });
    p.appendChild(b);
  }

  function init() {
    var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
    if (name) who(); else ask(false);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
