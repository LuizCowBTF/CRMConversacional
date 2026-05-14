/* =========================================================================
   CRM Conversacional — JavaScript
   ========================================================================= */

// Auto-scroll para o final da conversa
document.addEventListener('DOMContentLoaded', () => {
  const chatMessages = document.getElementById('chatMessages');
  if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;

  initChatInput();
  initKanbanDragDrop();
  initSnippetAutocomplete();
  initTemplateInsertion();
  initFollowupInsertion();
  initAutoResize();
});

/* =========================================================================
   AUTO RESIZE TEXTAREA
   ========================================================================= */
function initAutoResize() {
  document.querySelectorAll('textarea.auto-resize').forEach(t => {
    t.addEventListener('input', () => {
      t.style.height = 'auto';
      t.style.height = Math.min(t.scrollHeight, 140) + 'px';
    });
  });
}

/* =========================================================================
   CHAT INPUT — Enter envia, Shift+Enter quebra linha
   ========================================================================= */
function initChatInput() {
  const form = document.getElementById('chatForm');
  if (!form) return;
  const textarea = form.querySelector('textarea[name=body]');
  if (!textarea) return;

  textarea.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (textarea.value.trim()) form.submit();
    }
  });
}

/* =========================================================================
   SNIPPETS — autocomplete com /
   ========================================================================= */
let snippetsCache = null;

async function loadSnippets() {
  if (snippetsCache) return snippetsCache;
  try {
    const r = await fetch('/api/snippets');
    snippetsCache = await r.json();
  } catch(e) { snippetsCache = []; }
  return snippetsCache;
}

function initSnippetAutocomplete() {
  const form = document.getElementById('chatForm');
  if (!form) return;
  const textarea = form.querySelector('textarea[name=body]');
  if (!textarea) return;

  const popup = document.getElementById('snippetPopup');
  if (!popup) return;

  let active = false;
  let filtered = [];
  let selectedIdx = 0;

  textarea.addEventListener('input', async e => {
    const val = textarea.value;
    // detecta se está digitando um comando: começou com / e ainda não tem espaço
    const m = val.match(/(^|\s)(\/[a-z0-9_]*)$/i);
    if (m) {
      const snippets = await loadSnippets();
      const term = m[2].toLowerCase();
      filtered = snippets.filter(s => s.shortcut.toLowerCase().startsWith(term));
      if (filtered.length > 0) {
        showPopup(popup, filtered);
        active = true;
        selectedIdx = 0;
        highlight(popup, selectedIdx);
        return;
      }
    }
    hidePopup(popup);
    active = false;
  });

  textarea.addEventListener('keydown', e => {
    if (!active) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIdx = (selectedIdx + 1) % filtered.length;
      highlight(popup, selectedIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIdx = (selectedIdx - 1 + filtered.length) % filtered.length;
      highlight(popup, selectedIdx);
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      insertSnippet(textarea, filtered[selectedIdx]);
      hidePopup(popup);
      active = false;
    } else if (e.key === 'Escape') {
      hidePopup(popup);
      active = false;
    }
  });
}

function showPopup(popup, items) {
  popup.innerHTML = items.map((s, i) =>
    `<div class="snippet-item" data-idx="${i}" data-body="${escapeAttr(s.body)}">
       <span class="snippet-shortcut">${s.shortcut}</span>
       <span class="snippet-preview">${escapeHtml(s.body)}</span>
     </div>`
  ).join('');
  popup.style.display = 'block';

  popup.querySelectorAll('.snippet-item').forEach(item => {
    item.addEventListener('click', () => {
      const textarea = document.querySelector('#chatForm textarea[name=body]');
      insertSnippet(textarea, { body: item.dataset.body });
      hidePopup(popup);
    });
  });
}

function hidePopup(popup) { popup.style.display = 'none'; }

function highlight(popup, idx) {
  popup.querySelectorAll('.snippet-item').forEach((el, i) => {
    el.classList.toggle('selected', i === idx);
  });
}

