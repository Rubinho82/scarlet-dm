const $ = (id) => document.getElementById(id);
const t = (id, ...subs) => chrome.i18n.getMessage(id, subs.map(String)) || id;
document.documentElement.lang = chrome.i18n.getUILanguage();
document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
const msg = (t) => { $("msg").textContent = t || ""; };

function fmtSize(n) {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 && i ? 1 : 0 })} ${u[i]}`;
}

function nameOf(url) {
  try {
    const p = new URL(url).pathname.split("/").filter(Boolean);
    return decodeURIComponent(p[p.length - 1] || url);
  } catch (e) { return url; }
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function render() {
  const st = await chrome.runtime.sendMessage({ type: "status" });
  $("status").textContent = st.online ? t("connected") : t("appClosed");
  $("status").classList.toggle("on", st.online);
  $("intercept").checked = st.cfg.intercept;
  $("minSize").value = st.cfg.minSizeKB;
  $("port").value = st.cfg.port;
  $("skipHtml").checked = st.cfg.skipHtml;
  $("skipDomains").value = st.cfg.skipDomains || "";
  $("skipExts").value = st.cfg.skipExts || "";

  const tab = await activeTab();
  const { items } = await chrome.runtime.sendMessage({ type: "media", tabId: tab.id });
  const ul = $("media");
  ul.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = t("noMedia");
    ul.append(li);
    return;
  }
  for (const m of items.slice().reverse()) {
    const li = document.createElement("li");
    const info = document.createElement("div");
    info.className = "info";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = nameOf(m.url);
    name.title = m.url;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [m.kind === "hls" ? t("hlsStream") : m.type, fmtSize(m.size)].filter(Boolean).join(" · ");
    info.append(name, meta);
    const b = document.createElement("button");
    b.textContent = t("download");
    b.onclick = async () => {
      const r = await chrome.runtime.sendMessage({
        type: "send", urls: [m.url],
        extra: { referer: tab.url, title: tab.title, kind: m.kind === "hls" ? "hls" : "" },
      });
      msg(r.ok ? t("sent") : r.error);
    };
    li.append(info, b);
    ul.append(li);
  }
}

$("intercept").onchange = (e) => chrome.storage.local.set({ intercept: e.target.checked });
$("skipHtml").onchange = (e) => chrome.storage.local.set({ skipHtml: e.target.checked });
$("skipDomains").onchange = (e) => chrome.storage.local.set({ skipDomains: e.target.value });
$("skipExts").onchange = (e) => chrome.storage.local.set({ skipExts: e.target.value });
$("pagemedia").onclick = async () => {
  const tab = await activeTab();
  const r = await chrome.runtime.sendMessage({ type: "send", urls: [tab.url], extra: { kind: "media", referer: tab.url } });
  msg(r.ok ? t("pageSent") : r.error);
};
$("minSize").onchange = (e) => chrome.storage.local.set({ minSizeKB: Math.max(0, parseInt(e.target.value, 10) || 0) });
$("port").onchange = async (e) => {
  await chrome.storage.local.set({ port: parseInt(e.target.value, 10) || 47331 });
  render();
};
$("show").onclick = async () => {
  const r = await chrome.runtime.sendMessage({ type: "show" });
  msg(r.ok ? "" : r.error);
};
$("page").onclick = async () => {
  const tab = await activeTab();
  const r = await chrome.runtime.sendMessage({ type: "pageLinks", tabId: tab.id, url: tab.url });
  msg(r.ok ? t("linksSent", r.count) : r.error);
};

render();
