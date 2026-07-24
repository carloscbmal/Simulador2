# -*- coding: utf-8 -*-
"""
Visualização animada do "spread das turmas", integrada ao Streamlit (teste5.py).

Reaproveita a simulação de teste5.py/analise_spread.py: acompanha turmas reais
(agrupadas por ano de admissão) e uma turma TEÓRICA (soldados ingressando como
SD 1 no próximo ciclo, disputando as mesmas vagas legais). Os parâmetros de
aposentadoria (tempo de serviço / idade) vêm dos mesmos controles da barra
lateral usados no restante do app, e as matrículas acompanhadas pelo usuário
(até 5) aparecem destacadas ("acesas") no gráfico, mesmo que a turma delas não
esteja na lista padrão de turmas em foco.
"""
import pandas as pd
from dateutil.relativedelta import relativedelta
import streamlit.components.v1 as components

from teste5 import HIERARQUIA, TEMPO_MINIMO, POSTOS_COM_EXCEDENTE, VAGAS_QOA, VAGAS_QOMT, VAGAS_QOM, get_anos
import analise_spread as asp

NIVEL = {p: i for i, p in enumerate(HIERARQUIA)}
ANOS_FOCO_PADRAO = [1994, 2002, 2006, 2010, 2018, 2023]
N_TEORICA = 100


def _proximo_ciclo(data):
    """Primeira data de ciclo (26/06 ou 29/11) >= data."""
    for delta_ano in range(0, 3):
        ano = data.year + delta_ano
        for mes, dia in [(6, 26), (11, 29)]:
            d = pd.Timestamp(year=ano, month=mes, day=dia)
            if d >= data:
                return d
    return pd.Timestamp(year=data.year + 3, month=11, day=29)


def _montar_turma_teorica(entrada, n, nasc):
    df = pd.DataFrame([{
        'Matricula': 9_000_001 + i,
        'Pos_Hierarquica': pd.NA,
        'Posto_Graduacao': HIERARQUIA[0],
        'Data_Admissao': entrada,
        'Data_Nascimento': nasc,
        'Ultima_promocao': entrada,
        'Excedente': '',
    } for i in range(n)])
    df.index = range(2_000_000, 2_000_000 + n)
    return df


def _simular(df_input, vagas_base, vagas_extras_dict, df_teorica, entrada_teorica,
             data_alvo, tempo_apo, idade_apo):
    """Fiel a executar_simulacao_quadro (sem Gerador Quântico), injetando a turma teórica."""
    df = df_input.copy()
    data_atual = pd.Timestamp.today().normalize()

    datas_ciclo = []
    for ano in range(data_atual.year, data_alvo.year + 1):
        for mes, dia in [(6, 26), (11, 29)]:
            d = pd.Timestamp(year=ano, month=mes, day=dia)
            if data_atual <= d <= data_alvo:
                datas_ciclo.append(d)
    datas_ciclo.sort()

    injetado = False
    snapshots = {}
    for data_ref in datas_ciclo:
        if not injetado and data_ref >= entrada_teorica:
            df = pd.concat([df, df_teorica])
            injetado = True

        extras = (vagas_extras_dict or {}).get(data_ref, {})

        # --- A) PROMOÇÕES ---
        for i in range(len(HIERARQUIA) - 1):
            posto_atual, proximo = HIERARQUIA[i], HIERARQUIA[i + 1]
            candidatos = df[df['Posto_Graduacao'] == posto_atual].sort_values('Pos_Hierarquica')
            limite = vagas_base.get(proximo, 9999) + extras.get(proximo, 0)
            ocupados = len(df[(df['Posto_Graduacao'] == proximo) & (df['Excedente'] != "x")])
            vagas = max(0, limite - ocupados)
            for idx, mil in candidatos.iterrows():
                anos_posto = relativedelta(data_ref, mil['Ultima_promocao']).years
                if anos_posto >= TEMPO_MINIMO.get(posto_atual, 99) and vagas > 0:
                    df.at[idx, 'Posto_Graduacao'] = proximo
                    df.at[idx, 'Ultima_promocao'] = data_ref
                    df.at[idx, 'Excedente'] = ""
                    vagas -= 1
                elif posto_atual in POSTOS_COM_EXCEDENTE and anos_posto >= 6:
                    df.at[idx, 'Posto_Graduacao'] = proximo
                    df.at[idx, 'Ultima_promocao'] = data_ref
                    df.at[idx, 'Excedente'] = "x"

        # --- B) ABSORÇÃO ---
        for posto in HIERARQUIA:
            limite = vagas_base.get(posto, 9999) + extras.get(posto, 0)
            abertas = limite - len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
            if abertas > 0:
                exc = df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] == "x")].sort_values('Pos_Hierarquica')
                for idx_exc in exc.head(int(abertas)).index:
                    df.at[idx_exc, 'Excedente'] = ""

        # --- C) APOSENTADORIA ---
        idade = pd.to_numeric(df['Data_Nascimento'].apply(lambda x: get_anos(data_ref, x)))
        servico = pd.to_numeric(df['Data_Admissao'].apply(lambda x: get_anos(data_ref, x)))
        mask_apo = (idade >= idade_apo) | (servico >= tempo_apo)
        if mask_apo.any():
            df = df[~mask_apo].copy()

        snapshots[data_ref] = dict(zip(df['Matricula'], df['Posto_Graduacao']))

    return snapshots, datas_ciclo