function insertSnippet(textarea, snippet) {
  const val = textarea.value;
  // remove o último /comando digitado e coloca o body
  const newVal = val.replace(/(^|\s)\/[a-z0-9_]*$/i, (match, prefix) => prefix + snippet.body);
  textarea.value = newVal;
  textarea.focus();
  // posiciona cursor no fim
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

/* =========================================================================
   TEMPLATES — clique insere com variáveis renderizadas
   ========================================================================= */
function initTemplateInsertion() {
  const leadId = document.body.dataset.leadId;
  if (!leadId) return;
  const textarea = document.querySelector('#chatForm textarea[name=body]');
  if (!textarea) return;

  document.querySelectorAll('.use-template').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = btn.dataset.templateId;
      try {
        const r = await fetch(`/api/render-template/${tid}/${leadId}`);
        const data = await r.json();
        textarea.value = data.body;
        textarea.focus();
        textarea.dispatchEvent(new Event('input'));
      } catch(e) { console.error(e); }
    });
  });
}

function initFollowupInsertion() {
  const leadId = document.body.dataset.leadId;
  if (!leadId) return;
  const textarea = document.querySelector('#chatForm textarea[name=body]');
  if (!textarea) return;

  document.querySelectorAll('.use-followup').forEach(btn => {
    btn.addEventListener('click', async () => {
      const fid = btn.dataset.followupId;
      try {
        const r = await fetch(`/api/render-followup/${fid}/${leadId}`);
        const data = await r.json();
        // ao usar follow-up, marcamos kind como 'followup'
        const kindField = document.querySelector('#chatForm input[name=kind]');
        if (kindField) kindField.value = 'followup';
        textarea.value = data.body;
        textarea.focus();
        textarea.dispatchEvent(new Event('input'));
      } catch(e) { console.error(e); }
    });
  });

  // qualquer clique no template reseta kind
  document.querySelectorAll('.use-template').forEach(btn => {
    btn.addEventListener('click', () => {
      const kindField = document.querySelector('#chatForm input[name=kind]');
      if (kindField) kindField.value = 'template';
    });
  });
}

/* =========================================================================
   KANBAN — drag and drop
   ========================================================================= */
function initKanbanDragDrop() {
  const cards = document.querySelectorAll('.kanban-card');
  const cols  = document.querySelectorAll('.kanban-col-body');

  cards.forEach(card => {
    card.draggable = true;
    card.addEventListener('dragstart', e => {
      card.classList.add('dragging');
      e.dataTransfer.setData('text/plain', card.dataset.leadId);
    });
    card.addEventListener('dragend', () => card.classList.remove('dragging'));
  });

  cols.forEach(col => {
    col.addEventListener('dragover', e => {
      e.preventDefault();
      col.style.background = 'rgba(0,168,132,.06)';
    });
    col.addEventListener('dragleave', () => col.style.background = '');
    col.addEventListener('drop', async e => {
      e.preventDefault();
      col.style.background = '';
      const leadId = e.dataTransfer.getData('text/plain');
      const newStage = col.dataset.stage;
      const card = document.querySelector(`.kanban-card[data-lead-id="${leadId}"]`);
      if (card) col.appendChild(card);
      // sincroniza com backend
      try {
        await fetch(`/pipeline/move/${leadId}`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({stage: newStage})
        });
        // atualiza contadores
        updateKanbanCounts();
      } catch(err) { console.error(err); }
    });
  });
}

function updateKanbanCounts() {
  document.querySelectorAll('.kanban-col').forEach(col => {
    const count = col.querySelectorAll('.kanban-card').length;
    const badge = col.querySelector('.count');
    if (badge) badge.textContent = count;
  });
}

/* =========================================================================
   SIMULAÇÃO INBOUND — botão de teste no chat
   ========================================================================= */
function toggleSimulator() {
  const sim = document.getElementById('simulatorBox');
  if (sim) sim.style.display = sim.style.display === 'none' ? 'block' : 'none';
}

