// Scarlet DM — integração com o navegador (Manifest V3; Chrome, Edge, Brave, Opera, Vivaldi e Firefox)
const t = (id, ...subs) => chrome.i18n.getMessage(id, subs.map(String)) || id;
const DEFAULTS = { port: 47331, intercept: true, minSizeKB: 0, skipDomains: "", skipExts: "", skipHtml: true };

function listOf(text) {
  return (text || "").split(/[\s,;]+/).map((s) => s.trim().toLowerCase().replace(/^\*?\./, "")).filter(Boolean);
}

function hostOf(url) {
  try { return new URL(url).hostname.toLowerCase(); } catch (e) { return ""; }
}

function domainSkipped(c, ...urls) {
  const doms = listOf(c.skipDomains);
  return urls.some((u) => {
    const h = hostOf(u);
    return h && doms.some((d) => h === d || h.endsWith("." + d));
  });
}

function extSkipped(c, name) {
  const exts = listOf(c.skipExts);
  const m = /\.([a-z0-9]{1,8})$/i.exec(name || "");
  return !!(m && exts.includes(m[1].toLowerCase()));
}
const skipOnce = new Set();   // links que devolvemos ao navegador (fallback) não são interceptados de novo

async function cfg() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) };
}

async function api(path, init = {}) {
  const c = await cfg();
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 2500);
  try {
    return await fetch(`http://127.0.0.1:${c.port}${path}`, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

async function ping() {
  try {
    const r = await api("/ping");
    return r.ok;
  } catch {
    return false;
  }
}

async function cookieHeader(url) {
  try {
    const list = await chrome.cookies.getAll({ url });
    return list.map((c) => `${c.name}=${c.value}`).join("; ");
  } catch {
    return "";
  }
}

async function send(urls, extra = {}) {
  const first = urls[0] || "";
  const body = {
    urls,
    referer: extra.referer || "",
    cookies: first.startsWith("http") ? await cookieHeader(first) : "",
    userAgent: navigator.userAgent,
    filename: extra.filename || "",
    title: extra.title || "",
    kind: extra.kind || "",
    silent: !!extra.silent,
  };
  const r = await api("/add", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Scarlet-Client": "extension" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function notify(message) {
  chrome.notifications.create({ type: "basic", iconUrl: "icons/128.png", title: "Scarlet DM", message });
}

const OFFLINE = t("offline");

// ---------------------------------------------------------------- menus
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "link", title: t("menuLink"), contexts: ["link"] });
    chrome.contextMenus.create({ id: "media", title: t("menuMedia"), contexts: ["image", "video", "audio"] });
    chrome.contextMenus.create({ id: "selection", title: t("menuSelection"), contexts: ["selection"] });
    chrome.contextMenus.create({ id: "pagemedia", title: t("menuPageMedia"), contexts: ["page", "video", "audio"] });
    chrome.contextMenus.create({ id: "page", title: t("menuPage"), contexts: ["page"] });
  });
});

function collectLinks(onlySelection) {
  const out = new Set();
  const re = /(?:https?|ftp):\/\/[^\s"'<>]+|magnet:\?[^\s"'<>]+/g;
  let anchors = [];
  if (onlySelection) {
    const sel = getSelection();
    if (sel && sel.rangeCount) {
      const frag = sel.getRangeAt(0).cloneContents();
      anchors = [...frag.querySelectorAll("a[href]")];
      (sel.toString().match(re) || []).forEach((u) => out.add(u));
    }
  } else {
    anchors = [...document.querySelectorAll("a[href]")];
  }
  for (const a of anchors) {
    try {
      const u = new URL(a.getAttribute("href"), location.href).href;
      if (/^(https?|ftp):/i.test(u) || u.startsWith("magnet:")) out.add(u);
    } catch (e) { /* href inválido */ }
  }
  const ext = /\.(zip|rar|7z|tar|gz|tgz|bz2|xz|zst|iso|img|exe|msi|msix|apk|dmg|pkg|deb|rpm|appimage|jar|mp4|mkv|avi|mov|wmv|flv|webm|m4v|mp3|flac|wav|ogg|opus|m4a|aac|wma|pdf|docx?|xlsx?|pptx?|odt|epub|mobi|torrent|jpe?g|png|gif|webp|bmp|tiff?|m3u8|bin|cab)$/i;
  return [...out].filter((u) => {
    if (onlySelection || u.startsWith("magnet:")) return true;
    try { return ext.test(new URL(u).pathname); } catch (e) { return false; }
  });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  try {
    if (info.menuItemId === "link") {
      await send([info.linkUrl], { referer: info.pageUrl || (tab && tab.url) || "" });
    } else if (info.menuItemId === "media") {
      await send([info.srcUrl], { referer: info.pageUrl || "", title: tab ? tab.title : "" });
    } else if (info.menuItemId === "pagemedia") {
      await send([info.pageUrl || tab.url], { kind: "media", referer: info.pageUrl || "" });
    } else {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: collectLinks,
        args: [info.menuItemId === "selection"],
      });
      if (!result || !result.length) return notify(t("noFiles"));
      await send(result, { referer: tab.url });
    }
  } catch (e) {
    notify(OFFLINE);
  }
});

