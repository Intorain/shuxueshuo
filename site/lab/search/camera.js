/* Question boxes come from the local OCR segmentation API (run_site.py, POST /api/search/pages);
   without it the page falls back to mocked boxes. ?sim=1 simulates the viewfinder with a
   composed worksheet, ?sim=denied the no-permission state, ?demo=page skips the viewfinder. */
const params = new URLSearchParams(location.search);
const sim = params.get('sim');
const $ = selector => document.querySelector(selector);

/* Mock worksheet: known question boxes stand in for the detection service. */
const PAGE = [
  {src: 'sample-q01.png', demo: 'ok'},
  {text: '求函数 y = sin x + cos x 的最大值。', h: 200, demo: 'unsupported'},
  {src: 'sample-q04.png', demo: 'ok'},
  {src: 'sample-q10.png', demo: 'multi'},
  {src: 'sample-q02.png', demo: 'ok'},
  {src: 'sample-q11.png', demo: 'ok'},
];
const MOCK_BANDS = [[.08, .28], [.38, .26], [.66, .26]].map(([y, h]) => ({x: .05, y, w: .9, h, demo: 'ok'}));

let stream = null;
let page = null;
let pageId = null;
let detection = null;
let boxes = [];
let selected = 0;
let crop = null;
const MIN = .08;

const load = src => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => resolve(img); img.onerror = reject; img.src = src;
});

function toast(text) {
  const el = $('#sq-toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 2400);
}

async function buildPage() {
  const W = 2100, pad = 90, gap = 46, head = 220, number = 110, inner = 1920 - number;
  const imgs = await Promise.all(PAGE.map(item => item.src ? load(item.src) : null));
  const heights = PAGE.map((item, i) => imgs[i] ? imgs[i].naturalHeight * inner / imgs[i].naturalWidth : item.h);
  const H = head + heights.reduce((sum, h) => sum + h + gap, 0) + pad;
  const canvas = Object.assign(document.createElement('canvas'), {width: W, height: H});
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#f3f0e8'; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#2a2a2a'; ctx.textAlign = 'center';
  ctx.font = 'bold 66px "Songti SC", "STSong", serif';
  ctx.fillText('高一数学 · 不等式恒成立专项练习', W / 2, 112);
  ctx.font = '42px "Songti SC", "STSong", serif';
  ctx.fillText('班级 ________    姓名 ________', W / 2, 180);
  ctx.textAlign = 'left';
  ctx.globalCompositeOperation = 'multiply';
  const found = [];
  let y = head;
  PAGE.forEach((item, i) => {
    const h = heights[i];
    ctx.font = '62px "Songti SC", "STSong", serif';
    const baseline = imgs[i] ? y + Math.min(h, 140) / 2 + 22 : y + h / 2 + 20;
    ctx.fillText(`${i + 1}．`, pad, baseline);
    if (imgs[i]) ctx.drawImage(imgs[i], pad + number, y, inner, h);
    else ctx.fillText(item.text, pad + number, baseline);
    found.push({x: (pad - 24) / W, y: (y - 14) / H, w: (number + inner + 48) / W, h: (h + 28) / H, demo: item.demo, number: i + 1});
    y += h + gap;
  });
  ctx.globalCompositeOperation = 'source-over';
  const shade = ctx.createRadialGradient(W / 2, H / 2, H * .3, W / 2, H / 2, H * .8);
  shade.addColorStop(0, 'rgba(0,0,0,0)'); shade.addColorStop(1, 'rgba(60,45,20,.16)');
  ctx.fillStyle = shade; ctx.fillRect(0, 0, W, H);
  return {url: canvas.toDataURL('image/jpeg', .9), boxes: found};
}

/* ---------- 取景 ---------- */
function showDenied() {
  $('#cm-denied').hidden = false;
  $('#cm-hint').hidden = true;
  $('.cm-bar').hidden = true;
}

async function startCamera() {
  if (sim === '1') {
    page = await buildPage();
    $('#cm-video').hidden = true;
    Object.assign($('#cm-sim'), {src: page.url, hidden: false});
    return;
  }
  if (sim === 'denied' || !navigator.mediaDevices?.getUserMedia) return showDenied();
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1440}}, audio: false});
    $('#cm-video').srcObject = stream;
  } catch {
    showDenied();
  }
}

function stopCamera() {
  for (const track of stream?.getTracks() || []) track.stop();
  stream = null;
}

const toBlob = async url => (await fetch(url)).blob();

async function shoot() {
  if (page) return openPick(page.url, await toBlob(page.url), page.boxes);
  const video = $('#cm-video');
  if (!video.videoWidth) return;
  const canvas = Object.assign(document.createElement('canvas'), {width: video.videoWidth, height: video.videoHeight});
  canvas.getContext('2d').drawImage(video, 0, 0);
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .92));
  openPick(URL.createObjectURL(blob), blob, MOCK_BANDS);
}