/* =========================================================================
   UPLOAD DE ANEXOS — Imagem, PDF, áudio, qualquer arquivo
   ========================================================================= */
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btnAttach');
  const fileInput = document.getElementById('fileInput');
  const preview = document.getElementById('attachmentPreview');
  if (!btn || !fileInput || !preview) return;

  btn.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files || []);
    if (!files.length) return;
    const url = fileInput.dataset.uploadUrl;

    for (const file of files) {
      const chip = document.createElement('span');
      chip.className = 'preview-chip uploading';
      chip.innerHTML = `<i class="bi bi-arrow-up-circle"></i> ${escapeHtml(file.name)} <span class="status">enviando…</span>`;
      preview.appendChild(chip);
      preview.style.display = 'flex';

      const fd = new FormData();
      fd.append('file', file);

      try {
        const r = await fetch(url, { method: 'POST', body: fd });
        if (!r.ok) throw new Error('upload falhou');
        chip.classList.remove('uploading'); chip.classList.add('done');
        chip.innerHTML = `<i class="bi bi-check2-circle"></i> ${escapeHtml(file.name)} <span class="status">enviado</span>`;
        // Após 800ms, recarrega a página para mostrar o anexo na timeline
        setTimeout(() => location.reload(), 800);
      } catch(err) {
        console.error(err);
        chip.classList.remove('uploading'); chip.classList.add('error');
        chip.innerHTML = `<i class="bi bi-x-circle"></i> ${escapeHtml(file.name)} <span class="status">erro</span>`;
      }
    }

    fileInput.value = '';
  });
});

/* =========================================================================
   POPUP DE EVENTOS — novo lead + tarefa vencida (polling cada 15s)
   ========================================================================= */
const CRM_EVENTS = {
  lastSince: new Date().toISOString(),
  seenLeads: new Set(),
  seenTasks: new Set(),
  intervalId: null,
};

document.addEventListener('DOMContentLoaded', () => {
  const userId = document.body.dataset.userId;
  if (!userId) return;
  // primeiro fetch após 5s, depois cada 15s
  setTimeout(pollEvents, 5000);
  CRM_EVENTS.intervalId = setInterval(pollEvents, 15000);
});

async function pollEvents() {
  try {
    const r = await fetch(`/api/events?since=${encodeURIComponent(CRM_EVENTS.lastSince)}`);
    if (!r.ok) return;
    const data = await r.json();
    CRM_EVENTS.lastSince = data.now;

    (data.new_leads || []).forEach(lead => {
      if (CRM_EVENTS.seenLeads.has(lead.id)) return;
      CRM_EVENTS.seenLeads.add(lead.id);
      showToast({
        kind: 'lead',
        head: '🆕 NOVO LEAD ATRIBUÍDO',
        title: lead.name,
        sub: `${lead.phone || '—'} · origem: ${lead.source}`,
        url: lead.url,
        btnLabel: 'Atender agora',
      });
      playDing();
    });

    (data.due_tasks || []).forEach(task => {
      if (CRM_EVENTS.seenTasks.has(task.id)) return;
      CRM_EVENTS.seenTasks.add(task.id);
      showToast({
        kind: 'task',
        head: '⏰ TAREFA AGORA',
        title: task.title,
        sub: task.description || `Tipo: ${task.kind}`,
        url: task.url,
        btnLabel: 'Ver',
      });
      playDing();
    });
  } catch(err) { console.error('poll events:', err); }
}

function showToast({ kind, head, title, sub, url, btnLabel }) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `crm-toast ${kind}`;
  toast.innerHTML = `
    <button class="toast-close" onclick="this.parentElement.classList.add('fading'); setTimeout(()=>this.parentElement.remove(), 250)">×</button>
    <div class="toast-head">${head}</div>
    <div class="toast-title">${escapeHtml(title)}</div>
    <div class="toast-sub">${escapeHtml(sub)}</div>
    <div class="toast-actions">
      <a class="toast-btn" href="${url}"><i class="bi bi-arrow-right"></i> ${btnLabel}</a>
    </div>
  `;
  container.appendChild(toast);
  // auto-some em 3s (mas mantém clicável)
  setTimeout(() => {
    if (toast.parentElement) {
      toast.classList.add('fading');
      setTimeout(() => toast.remove(), 250);
    }
  }, 3000);
}