def montar_dados_spread(tipo_simulacao, df_ativo, df_condutores, df_musicos,
                         tempo_apo, idade_apo, matriculas_destaque, anos_foco=None):
    """Monta o dicionário DATA (pronto para JSON) consumido pela animação."""
    anos_foco = list(anos_foco or ANOS_FOCO_PADRAO)

    # Garante que a turma (ano de admissão) de cada matrícula em destaque apareça
    # no gráfico, mesmo que não esteja entre as turmas curadas por padrão.
    if matriculas_destaque:
        admissoes = df_ativo.set_index('Matricula')['Data_Admissao']
        for mat in matriculas_destaque:
            if mat in admissoes.index and pd.notna(admissoes[mat]):
                anos_foco.append(int(pd.Timestamp(admissoes[mat]).year))
    anos_foco = sorted(set(anos_foco))

    mapa, info = asp.montar_turmas_foco(df_ativo, anos_foco)
    letra_teorica = asp.letra(len(anos_foco))

    hoje = pd.Timestamp.today().normalize()
    entrada_teorica = _proximo_ciclo(hoje + pd.DateOffset(years=2))
    nasc_teorica = entrada_teorica - pd.DateOffset(years=25)
    horizonte_anos = int(max(tempo_apo, idade_apo - 25)) + 3
    data_alvo = entrada_teorica + pd.DateOffset(years=horizonte_anos)

    df_teorica = _montar_turma_teorica(entrada_teorica, N_TEORICA, nasc_teorica)
    for i in range(N_TEORICA):
        mapa[9_000_001 + i] = {'letra': letra_teorica, 'antig': i + 1}
    info.append({'letra': letra_teorica, 'rotulo': str(entrada_teorica.year), 'n': N_TEORICA})

    if tipo_simulacao == "QOA/QPC (Administrativo)":
        vagas_base = VAGAS_QOA
        vagas_extras = asp.vagas_migradas_qoa(df_condutores, df_musicos, data_alvo, tempo_apo, idade_apo)
    elif "Condutores" in tipo_simulacao:
        vagas_base, vagas_extras = VAGAS_QOMT, None
    else:
        vagas_base, vagas_extras = VAGAS_QOM, None

    snapshots, datas_ciclo = _simular(df_ativo, vagas_base, vagas_extras, df_teorica,
                                       entrada_teorica, data_alvo, tempo_apo, idade_apo)

    snap_inicial = dict(zip(df_ativo['Matricula'], df_ativo['Posto_Graduacao']))
    colunas = [('Atual', None, snap_inicial)] + \
              [(d.strftime('%d/%m/%Y'), d, snapshots[d]) for d in datas_ciclo]

    destaque_set = set(int(m) for m in (matriculas_destaque or []))
    membros = []
    for mat, m in mapa.items():
        ranks = []
        for _, d, snap in colunas:
            if m['letra'] == letra_teorica and (d is None or d < entrada_teorica):
                ranks.append(-2)
            elif mat in snap:
                ranks.append(NIVEL[snap[mat]])
            else:
                ranks.append(-1)
        membros.append({'mat': int(mat), 'turma': m['letra'], 'antig': int(m['antig']),
                         'ranks': ranks, 'destaque': int(mat) in destaque_set})
    membros.sort(key=lambda x: (x['turma'], x['antig']))

    encontrados = {m['mat'] for m in membros}
    nao_encontrados = sorted(destaque_set - encontrados)

    return {
        'hierarquia': HIERARQUIA,
        'ciclos': [c[0] for c in colunas],
        'turmas': [{'letra': t['letra'], 'rotulo': t['rotulo'], 'n': t['n'],
                    'teorica': t['letra'] == letra_teorica} for t in info],
        'membros': membros,
        'tempo_apo': int(tempo_apo),
        'idade_apo': int(idade_apo),
        'n_teorica': N_TEORICA,
        'entrada_teorica': entrada_teorica.strftime('%d/%m/%Y'),
        'nao_encontrados': nao_encontrados,
    }


