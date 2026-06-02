(() => {
  const path = window.location.pathname;
  const base = path.startsWith('/android') ? '/android' : '';
  const api = `${base}/api`;

  const screen = document.getElementById('screen');
  const video = document.getElementById('webrtcVideo');
  const stage = document.getElementById('screenStage');
  const statusEl = document.getElementById('status');
  const touchDot = document.getElementById('touchDot');
  const keyboardDrawer = document.getElementById('keyboardDrawer');
  const textInput = document.getElementById('textInput');
  const approvalPanel = document.getElementById('approvalPanel');
  const screenPanel = document.getElementById('screenPanel');
  const secureOverlay = document.getElementById('secureOverlay');
  const secureNodes = document.getElementById('secureNodes');
  const secureTitle = document.getElementById('secureTitle');
  const chromeToggle = document.getElementById('chromeToggle');
  const approvalList = document.getElementById('approvalList');
  const approvalDetail = document.getElementById('approvalDetail');
  const approvalCount = document.getElementById('approvalCount');

  let nativeWidth = 1080;
  let nativeHeight = 2400;
  let pointerStart = null;
  let lastApprovals = [];
  const params = new URLSearchParams(window.location.search);
  const cosmeticParams = ['quality', 'fast', 'latency', 'verify', 'pwcheck', 'big', 'stream'];
  if (base === '/android' && !path.includes('/approvals') && cosmeticParams.some(key => params.has(key))) {
    for (const key of cosmeticParams) params.delete(key);
    const suffix = params.toString();
    history.replaceState(null, '', suffix ? `${base}?${suffix}` : base);
  }
  let useStream = params.get('poll') !== '1';
  let useWebRTC = useStream && params.get('video') !== '0' && params.get('mjpeg') !== '1';
  let pc = null;
  let chromeTimer = null;

  // Secure overlay debounce — don't flip rapidly
  let secureActive = false;
  let secureLastSeen = 0;
  const SECURE_HOLD_MS = 6000;

  function hideChrome() {
    document.body.classList.add('chrome-hidden');
  }

  function showChrome(ms = 2600) {
    document.body.classList.remove('chrome-hidden');
    if (chromeTimer) clearTimeout(chromeTimer);
    chromeTimer = setTimeout(hideChrome, ms);
  }

  async function jfetch(url, opts = {}) {
    const res = await fetch(url, {
      ...opts,
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
    return data;
  }

  function setStatus(text, good = true) {
    statusEl.textContent = text;
    statusEl.style.color = good ? '#94a3b8' : '#fca5a5';
  }

  async function tapAndroidPoint(point) {
    if (!point) return;
    await jfetch(`${api}/tap`, { method: 'POST', body: JSON.stringify({ x: point.x, y: point.y }) });
    setTimeout(refreshScreen, 80);
    setTimeout(loadSecureUi, 300);
  }

  // --- Secure overlay: position-based layout matching real screen ---

  function buildSecureOverlay(nodes, passwordNode) {
    const w = nativeWidth, h = nativeHeight;
    secureNodes.innerHTML = '';

    // Thin status bar at top
    const bar = document.createElement('div');
    bar.className = 'secure-bar';
    const pwLen = passwordNode ? (passwordNode.text || '').length : 0;
    bar.textContent = pwLen > 0 ? `🔒 Password (${pwLen} chars) — tap field or ENTER to submit` : '🔒 Secure screen';
    secureNodes.appendChild(bar);

    // Position each node at its real screen coordinates
    for (const node of nodes) {
      if (!node.bounds) continue;
      const b = node.bounds;
      const el = document.createElement(node.clickable && node.center ? 'button' : 'div');
      el.className = 'secure-spot';
      if (node.clickable) el.classList.add('clickable');
      if (node.focused) el.classList.add('focused');

      el.style.left = `${(b.x1 / w) * 100}%`;
      el.style.top = `${(b.y1 / h) * 100}%`;
      el.style.width = `${((b.x2 - b.x1) / w) * 100}%`;
      el.style.height = `${((b.y2 - b.y1) / h) * 100}%`;

      let label = '';
      if (node.password) {
        label = '••••••••';
      } else if (node.text) {
        label = node.text.length > 40 ? node.text.slice(0, 38) + '…' : node.text;
      } else if (node.description) {
        label = node.description.length > 40 ? node.description.slice(0, 38) + '…' : node.description;
      }
      el.textContent = label;

      if (node.clickable && node.center) {
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          tapAndroidPoint(node.center);
        });
      }
      secureNodes.appendChild(el);
    }

    // ENTER key button at bottom center (only if password present)
    if (passwordNode) {
      const enterEl = document.createElement('button');
      enterEl.className = 'secure-spot clickable';
      enterEl.style.left = '25%';
      enterEl.style.bottom = '3%';
      enterEl.style.width = '50%';
      enterEl.style.height = '5%';
      enterEl.style.top = 'auto';
      enterEl.textContent = '⏎ Submit (ENTER)';
      enterEl.addEventListener('click', async (e) => {
        e.stopPropagation();
        await jfetch(`${api}/key`, { method: 'POST', body: JSON.stringify({ key: 'ENTER' }) });
        setTimeout(refreshScreen, 100);
        setTimeout(loadSecureUi, 400);
      });
      secureNodes.appendChild(enterEl);
    }
  }

  async function loadSecureUi(force = false) {
    if (!force && !secureActive) return;
    try {
      const data = await jfetch(`${api}/ui`);
      if (!data.secure && !force) {
        exitSecureMode();
        return;
      }
      secureLastSeen = Date.now();
      if (!secureActive) {
        secureActive = true;
        secureOverlay.classList.remove('hidden');
      }
      const nodes = (data.nodes || []).filter(n => {
        // Keep clickable items or items with text/content
        if (n.clickable && n.center) return true;
        if (n.text || n.description) return true;
        if (n.password) return true;
        return false;
      });
      const passwordNode = nodes.find(n => n.password);
      buildSecureOverlay(nodes, passwordNode);
    } catch (err) {
      console.error('Secure overlay:', err);
      // Don't exit secure mode on transient errors
      secureLastSeen = Date.now();
    }
  }

  function exitSecureMode() {
    // Debounce: don't exit if we recently saw secure content
    if (Date.now() - secureLastSeen < SECURE_HOLD_MS) return;
    secureActive = false;
    secureOverlay.classList.add('hidden');
  }

  let screenLoading = false;
  function refreshScreen() {
    if (useStream) return;
    if (screenLoading) return;
    screenLoading = true;
    const next = new Image();
    next.onload = () => {
      screen.src = next.src;
      screenLoading = false;
    };
    next.onerror = () => {
      screenLoading = false;
    };
    next.src = `${api}/screenshot.png?ts=${Date.now()}`;
  }

  function waitIceGatheringComplete(peer) {
    if (peer.iceGatheringState === 'complete') return Promise.resolve();
    return new Promise(resolve => {
      const timeout = setTimeout(resolve, 2500);
      peer.addEventListener('icegatheringstatechange', () => {
        if (peer.iceGatheringState === 'complete') {
          clearTimeout(timeout);
          resolve();
        }
      });
    });
  }

  async function startWebRTC() {
    if (!window.RTCPeerConnection) {
      setStatus('WebRTC unavailable; using stream fallback', false);
      startStream();
      return;
    }
    useStream = true;
    useWebRTC = true;
    screenLoading = false;
    screen.onerror = null;
    try {
      if (pc) pc.close();
      let sourceLabel = 'WebRTC video';
      pc = new RTCPeerConnection({ iceServers: [] });
      pc.addTransceiver('video', { direction: 'recvonly' });
      pc.ontrack = ev => {
        video.srcObject = ev.streams[0];
        video.classList.remove('hidden');
        screen.classList.add('hidden');
        video.play().catch(() => {});
        setStatus(`Android online · ${sourceLabel} · ${nativeWidth}×${nativeHeight}`);
      };
      pc.onconnectionstatechange = () => {
        if (!pc) return;
        if (pc.connectionState === 'connected') {
          setStatus(`Android online · ${sourceLabel} · ${nativeWidth}×${nativeHeight}`);
        } else if (['failed', 'disconnected'].includes(pc.connectionState)) {
          setStatus('WebRTC dropped; using stream fallback', false);
          startStream();
        }
      };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await waitIceGatheringComplete(pc);
      const answer = await jfetch(`${api}/webrtc/offer`, {
        method: 'POST',
        body: JSON.stringify({ sdp: pc.localDescription.sdp, type: pc.localDescription.type }),
      });
      sourceLabel = answer.source === 'scrcpy-native' ? 'native video' : 'WebRTC video';
      await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
      setTimeout(() => {
        if (pc && !['connected', 'completed'].includes(pc.iceConnectionState)) {
          setStatus('WebRTC did not connect; using stream fallback', false);
          startStream();
        }
      }, 6000);
    } catch (err) {
      setStatus(`WebRTC failed: ${err.message}; using stream fallback`, false);
      startStream();
    }
  }

  function startStream() {
    useWebRTC = false;
    useStream = true;
    if (pc) {
      const old = pc;
      pc = null;
      old.close().catch(() => {});
    }
    video.pause();
    video.srcObject = null;
    video.classList.add('hidden');
    screen.classList.remove('hidden');
    screenLoading = false;
    screen.onerror = () => {
      useStream = false;
      setStatus('Stream failed; using polling fallback', false);
      refreshScreen();
    };
    screen.src = `${api}/stream.mjpeg?ts=${Date.now()}`;
  }

  async function pollStatus() {
    try {
      const data = await jfetch(`${api}/status`);
      const s = data.screen || {};
      if (s.width && s.height) {
        nativeWidth = s.width;
        nativeHeight = s.height;
      }
      if (data.secure) {
        setStatus(`Android online · secure screen · ${nativeWidth}×${nativeHeight}`);
        secureLastSeen = Date.now();
        if (!secureActive) {
          secureActive = true;
          secureOverlay.classList.remove('hidden');
        }
        loadSecureUi(true);
      } else if (secureActive) {
        exitSecureMode();
        if (!secureActive) setStatus(data.booted ? `Android online · ${nativeWidth}×${nativeHeight}` : 'Android connected, still booting…', data.booted);
      } else {
        setStatus(data.booted ? `Android online · ${nativeWidth}×${nativeHeight}` : 'Android connected, still booting…', data.booted);
      }
    } catch (err) {
      // Don't exit secure mode on transient API errors
      if (!secureActive) setStatus(`Offline: ${err.message}`, false);
    }
  }

  function eventToAndroid(ev) {
    const rect = stage.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (ev.clientY - rect.top) / rect.height));
    return { x: Math.round(x * nativeWidth), y: Math.round(y * nativeHeight), px: ev.clientX - rect.left, py: ev.clientY - rect.top };
  }

  function showDot(pt) {
    touchDot.style.left = `${pt.px}px`;
    touchDot.style.top = `${pt.py}px`;
    touchDot.classList.remove('hidden');
    setTimeout(() => touchDot.classList.add('hidden'), 180);
  }

  stage.addEventListener('pointerdown', ev => {
    ev.preventDefault();
    hideChrome();
    stage.setPointerCapture(ev.pointerId);
    pointerStart = { ...eventToAndroid(ev), t: Date.now() };
    showDot(pointerStart);
  });

  stage.addEventListener('pointerup', async ev => {
    ev.preventDefault();
    if (!pointerStart) return;
    const end = eventToAndroid(ev);
    const dx = Math.abs(end.x - pointerStart.x);
    const dy = Math.abs(end.y - pointerStart.y);
    const dt = Date.now() - pointerStart.t;
    try {
      if (dx < 35 && dy < 35 && dt < 700) {
        await jfetch(`${api}/tap`, { method: 'POST', body: JSON.stringify({ x: end.x, y: end.y }) });
      } else {
        await jfetch(`${api}/swipe`, { method: 'POST', body: JSON.stringify({ x1: pointerStart.x, y1: pointerStart.y, x2: end.x, y2: end.y, duration_ms: Math.max(120, dt) }) });
      }
      setTimeout(refreshScreen, 80);
    } catch (err) {
      setStatus(`Touch failed: ${err.message}`, false);
    } finally {
      pointerStart = null;
    }
  });

  stage.addEventListener('pointercancel', () => { pointerStart = null; });
  chromeToggle.addEventListener('click', ev => {
    ev.preventDefault();
    showChrome(3500);
  });

  document.querySelectorAll('[data-key]').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await jfetch(`${api}/key`, { method: 'POST', body: JSON.stringify({ key: btn.dataset.key }) });
        setTimeout(refreshScreen, 80);
      } catch (err) { setStatus(`Key failed: ${err.message}`, false); }
    });
  });

  document.getElementById('keyboardBtn').addEventListener('click', () => {
    keyboardDrawer.classList.remove('hidden');
    textInput.focus();
  });
  document.getElementById('closeKeyboard').addEventListener('click', () => keyboardDrawer.classList.add('hidden'));
  document.getElementById('sendText').addEventListener('click', async () => {
    try {
      await jfetch(`${api}/type`, { method: 'POST', body: JSON.stringify({ text: textInput.value }) });
      textInput.value = '';
      keyboardDrawer.classList.add('hidden');
      setTimeout(refreshScreen, 80);
    } catch (err) { setStatus(`Typing failed: ${err.message}`, false); }
  });
  document.getElementById('shotBtn').addEventListener('click', () => {
    if (useWebRTC) startWebRTC();
    else if (useStream) startStream();
    else refreshScreen();
  });

  document.getElementById('approvalsBtn').addEventListener('click', () => showApprovals());
  document.getElementById('backToPhone').addEventListener('click', () => showPhone());

  async function loadApprovals() {
    try {
      const data = await jfetch(`${api}/approvals`);
      lastApprovals = data.approvals || [];
      const pending = lastApprovals.filter(a => a.status === 'pending' || a.status === 'editing').length;
      approvalCount.textContent = String(pending);
      renderApprovalList();
      return lastApprovals;
    } catch (err) {
      approvalCount.textContent = '!';
      return [];
    }
  }

  function riskBadge(risk) {
    const r = (risk || 'medium').toLowerCase();
    return `<span class="badge ${r}">${r.toUpperCase()}</span>`;
  }

  function renderApprovalList() {
    approvalList.innerHTML = '';
    if (!lastApprovals.length) {
      approvalList.innerHTML = '<div class="approval-card"><div class="approval-title">No approvals yet</div><div class="approval-meta">Pending requests will appear here.</div></div>';
      return;
    }
    for (const a of lastApprovals) {
      const card = document.createElement('button');
      card.className = `approval-card ${a.status}`;
      card.innerHTML = `<div class="approval-title">${riskBadge(a.risk)} ${escapeHtml(a.action)}</div><div class="approval-meta">${escapeHtml(a.app)} · ${escapeHtml(a.status)} · ${new Date(a.created_at).toLocaleString()}</div>`;
      card.addEventListener('click', () => renderApprovalDetail(a.id));
      approvalList.appendChild(card);
    }
  }

  async function renderApprovalDetail(id) {
    const data = await jfetch(`${api}/approvals/${id}`);
    const a = data.approval;
    approvalDetail.classList.remove('hidden');
    approvalDetail.innerHTML = `
      <div class="approval-card ${a.status}">
        <div class="approval-title">${riskBadge(a.risk)} ${escapeHtml(a.action)}</div>
        <div class="approval-meta">${escapeHtml(a.app)} · ${escapeHtml(a.status)}</div>
        <p>${escapeHtml(a.message).replace(/\n/g, '<br>')}</p>
      </div>
      <img src="${base}${a.screenshot}?ts=${Date.now()}" alt="Approval screenshot" />
      <div class="approval-actions">
        <button class="approve" id="approveNow">Approve</button>
        <button class="deny" id="denyNow">Deny</button>
        <button class="edit" id="editNow">Edit</button>
      </div>
    `;
    document.getElementById('approveNow').onclick = () => decide(id, 'approve');
    document.getElementById('denyNow').onclick = () => decide(id, 'deny');
    document.getElementById('editNow').onclick = async () => {
      await decide(id, 'edit', false);
      showPhone();
    };
  }

  async function decide(id, action, returnToList = true) {
    await jfetch(`${api}/approvals/${id}/${action}`, { method: 'POST' });
    await loadApprovals();
    if (returnToList) approvalDetail.classList.add('hidden');
  }

  async function showApprovals() {
    screenPanel.classList.add('hidden');
    approvalPanel.classList.remove('hidden');
    await loadApprovals();
    const match = window.location.pathname.match(/approvals\/([^/]+)/);
    if (match) renderApprovalDetail(match[1]);
  }

  function showPhone() {
    approvalPanel.classList.add('hidden');
    screenPanel.classList.remove('hidden');
    history.replaceState(null, '', base || '/');
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  document.getElementById('notifyBtn').addEventListener('click', async () => {
    if (!('Notification' in window)) return alert('Notifications not supported here.');
    const perm = await Notification.requestPermission();
    if (perm === 'granted') new Notification('AgentPhone approvals enabled');
  });

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register(`${base}/sw.js`).catch(() => {});
  }

  if (path.includes('/approvals')) showApprovals();
  pollStatus();
  loadApprovals();
  showChrome(2200);
  if (useWebRTC) startWebRTC();
  else if (useStream) startStream();
  else refreshScreen();
  setInterval(() => {
    if (!document.hidden && !useStream) refreshScreen();
  }, 350);
  setInterval(pollStatus, 5000);
  setInterval(loadApprovals, 4000);
  setInterval(() => loadSecureUi(false), 2000);
})();