// -------------------------------------------------- captura de downloads
chrome.downloads.onCreated.addListener(async (item) => {
  const c = await cfg();
  if (!c.intercept) return;
  const url = item.finalUrl || item.url;
  if (!/^(https?|ftp):/i.test(url)) return;              // blob:, data: etc. ficam no navegador
  if (skipOnce.has(url)) { skipOnce.delete(url); return; }
  if (item.state !== "in_progress") return;
  const size = item.totalBytes > 0 ? item.totalBytes : item.fileSize;
  if (c.minSizeKB > 0 && size > 0 && size < c.minSizeKB * 1024) return;
  if (domainSkipped(c, url, item.referrer || "")) return;
  let fname = item.filename ? item.filename.split(/[\\/]/).pop() : "";
  if (!fname) { try { fname = decodeURIComponent(new URL(url).pathname.split("/").pop() || ""); } catch (e) { fname = ""; } }
  if (extSkipped(c, fname)) return;
  if (c.skipHtml && (item.mime || "").toLowerCase().startsWith("text/html")) return;
  if (!(await ping())) return;                           // app fechado: o navegador baixa normalmente
  try {
    await chrome.downloads.cancel(item.id);
  } catch (e) {
    return;                                              // já terminou no navegador: fica como está
  }
  const [now] = await chrome.downloads.search({ id: item.id });
  if (now && now.state === "complete") return;           // arquivo pequeno que terminou antes do cancelamento
  chrome.downloads.erase({ id: item.id }).catch(() => {});
  try {
    const name = item.filename ? item.filename.split(/[\\/]/).pop() : "";
    await send([url], { referer: item.referrer || "", filename: name });
  } catch (e) {
    skipOnce.add(url);                                   // o app recusou: devolve o download ao navegador
    chrome.downloads.download({ url });
  }
});

// ------------------------------------------------ detecção de mídias
function mediaKey(tabId) { return `media_${tabId}`; }

async function getMedia(tabId) {
  const k = mediaKey(tabId);
  const o = await chrome.storage.session.get(k);
  return o[k] || [];
}

async function setBadge(tabId, n) {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#e3222f" });
    await chrome.action.setBadgeText({ tabId, text: n ? String(n) : "" });
  } catch (e) { /* aba fechada */ }
}

chrome.webRequest.onHeadersReceived.addListener(
  (d) => {
    if (d.tabId < 0 || d.statusCode >= 400) return;
    const h = {};
    for (const x of d.responseHeaders || []) h[x.name.toLowerCase()] = x.value || "";
    const ct = (h["content-type"] || "").toLowerCase();
    let path = "";
    try { path = new URL(d.url).pathname.toLowerCase(); } catch (e) { return; }
    let kind = null;
    if (ct.includes("mpegurl") || path.endsWith(".m3u8")) kind = "hls";
    else if (/^(video|audio)\//.test(ct) && !/mp2t|iso.segment/.test(ct) && !/\.(ts|m4s|aac)$/.test(path)) kind = "file";
    if (!kind) return;
    const size = parseInt(h["content-length"] || "0", 10) || 0;
    const range = h["content-range"] || "";
    const total = range.includes("/") ? parseInt(range.split("/")[1], 10) || size : size;
    if (kind === "file" && total && total < 300 * 1024) return;
    (async () => {
      const list = await getMedia(d.tabId);
      if (list.some((m) => m.url === d.url)) return;
      list.push({ url: d.url, kind, type: ct.split(";")[0], size: total, at: Date.now() });
      await chrome.storage.session.set({ [mediaKey(d.tabId)]: list.slice(-50) });
      await setBadge(d.tabId, list.length);
    })();
  },
  { urls: ["<all_urls>"], types: ["media", "xmlhttprequest", "other"] },
  ["responseHeaders"]
);

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.status === "loading" && info.url) {
    await chrome.storage.session.remove(mediaKey(tabId));
    await setBadge(tabId, 0);
  }
});
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove(mediaKey(tabId)));

// ------------------------------------------------ mensagens do popup
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      if (msg.type === "status") reply({ online: await ping(), cfg: await cfg() });
      else if (msg.type === "media") reply({ items: await getMedia(msg.tabId) });
      else if (msg.type === "send") { await send(msg.urls, msg.extra || {}); reply({ ok: true }); }
      else if (msg.type === "show") {
        await api("/show", { method: "POST", headers: { "Content-Type": "application/json", "X-Scarlet-Client": "extension" }, body: "{}" });
        reply({ ok: true });
      } else if (msg.type === "pageLinks") {
        const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: msg.tabId }, func: collectLinks, args: [false] });
        if (!result || !result.length) reply({ ok: false, error: t("noFilesPage") });
        else { await send(result, { referer: msg.url }); reply({ ok: true, count: result.length }); }
      } else reply({ ok: false });
    } catch (e) {
      reply({ ok: false, error: OFFLINE });
    }
  })();
  return true;
});