async function fromFile(file) {
  if (!file) return;
  if (!/^image\//.test(file.type)) { toast('请选择 PNG、JPEG 或 WebP 图片'); return; }
  openPick(URL.createObjectURL(file), file, MOCK_BANDS);
}

/* Real boxes from OCR segmentation; mocked ones only when the local API is unavailable. */
async function detect(blob, fallback) {
  try {
    const response = await fetch('/api/search/pages', {method: 'POST', body: blob, headers: {'Content-Type': blob.type || 'image/jpeg'}});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    pageId = result.page_id;
    const seconds = Object.values(result.latency_ms).reduce((a, b) => a + b, 0) / 1000;
    const rect = ([x0, y0, x1, y1]) => ({x: x0, y: y0, w: x1 - x0, h: y1 - y0});
    /* box: non-overlapping tap area drawn on the photo; crop: what is sent, may reach into a neighbour. */
    const found = result.regions.map(r => ({...rect(r.box), number: r.number, crop: rect(r.crop || r.box)}));
    const note = `OCR 切题 ${seconds.toFixed(1)} 秒 · ${found.length} 道` + (result.mode === 'whole_content' ? ' · 没找到题号，整块作为一题' : '');
    return {found, note};
  } catch {
    pageId = null;
    return {found: fallback, note: '离线原型：题目框为模拟（本地切题接口不可用）'};
  }
}

/* ---------- 选题 ---------- */
async function openPick(url, blob, fallback) {
  stopCamera();
  const photo = $('#cm-photo');
  photo.src = url;
  const started = performance.now();
  /* Set before the pick view (and its "whole image" button) appears; go() waits on it. */
  detection = Promise.all([detect(blob, fallback), photo.decode().catch(() => {})]).then(([result]) => result);
  document.body.dataset.state = 'pick';
  $('#cm-shoot').hidden = true;
  $('#cm-pick').hidden = false;
  const {found, note} = await detection;
  await new Promise(resolve => setTimeout(resolve, Math.max(0, 700 - (performance.now() - started))));
  Object.assign($('#cm-proto-note'), {textContent: note, hidden: false});
  $('#cm-finding').hidden = true;
  $('#cm-finding-text').hidden = true;
  boxes = found;
  if (!boxes.length) { toast('没找到题目，手动框一下吧'); return startCrop(); }
  renderBoxes();
  $('#cm-choose').hidden = false;
  /* Students aim at the question they want, so preselect the box nearest the middle of the shot. */
  const dist = box => Math.abs(box.y + box.h / 2 - .5);
  select(boxes.reduce((best, box, i) => dist(box) < dist(boxes[best]) ? i : best, 0));
}

const label = i => boxes[i].number ?? i + 1;

function renderBoxes() {
  $('#cm-boxes').innerHTML = boxes.map((box, i) =>
    `<button type="button" class="cm-box" data-box="${i}" aria-label="第 ${label(i)} 题" style="left:${box.x * 100}%;top:${box.y * 100}%;width:${box.w * 100}%;height:${box.h * 100}%;animation-delay:${i * 60}ms"><b>${label(i)}</b></button>`).join('');
  $('#cm-chips').innerHTML = boxes.map((_, i) => `<button type="button" role="tab" data-box="${i}">${label(i)}</button>`).join('');
}

function cropUrl(rect, max) {
  const img = $('#cm-photo');
  const sx = rect.x * img.naturalWidth, sy = rect.y * img.naturalHeight, sw = rect.w * img.naturalWidth, sh = rect.h * img.naturalHeight;
  const scale = Math.min(1, max / Math.max(sw, sh));
  const canvas = Object.assign(document.createElement('canvas'), {width: Math.round(sw * scale), height: Math.round(sh * scale)});
  canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', .9);
}

function select(i) {
  selected = i;
  for (const el of document.querySelectorAll('.cm-box')) el.setAttribute('aria-pressed', String(Number(el.dataset.box) === i));
  for (const el of $('#cm-chips').children) el.setAttribute('aria-selected', String(Number(el.dataset.box) === i));
  $('#cm-chips').children[i]?.scrollIntoView({block: 'nearest', inline: 'center'});
  $('#cm-chosen-img').src = cropUrl(boxes[i].crop || boxes[i], 900);
  $('#cm-title').textContent = `第 ${label(i)} 题`;
}

/* Live: the server crops the full-resolution page and starts stage one. Offline (the upload
   failed, not merely pending): mocked run. */
async function go(rect) {
  const buttons = [$('#cm-go'), $('#cm-crop-go'), $('#cm-whole')];
  for (const button of buttons) button.disabled = true;
  try {
    await detection;
    if (!pageId) {
      try { sessionStorage.setItem('sq-image', cropUrl(rect, 1600)); } catch { sessionStorage.removeItem('sq-image'); }
      location.href = `problem.html?demo=${rect.demo || 'ok'}&fresh=1`;
      return;
    }
    const response = await fetch('/api/search/problems', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({page_id: pageId, box: [rect.x, rect.y, rect.x + rect.w, rect.y + rect.h]}),
    });
    const body = await response.json().catch(() => ({}));
    if (response.ok) { location.href = `problem.html?search=${body.search_id}`; return; }
    const detail = String(body.detail || response.status);
    toast(detail.startsWith('stage_one.disabled') ? '本地没开启阶段①：用 RUN_LLM_INTEGRATION=1 启动 run_site.py' : `提交失败：${detail}`);
  } catch {
    toast('提交失败，请检查连接后重试');
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

/* ---------- 手动框选 ---------- */
function placeCrop() {
  Object.assign($('#cm-crop').style, {left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.w * 100}%`, height: `${crop.h * 100}%`});
}

function startCrop() {
  const base = boxes[selected]?.crop || boxes[selected] || {x: .08, y: .3, w: .84, h: .3};
  crop = {x: base.x, y: base.y, w: base.w, h: base.h};
  placeCrop();
  $('#cm-crop').hidden = false;
  $('#cm-boxes').classList.add('is-cropping');
  $('#cm-choose').hidden = true;
  $('#cm-cropping').hidden = false;
  $('#cm-title').textContent = '手动框选';
}

function endCrop() {
  if (!boxes.length) return reshoot();
  $('#cm-crop').hidden = true;
  $('#cm-boxes').classList.remove('is-cropping');
  $('#cm-cropping').hidden = true;
  $('#cm-choose').hidden = false;
  select(selected);
}

function bindCrop() {
  const stage = $('#cm-stage');
  let drag = null;
  stage.addEventListener('pointerdown', event => {
    if (!event.target.closest('#cm-crop')) return;
    event.preventDefault();
    stage.setPointerCapture(event.pointerId);
    drag = {handle: event.target.dataset.handle || 'move', start: {...crop}, x: event.clientX, y: event.clientY, rect: stage.getBoundingClientRect()};
  });
  stage.addEventListener('pointermove', event => {
    if (!drag) return;
    const dx = (event.clientX - drag.x) / drag.rect.width, dy = (event.clientY - drag.y) / drag.rect.height;
    const s = drag.start, clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    if (drag.handle === 'move') {
      crop = {x: clamp(s.x + dx, 0, 1 - s.w), y: clamp(s.y + dy, 0, 1 - s.h), w: s.w, h: s.h};
    } else {
      let left = s.x, top = s.y, right = s.x + s.w, bottom = s.y + s.h;
      if (drag.handle.includes('w')) left = clamp(left + dx, 0, right - MIN);
      if (drag.handle.includes('e')) right = clamp(right + dx, left + MIN, 1);
      if (drag.handle.includes('n')) top = clamp(top + dy, 0, bottom - MIN);
      if (drag.handle.includes('s')) bottom = clamp(bottom + dy, top + MIN, 1);
      crop = {x: left, y: top, w: right - left, h: bottom - top};
    }
    placeCrop();
  });
  const end = () => { drag = null; };
  stage.addEventListener('pointerup', end);
  stage.addEventListener('pointercancel', end);
}

function reshoot() {
  location.href = sim ? `camera.html?sim=${sim}` : 'camera.html';
}

document.addEventListener('DOMContentLoaded', () => {
  $('#cm-shutter').addEventListener('click', shoot);
  for (const id of ['#cm-album', '#cm-system']) $(id).addEventListener('change', event => fromFile(event.target.files[0]));
  $('#cm-retake').addEventListener('click', reshoot);
  $('#cm-whole').addEventListener('click', () => go({x: 0, y: 0, w: 1, h: 1, demo: 'ok'}));
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-box]');
    if (target) select(Number(target.dataset.box));
  });
  $('#cm-go').addEventListener('click', () => go({...boxes[selected].crop || boxes[selected], demo: boxes[selected].demo}));
  $('#cm-manual').addEventListener('click', startCrop);
  $('#cm-crop-cancel').addEventListener('click', endCrop);
  $('#cm-crop-go').addEventListener('click', () => go({...crop, demo: boxes[selected]?.demo}));
  bindCrop();

  const handoff = params.get('from') === 'album' && sessionStorage.getItem('sq-page');
  if (handoff) { $('#cm-video').hidden = true; toBlob(handoff).then(blob => openPick(handoff, blob, MOCK_BANDS)); return; }
  if (params.get('demo') === 'page') {
    buildPage().then(async built => { page = built; openPick(page.url, await toBlob(page.url), page.boxes); });
    return;
  }
  startCamera();
});