/* =========================================================================
   SOM "DING" via WebAudio (sem precisar de arquivo externo)
   ========================================================================= */
let _audioCtx = null;
function playDing() {
  try {
    if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const ctx = _audioCtx;
    const now = ctx.currentTime;
    // dois tons: 880Hz e depois 1320Hz (notinha de notificação)
    [
      { freq: 880, start: 0,    dur: 0.12 },
      { freq: 1320, start: 0.10, dur: 0.18 },
    ].forEach(t => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = t.freq;
      gain.gain.setValueAtTime(0, now + t.start);
      gain.gain.linearRampToValueAtTime(0.12, now + t.start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + t.start + t.dur);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(now + t.start); osc.stop(now + t.start + t.dur + 0.02);
    });
  } catch(e) { /* navegadores podem bloquear sem user interaction — ok */ }
}

// Destrava o audio context na primeira interação (políticas de autoplay)
document.addEventListener('click', () => {
  if (!_audioCtx) {
    try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch(e) {}
  }
}, { once: true });

/* =========================================================================
   SIDEBAR TOGGLE — compacto / expandido (persiste em localStorage)
   ========================================================================= */
function toggleSidebar() {
  const shell = document.querySelector('.app-shell');
  if (!shell) return;
  shell.classList.toggle('sidebar-compact');
  try {
    localStorage.setItem('crm_sidebar_compact',
      shell.classList.contains('sidebar-compact') ? '1' : '0');
  } catch(e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    if (localStorage.getItem('crm_sidebar_compact') === '1') {
      document.querySelector('.app-shell')?.classList.add('sidebar-compact');
    }
  } catch(e) {}
});

/* =========================================================================
   FILTROS COLAPSÁVEIS em /conversas (seta ^/v)
   ========================================================================= */
function toggleFiltersStrip() {
  const strip = document.getElementById('chatListFilter');
  const arrow = document.getElementById('chatListFilterArrow');
  if (!strip || !arrow) return;
  strip.classList.toggle('collapsed');
  const isCollapsed = strip.classList.contains('collapsed');
  arrow.className = 'bi ' + (isCollapsed ? 'bi-chevron-down' : 'bi-chevron-up');
  try {
    localStorage.setItem('crm_filters_collapsed', isCollapsed ? '1' : '0');
  } catch(e) {}
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    if (localStorage.getItem('crm_filters_collapsed') === '1') {
      const strip = document.getElementById('chatListFilter');
      const arrow = document.getElementById('chatListFilterArrow');
      if (strip) strip.classList.add('collapsed');
      if (arrow) arrow.className = 'bi bi-chevron-down';
    }
  } catch(e) {}
});

/* =========================================================================
   PAINEL LATERAL DIREITO ocultável em /conversas
   ========================================================================= */
function toggleChatSide() {
  const layout = document.querySelector('.chat-layout');
  if (!layout) return;
  layout.classList.toggle('side-hidden');
  const isHidden = layout.classList.contains('side-hidden');
  try {
    localStorage.setItem('crm_side_hidden', isHidden ? '1' : '0');
  } catch(e) {}
  const btn = document.getElementById('btnToggleSide');
  if (btn) {
    btn.querySelector('i').className = 'bi ' + (isHidden ? 'bi-layout-sidebar-inset-reverse' : 'bi-layout-sidebar-reverse');
    btn.title = isHidden ? 'Mostrar painel lateral' : 'Ocultar painel lateral';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  try {
    if (localStorage.getItem('crm_side_hidden') === '1') {
      const layout = document.querySelector('.chat-layout');
      if (layout) {
        layout.classList.add('side-hidden');
        const btn = document.getElementById('btnToggleSide');
        if (btn) btn.querySelector('i').className = 'bi bi-layout-sidebar-inset-reverse';
      }
    }
  } catch(e) {}
});
