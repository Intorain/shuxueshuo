/* Prototype only: login, quota and history are mocked; ?as=user|guest|empty switches the state. */
const as = new URLSearchParams(location.search).get('as') || 'user';
let loggedIn = as !== 'guest';
const $ = selector => document.querySelector(selector);

const HISTORY = [
  {q: '已知函数 $f(x)=x^2-2ax+3$。（1）若对任意 $x\\in\\mathbb R$，$f(x)\\ge0$ 恒成立…', meta: '今天 10:58 · 正在识别', status: 'doing', label: '识别中', href: 'problem.html?demo=multi'},
  {q: '若不等式 $-x^2+2x+3\\le a^2-3a$ 对任意实数 $x$ 恒成立，求实数 $a$ 的取值范围。', meta: '今天 10:32 · 已用 2 种方法做完', status: 'done', label: '已完成', href: '/lab/graph-walk/quadratic-always-q01/'},
  {q: '若 $kx^2-kx+1>0$ 对一切实数 $x$ 恒成立，求实数 $k$ 的取值范围。', meta: '昨天 21:15 · 做到第 3 步', status: 'half', label: '继续做', href: '#'},
  {q: '求函数 $y=\\sin x+\\cos x$ 的最大值。', meta: '昨天 20:40 · 题型暂不支持，已记录', status: 'unsupported', label: '暂不支持', href: 'problem.html?demo=unsupported'},
];

function renderMath(root) {
  window.renderMathInElement?.(root, {delimiters: [{left: '$', right: '$', display: false}], throwOnError: false});
}

function renderAccount() {
  $('#sq-account').innerHTML = loggedIn
    ? '<span class="sq-account">138****6620</span>'
    : '<button type="button" class="sq-ghost" data-login style="min-height:34px;padding:0 12px;font-size:14px">登录</button>';
  $('#sq-quota').innerHTML = loggedIn ? '今天还可以拍 <b>8</b> 道题' : '登录后每天免费学 10 道';
  const list = $('#sq-history-list');
  $('#sq-history-guest').hidden = loggedIn;
  $('#sq-history-all').hidden = !loggedIn || as === 'empty';
  list.hidden = !loggedIn;
  if (!loggedIn) return;
  const returning = as !== 'empty';
  // Returning students come back to continue, so their recent problems sit right under the camera.
  if (returning) $('.sq-hero').after($('#sq-history'));
  list.innerHTML = !returning
    ? '<li class="sq-history-empty">还没有拍过题。拍一道恒成立问题试试？</li>'
    : HISTORY.slice(0, 3).map(item => `<li><a href="${item.href}"><span class="sq-history-q">${item.q}</span><span class="sq-history-meta">${item.meta}</span><span class="sq-status" data-status="${item.status}">${item.label}</span></a></li>`).join('');
  renderMath(list);
}

function toast(text) {
  const el = $('#sq-toast');
  el.textContent = text; el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 2600);
}

/* What to resume after login: 'shoot' or an album image to hand to the camera page. */
let pending = null;

/* Album photos go through the same question picker; scaled down so sessionStorage can hold them in the prototype. */
async function handOff(file) {
  const img = new Image();
  img.src = URL.createObjectURL(file);
  await img.decode();
  const scale = Math.min(1, 2200 / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = Object.assign(document.createElement('canvas'), {width: Math.round(img.naturalWidth * scale), height: Math.round(img.naturalHeight * scale)});
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  try { sessionStorage.setItem('sq-page', canvas.toDataURL('image/jpeg', .88)); } catch { toast('图片太大了，换一张试试'); return; }
  location.href = 'camera.html?from=album';
}

function proceed(action) {
  if (!loggedIn) { pending = action; $('#sq-login').showModal(); return; }
  if (action === 'shoot') location.href = 'camera.html';
  else handOff(action);
}

document.addEventListener('DOMContentLoaded', () => {
  renderAccount();
  renderMath(document.querySelector('.sq-examples'));
  $('#sq-file').addEventListener('change', event => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    if (!/^image\//.test(file.type)) { toast('请选择 PNG、JPEG 或 WebP 图片'); return; }
    if (file.size > 20 * 1024 * 1024) { toast('图片超过 20 MB，请压缩后再试'); return; }
    proceed(file);
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-shoot]')) { event.preventDefault(); proceed('shoot'); }
    if (event.target.closest('[data-login]')) $('#sq-login').showModal();
  });
  $('#sq-login').addEventListener('close', () => {
    if ($('#sq-login').returnValue !== 'ok') { pending = null; return; }
    loggedIn = true; renderAccount();
    if (pending) proceed(pending); else toast('已登录');
    pending = null;
  });

  const dock = $('#sq-dock');
  new IntersectionObserver(([entry]) => { dock.hidden = entry.isIntersecting; }).observe($('#sq-capture'));
});