_HTML_TEMPLATE = r"""
<div class="viz-root" id="viz-root">
<style>
  #viz-root {
    --surface-1: #fcfcfb; --page: #f9f9f7;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    #viz-root {
      --surface-1: #1a1a19; --page: #0d0d0d;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --grid: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      color-scheme: dark;
    }
  }
  html, body { margin: 0; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--page); }
  #viz-root { padding: 4px 2px 20px; color: var(--text-primary); background: var(--page); }
  h1 { font-size: 1.05rem; margin: 0 0 2px; }
  .sub { color: var(--text-secondary); font-size: .82rem; margin: 0 0 12px; line-height: 1.4; }
  .legend { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: .82rem; }
  .legend .chip { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); }
  .legend .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: .84rem; }
  .controls button {
    font: inherit; color: var(--text-primary); background: var(--surface-1);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 14px; cursor: pointer;
  }
  .controls button:hover { border-color: var(--baseline); }
  .controls select {
    font: inherit; color: var(--text-primary); background: var(--surface-1);
    border: 1px solid var(--border); border-radius: 8px; padding: 5px 8px;
  }
  .controls input[type=range] { flex: 1; min-width: 140px; }
  .when { font-variant-numeric: tabular-nums; color: var(--text-secondary); min-width: 130px; }
  .when b { color: var(--text-primary); font-size: 1.02rem; }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 8px; position: relative; }
  canvas { display: block; width: 100%; }
  .tip {
    position: absolute; pointer-events: none; display: none;
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 9px; font-size: .78rem;
    color: var(--text-primary); box-shadow: 0 2px 8px rgba(0,0,0,.12);
    white-space: nowrap; z-index: 5;
  }
  .tip .muted { color: var(--text-muted); }
  .foot { color: var(--text-muted); font-size: .76rem; margin-top: 10px; }
</style>

<h1>Spread das turmas — a marcha na carreira</h1>
<p class="sub" id="sub"></p>
<div class="legend" id="legend"></div>
<div class="controls">
  <button id="play">&#9654; Reproduzir</button>
  <button id="restart">&#8635; Início</button>
  <select id="speed">
    <option value="0.5">0,5&times;</option>
    <option value="1" selected>1&times;</option>
    <option value="2">2&times;</option>
    <option value="4">4&times;</option>
  </select>
  <input type="range" id="scrub" min="0" max="1000" value="0" step="1">
  <span class="when" id="when"></span>
</div>
<div class="card">
  <canvas id="cv"></canvas>
  <div class="tip" id="tip"></div>
</div>
<div class="foot" id="foot"></div>
</div>

<script>
const DATA = __DATA_JSON__;

const H = DATA.hierarquia;
const C = DATA.ciclos.length;
const members = DATA.membros;
const N = members.length;
const TURMAS = DATA.turmas.map(t => t.letra);
const ROTULO = Object.fromEntries(DATA.turmas.map(t => [t.letra, t.rotulo]));
const TEORICA_LETRA = (DATA.turmas.find(t => t.teorica) || {}).letra;
const destaqueAtivos = members.filter(m => m.destaque);

// Paleta categórica validada (color-formula.md): ordem fixa, ciclada se houver
// mais turmas do que cores (caso raro: matrículas em destaque de anos incomuns).
const PALETTE_LIGHT = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
const PALETTE_DARK  = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
const GLOW = { light: '#e0a000', dark: '#ffd60a' };

// Codificação de ranks: >=0 posto · -1 reserva · -2 ainda não ingressou (turma teórica)
const usados = new Set();
members.forEach(m => m.ranks.forEach(r => { if (r >= 0) usados.add(r); }));
const RANKS = [...usados].sort((a, b) => a - b);
const laneOf = new Map(RANKS.map((r, i) => [r, i]));

members.forEach(m => {
  m.retire = m.ranks.indexOf(-1);
  if (m.retire < 0) m.retire = Infinity;
});
const ordemReserva = members.map((m, i) => i)
  .sort((a, b) => (members[a].retire - members[b].retire) ||
                  members[a].turma.localeCompare(members[b].turma) ||
                  (members[a].antig - members[b].antig));
const slotReserva = new Array(N);
ordemReserva.forEach((mi, slot) => slotReserva[mi] = slot);

// ---------- cores / tema ----------
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
let TH = {};
function isDark() { return matchMedia('(prefers-color-scheme: dark)').matches; }
function readTheme() {
  const dark = isDark();
  const s = getComputedStyle(document.getElementById('viz-root'));
  TH = {
    surface: s.getPropertyValue('--surface-1').trim(),
    grid: s.getPropertyValue('--grid').trim(),
    baseline: s.getPropertyValue('--baseline').trim(),
    txt: s.getPropertyValue('--text-primary').trim(),
    txt2: s.getPropertyValue('--text-secondary').trim(),
    muted: s.getPropertyValue('--text-muted').trim(),
    glow: dark ? GLOW.dark : GLOW.light,
  };
  const pal = dark ? PALETTE_DARK : PALETTE_LIGHT;
  TURMAS.forEach((L, i) => { TH[L] = pal[i % pal.length]; });
  buildLegend();
  buildSub();
}
function buildSub() {
  const el = document.getElementById('sub');
  let txt = 'Cada ponto é um militar. As turmas caminham juntas e se separam quando parte é promovida ' +
    'antes; ao aposentar, o ponto segue para a Reserva. A turma teórica (' + TEORICA_LETRA + ') simula ' +
    DATA.n_teorica + ' soldados ingressando como SD 1 no ciclo ' + DATA.entrada_teorica +
    ', disputando as mesmas vagas legais. Aposentadoria: <b>' + DATA.tempo_apo + ' anos de serviço</b> / ' +
    '<b>' + DATA.idade_apo + ' anos de idade</b> (parâmetros escolhidos na barra lateral).';
  if (destaqueAtivos.length) {
    txt += ' &#128161; ' + destaqueAtivos.length + ' matrícula(s) acompanhada(s) acesas em dourado no gráfico.';
  }
  el.innerHTML = txt;
}
function buildLegend() {
  const el = document.getElementById('legend');
  const chips = DATA.turmas.map(t => {
    const rotulo = 'Turma ' + t.letra + ' &middot; ingresso ' + t.rotulo + ' (' + t.n + (t.teorica ? ', teórica' : '') + ')';
    return '<span class="chip"><span class="dot" style="background:' + TH[t.letra] + '"></span>' + rotulo + '</span>';
  });
  chips.push('<span class="chip"><span class="dot" style="background:' + TH.baseline + '"></span>Reserva (inativos)</span>');
  if (destaqueAtivos.length) {
    chips.push('<span class="chip"><span class="dot" style="background:' + TH.glow + '"></span>&#128161; Matrícula em destaque</span>');
  }
  el.innerHTML = chips.join('');
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readTheme(); });
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------- layout ----------
let W = 0, HT = 0, dpr = 1;
let G = {};
const R = 4.5;

function layout() {
  const rect = cv.parentElement.getBoundingClientRect();
  W = Math.max(760, rect.width - 16);
  HT = Math.min(760, Math.max(480, RANKS.length * 62 + 60));
  dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr; cv.height = HT * dpr;
  cv.style.height = HT + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const gutter = 84, reservaW = 118, top = 34, bottom = 12, gap = 14;
  const plotW = W - gutter - reservaW - gap - 10;
  const colW = (plotW - gap * (TURMAS.length - 1)) / TURMAS.length;
  const cols = {};
  TURMAS.forEach((L, i) => {
    const x0 = gutter + i * (colW + gap);
    cols[L] = { x0, x1: x0 + colW };
  });
  G = { gutter, top, bottom, reservaW, cols, laneH: (HT - top - bottom) / RANKS.length,
        res: { x0: W - reservaW - 4, x1: W - 4 } };
  computeAllTargets();
}

function laneY(lane) { return G.top + (RANKS.length - 1 - lane) * G.laneH; }

function packer(x0, x1, yc, hAvail, n) {
  if (n === 0) return () => [0, 0];
  const wAvail = (x1 - x0) - 16;
  let sp = 13;
  let rows = Math.max(1, Math.floor(hAvail / sp));
  let cols = Math.ceil(n / rows);
  if (cols * sp > wAvail) {
    sp = Math.max(9.5, wAvail / cols);
    rows = Math.max(1, Math.floor(hAvail / sp));
    cols = Math.ceil(n / rows);
    sp = Math.min(13, wAvail / cols, hAvail / rows);
  }
  rows = Math.ceil(n / cols);
  const gw = cols * sp, gh = rows * sp;
  const gx = (x0 + x1) / 2 - gw / 2 + sp / 2;
  const gy = yc - gh / 2 + sp / 2;
  return i => [gx + (i % cols) * sp, gy + Math.floor(i / cols) * sp];
}

let targets = [];
function computeAllTargets() {
  targets = [];
  for (let c = 0; c < C; c++) {
    const pos = new Float32Array(N * 2);
    const groups = new Map();
    for (let i = 0; i < N; i++) {
      const r = members[i].ranks[c];
      if (r < 0) continue;
      const k = members[i].turma + laneOf.get(r);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(i);
    }
    for (const [k, list] of groups) {
      list.sort((a, b) => members[a].antig - members[b].antig);
      const turma = k[0], lane = +k.slice(1);
      const col = G.cols[turma];
      const yc = laneY(lane) + G.laneH / 2;
      const put = packer(col.x0, col.x1, yc, G.laneH - 10, list.length);
      list.forEach((mi, s) => { const [x, y] = put(s); pos[mi*2] = x; pos[mi*2+1] = y; });
    }
    const nRes = members.reduce((acc, m) => acc + (m.ranks[c] === -1 ? 1 : 0), 0);
    if (nRes > 0) {
      const putR = packer(G.res.x0, G.res.x1, G.top + (HT - G.top - G.bottom) / 2,
                          HT - G.top - G.bottom - 20, nRes);
      let sSeq = 0;
      for (const mi of ordemReserva) {
        if (members[mi].ranks[c] === -1) {
          const [x, y] = putR(sSeq++);
          pos[mi*2] = x; pos[mi*2+1] = y;
        }
      }
    }
    for (let i = 0; i < N; i++) {
      if (members[i].ranks[c] === -2) { pos[i*2] = NaN; pos[i*2+1] = NaN; }
    }
    targets.push(pos);
  }
}

// ---------- animação ----------
let tau = 0;
let playing = false;
let speed = 1;
const CYCLE_MS = 950;
let lastTs = null;
const phase = members.map(() => Math.random() * Math.PI * 2);
const curPos = new Float32Array(N * 2);
const drawInfo = new Array(N);

const ease = f => f < .5 ? 2*f*f : 1 - Math.pow(-2*f + 2, 2) / 2;

function frame(ts) {
  if (playing) {
    if (lastTs != null) {
      tau += (ts - lastTs) / CYCLE_MS * speed;
      if (tau >= C - 1) { tau = C - 1; setPlaying(false); }
    }
    lastTs = ts;
  } else lastTs = ts;
  draw(ts);
  requestAnimationFrame(frame);
}

function drawDot(i, ts) {
  const m = members[i];
  const info = drawInfo[i];
  if (!info || !isFinite(info.x)) return;
  const { x, y, alpha, promovendo } = info;
  const cor = TH[m.turma];

  if (m.destaque) {                                     // "luz" pulsante atrás do ponto
    const pulse = 0.55 + 0.45 * Math.sin(ts / 260 + phase[i]);
    const gr = R + 7 + pulse * 3;
    const grad = ctx.createRadialGradient(x, y, R * 0.6, x, y, gr + 8);
    grad.addColorStop(0, `rgba(255,214,10,${0.55 * alpha})`);
    grad.addColorStop(1, 'rgba(255,214,10,0)');
    ctx.beginPath(); ctx.arc(x, y, gr + 8, 0, Math.PI * 2);
    ctx.fillStyle = grad; ctx.fill();
  }

  ctx.globalAlpha = alpha;
  ctx.beginPath(); ctx.arc(x, y, R, 0, Math.PI * 2);
  ctx.fillStyle = cor; ctx.fill();
  ctx.lineWidth = 2; ctx.strokeStyle = TH.surface; ctx.stroke();
  if (promovendo) {
    ctx.beginPath(); ctx.arc(x, y, R + 3, 0, Math.PI * 2);
    ctx.strokeStyle = cor; ctx.globalAlpha = alpha * (1 - promovendo); ctx.stroke();
  }
  ctx.globalAlpha = 1;

  if (m.destaque) {
    ctx.beginPath(); ctx.arc(x, y, R + 3.5, 0, Math.PI * 2);
    ctx.lineWidth = 2; ctx.strokeStyle = TH.glow; ctx.globalAlpha = alpha; ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.font = '700 10px system-ui, sans-serif';
    ctx.textAlign = 'center'; ctx.lineWidth = 3; ctx.strokeStyle = TH.surface;
    ctx.strokeText(String(m.mat), x, y - R - 8);
    ctx.fillStyle = TH.txt;
    ctx.fillText(String(m.mat), x, y - R - 8);
  }
}

function draw(ts) {
  ctx.clearRect(0, 0, W, HT);
  ctx.fillStyle = TH.surface;
  ctx.fillRect(0, 0, W, HT);

  const c0 = Math.min(C - 2, Math.floor(tau));
  const f = Math.min(1, tau - c0);
  const e = ease(Math.min(1, f / 0.55));
  const t0 = targets[c0], t1 = targets[Math.min(C - 1, c0 + 1)];

  ctx.strokeStyle = TH.grid; ctx.lineWidth = 1;
  ctx.font = '11px system-ui, sans-serif';
  for (let l = 0; l <= RANKS.length; l++) {
    const y = G.top + l * G.laneH;
    ctx.beginPath(); ctx.moveTo(G.gutter - 6, y); ctx.lineTo(G.res.x0 - 8, y); ctx.stroke();
  }
  ctx.fillStyle = TH.muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  RANKS.forEach((r, l) => ctx.fillText(H[r], G.gutter - 12, laneY(l) + G.laneH / 2));

  ctx.strokeStyle = TH.baseline;
  ctx.beginPath(); ctx.moveTo(G.res.x0 - 8, G.top - 20); ctx.lineTo(G.res.x0 - 8, HT - G.bottom); ctx.stroke();
  ctx.textAlign = 'center'; ctx.font = '600 12px system-ui, sans-serif';
  ctx.fillStyle = TH.txt2;
  for (const L of TURMAS) {
    const rot = L === TEORICA_LETRA ? `${ROTULO[L]} (teórica)` : ROTULO[L];
    ctx.fillText(`Turma ${L} · ${rot}`, (G.cols[L].x0 + G.cols[L].x1) / 2, G.top - 16);
  }
  ctx.fillText('Reserva', (G.res.x0 + G.res.x1) / 2, G.top - 16);

  const cShow = Math.round(tau);
  ctx.font = '10px system-ui, sans-serif';
  ctx.lineWidth = 3; ctx.strokeStyle = TH.surface;
  for (const turma of TURMAS) {
    const col = G.cols[turma];
    const cont = new Map();
    for (const m of members) {
      if (m.turma !== turma) continue;
      const r = m.ranks[cShow];
      if (r >= 0) cont.set(r, (cont.get(r) || 0) + 1);
    }
    ctx.textAlign = 'right'; ctx.fillStyle = TH.muted;
    for (const [r, n] of cont) {
      const y = laneY(laneOf.get(r)) + 13;
      ctx.strokeText(n, col.x1 - 4, y);
      ctx.fillText(n, col.x1 - 4, y);
    }
  }
  const nRes = members.reduce((a, m) => a + (m.ranks[cShow] === -1 ? 1 : 0), 0);
  if (nRes) { ctx.textAlign = 'center'; ctx.fillText(nRes + ' na reserva', (G.res.x0 + G.res.x1) / 2, HT - G.bottom - 2); }

  const bobT = ts / 480;
  for (let i = 0; i < N; i++) {
    const m = members[i];
    const r0 = m.ranks[c0], r1 = m.ranks[Math.min(C - 1, c0 + 1)];
    if (r0 === -2 && r1 === -2) { curPos[i*2] = NaN; curPos[i*2+1] = NaN; drawInfo[i] = null; continue; }
    let x, y, alpha = 1;
    if (r0 === -2) { x = t1[i*2]; y = t1[i*2+1]; alpha = e; }
    else {
      x = t0[i*2] + (t1[i*2] - t0[i*2]) * e;
      y = t0[i*2+1] + (t1[i*2+1] - t0[i*2+1]) * e;
      if (r0 === -1 && r1 === -1) alpha = 0.28;
      else if (r1 === -1) alpha = 1 - 0.72 * e;
    }
    const ativo = (f < .5 ? r0 : r1) >= 0;
    if (!reduceMotion && ativo && playing) {
      x += Math.sin(bobT * 2 + phase[i]) * 0.8;
      y += Math.sin(bobT * 3.1 + phase[i]) * 1.1;
    }
    curPos[i*2] = x; curPos[i*2+1] = y;
    const promovendo = r0 >= 0 && r1 >= 0 && r1 > r0 && f < 0.6 ? (f / 0.6) : 0;
    drawInfo[i] = { x, y, alpha, promovendo };
  }
  for (let i = 0; i < N; i++) if (!members[i].destaque) drawDot(i, ts);
  for (let i = 0; i < N; i++) if (members[i].destaque) drawDot(i, ts);

  const lab = DATA.ciclos[cShow];
  document.getElementById('when').innerHTML =
    lab === 'Atual' ? '<b>Hoje</b>' : `<b>${lab.slice(6)}</b> · ciclo ${lab.slice(0, 5)}`;
  if (!scrubbing) scrub.value = Math.round(tau / (C - 1) * 1000);
  const partes = TURMAS.map(L =>
    `Turma ${L}: ${members.filter(m => m.turma === L && m.ranks[cShow] >= 0).length}`);
  let footTxt = `Ativos — ${partes.join(' · ')} · Reserva: ${nRes}.`;
  if (destaqueAtivos.length) {
    const emAcompanhamento = destaqueAtivos.filter(m => m.ranks[cShow] >= 0).length;
    footTxt += ` &#128161; Em destaque: ${emAcompanhamento} ativo(s), ${destaqueAtivos.length - emAcompanhamento} na reserva.`;
  }
  document.getElementById('foot').innerHTML = footTxt;
}

// ---------- controles ----------
const playBtn = document.getElementById('play');
const scrub = document.getElementById('scrub');
let scrubbing = false;

function setPlaying(p) {
  playing = p;
  playBtn.innerHTML = p ? '&#9208; Pausar' : '&#9654; Reproduzir';
}
playBtn.onclick = () => {
  if (!playing && tau >= C - 1) tau = 0;
  setPlaying(!playing);
};
document.getElementById('restart').onclick = () => { tau = 0; setPlaying(true); };
document.getElementById('speed').onchange = e => speed = +e.target.value;
scrub.oninput = () => { scrubbing = true; tau = scrub.value / 1000 * (C - 1); };
scrub.onchange = () => scrubbing = false;

// ---------- tooltip ----------
const tip = document.getElementById('tip');
cv.addEventListener('mousemove', ev => {
  const rc = cv.getBoundingClientRect();
  const mx = ev.clientX - rc.left, my = ev.clientY - rc.top;
  let best = -1, bd = 144;
  for (let i = 0; i < N; i++) {
    if (!isFinite(curPos[i*2])) continue;
    const dx = curPos[i*2] - mx, dy = curPos[i*2+1] - my, d = dx*dx + dy*dy;
    if (d < bd) { bd = d; best = i; }
  }
  if (best < 0) { tip.style.display = 'none'; return; }
  const m = members[best], cShow = Math.round(tau), r = m.ranks[cShow];
  tip.innerHTML = `<b>${m.turma}${m.antig}</b> · matrícula ${m.mat}${m.destaque ? ' &#128161;' : ''}<br>` +
    `<span class="muted">${r >= 0 ? H[r] : 'Reserva (inativo)'}` +
    ` · turma ${ROTULO[m.turma]}</span>`;
  tip.style.display = 'block';
  tip.style.left = Math.min(mx + 14, W - 190) + 'px';
  tip.style.top = (my + 14) + 'px';
});
cv.addEventListener('mouseleave', () => tip.style.display = 'none');

// ---------- boot ----------
readTheme();
layout();
window.addEventListener('resize', layout);
requestAnimationFrame(frame);
</script>
"""


def render(dados, height=980):
    """Renderiza a animação no Streamlit a partir do dicionário de montar_dados_spread()."""
    import json
    html = _HTML_TEMPLATE.replace('__DATA_JSON__', json.dumps(dados, ensure_ascii=False))
    components.html(html, height=height, scrolling=True)
