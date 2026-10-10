const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
if (tg?.setHeaderColor) tg.setHeaderColor("#100d1d");
if (tg?.setBackgroundColor) tg.setBackgroundColor("#100d1d");

let state = { stars: 0, nfts: [], user: null, last_daily: null };
const $ = (id) => document.getElementById(id);
const rarityEmoji = {"Обычный":"🐈","Редкий":"💎","Эпический":"🎭","Легендарный":"🐉","Мифический":"👻"};
const authData = tg?.initData || "";

async function api(path, method="GET") {
  const response = await fetch(path, {
    method,
    headers: {"Authorization": "tma " + authData, "Content-Type":"application/json"}
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "Не удалось выполнить действие.");
  return data;
}
function toast(message) {
  const el = $("toast"); el.textContent = message; el.classList.add("show");
  clearTimeout(window.toastTimer); window.toastTimer = setTimeout(()=>el.classList.remove("show"), 2600);
}
function setBusy(button, busy, label) {
  if (busy) { button.dataset.oldText = button.textContent; button.textContent = "Подожди…"; button.disabled = true; }
  else { button.textContent = label || button.dataset.oldText; button.disabled = false; }
}
function render() {
  $("stars").textContent = Number(state.stars).toLocaleString("ru-RU");
  $("nftCount").textContent = state.nfts.length;
  $("avatar").textContent = (state.user?.first_name || "G").slice(0,1).toUpperCase();
  const dailyClaimed = state.last_daily === new Date().toISOString().slice(0,10);
  $("dailyBtn").disabled = dailyClaimed;
  $("dailyBtn").textContent = dailyClaimed ? "Получено сегодня ✓" : "Забрать +100 ✦";
  const inventory = $("inventory");
  if (!state.nfts.length) {
    inventory.innerHTML = '<div class="empty-state"><div>🪄</div><b>Коллекция пока пуста</b><p>Открой свой первый кейс и найди сокровище.</p></div>';
    return;
  }
  inventory.innerHTML = state.nfts.map(n => `
    <article class="nft-card">
      <div class="nft-art">${rarityEmoji[n.rarity] || "🎁"}</div>
      <div class="nft-info"><b>${escapeHtml(n.name)}</b><div class="nft-meta">Уровень ${n.level} · улучшение ${Number(n.level)*40} ✦</div><span class="rarity">${escapeHtml(n.rarity)}</span></div>
      <button class="upgrade" data-upgrade="${n.id}">⬆ ${Number(n.level)*40} ✦</button>
    </article>`).join("");
  inventory.querySelectorAll("[data-upgrade]").forEach(btn => btn.addEventListener("click", () => upgradeNft(Number(btn.dataset.upgrade), btn)));
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
async function refresh() {
  const data = await api("/api/me");
  state = {...state, ...data};
  render();
}
$("dailyBtn").addEventListener("click", async () => {
  setBusy($("dailyBtn"), true);
  try { const data = await api("/api/daily", "POST"); state.stars=data.stars; state.last_daily=new Date().toISOString().slice(0,10); render(); toast(`Получено +${data.reward} ✦!`); tg?.HapticFeedback?.notificationOccurred("success"); }
  catch(e) { toast(e.message); }
  finally { setBusy($("dailyBtn"), false, state.last_daily===new Date().toISOString().slice(0,10) ? "Получено сегодня ✓" : "Забрать +100 ✦"); render(); }
});
$("caseBtn").addEventListener("click", async () => {
  setBusy($("caseBtn"), true);
  try {
    const data = await api("/api/case", "POST"); state.stars=data.stars;
    state.nfts.unshift(data.nft); render();
    $("modalEmoji").textContent=rarityEmoji[data.nft.rarity] || "🎁";
    $("modalName").textContent=data.nft.name; $("modalRarity").textContent=data.nft.rarity;
    $("modal").classList.add("show"); tg?.HapticFeedback?.notificationOccurred("success");
  } catch(e) { toast(e.message); }
  finally { setBusy($("caseBtn"), false, "🎁\n Mystery Gift"); }
});
async function upgradeNft(id, btn) {
  setBusy(btn, true);
  try { const data=await api(`/api/upgrade/${id}`, "POST"); state.stars=data.stars; const n=state.nfts.find(x=>x.id===id); if(n)n.level=data.level; render(); toast(`NFT улучшен до уровня ${data.level}!`); tg?.HapticFeedback?.notificationOccurred("success"); }
  catch(e) { toast(e.message); }
  finally { if(document.body.contains(btn)) setBusy(btn, false); }
}
function closeModal(){ $("modal").classList.remove("show"); }
$("closeModal").addEventListener("click", closeModal);
$("modalOk").addEventListener("click", closeModal);
$("modal").addEventListener("click", e=>{if(e.target===$("modal"))closeModal();});
document.querySelectorAll(".nav-item").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(x=>x.classList.remove("active")); btn.classList.add("active");
  if(btn.dataset.tab==="collection") document.querySelector(".inventory-head").scrollIntoView({behavior:"smooth",block:"start"});
  else if(btn.dataset.tab==="home") window.scrollTo({top:0,behavior:"smooth"});
  else toast(`${state.user?.first_name || "Игрок"} · ${state.stars} ✦ · ${state.nfts.length} NFT`);
}));
(async function init(){
  try {
    if (!authData && !location.hostname.includes("localhost")) {
      // Server will reject requests without valid Telegram initData.
    }
    await refresh();
  } catch(e) {
    document.querySelector("main").innerHTML = `<section class="hero panel"><div class="eyebrow">GIFTGRAM</div><h1>Открой приложение<br><span>через Telegram</span></h1><p>${escapeHtml(e.message)} Убедись, что Mini App опубликована по HTTPS и открыта кнопкой из бота.</p></section>`;
  }
})();
