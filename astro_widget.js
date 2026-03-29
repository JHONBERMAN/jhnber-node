/**
 * jhonber.com 천체 점성술 위젯 — index.html 구조 대응 버전
 * desktop_app.py 가 Gist 에 올린 data.json 을 읽어 각 섹션을 동적으로 갱신합니다.
 * 타겟 IDs: ovSignals, planetGrid, moonPhaseInfo, moonPhaseName/Icon/Desc, astroCounters
 */
(function () {
  'use strict';

  /* ── GitHub Gist raw URL ── */
  const DATA_URL = 'https://gist.githubusercontent.com/JHONBERMAN/fee5f407cb28e180a9e692a12055d987/raw/data.json';

  /* ── 행성 한글·심볼 ── */
  const PKR  = { Sun:'태양',Moon:'달',Mercury:'수성',Venus:'금성',Mars:'화성',
                 Jupiter:'목성',Saturn:'토성',Uranus:'천왕성',Neptune:'해왕성',
                 Pluto:'명왕성','True Node':'노스노드' };
  const PSYM = { Sun:'☉',Moon:'☽',Mercury:'☿',Venus:'♀',Mars:'♂',
                 Jupiter:'♃',Saturn:'♄',Uranus:'♅',Neptune:'♆',
                 Pluto:'♇','True Node':'☊' };

  /* ── 시그널 강도 ── */
  function stars(orb){
    if(orb<=1) return '<span style="color:#f59e0b;font-size:11px">★★★ EXACT</span>';
    if(orb<=3) return '<span style="color:#f59e0b;font-size:11px">★★☆</span>';
    return '<span style="color:#c8a96e;font-size:11px">★☆☆</span>';
  }

  /* ── 달 위상 ── */
  function moonPhase(sunLon, moonLon){
    let d = moonLon - sunLon; if(d<0) d+=360;
    if(d<22.5)  return {icon:'🌑', name:'신월(New Moon)',        desc:'새 사이클 시작, 씨앗 에너지'};
    if(d<67.5)  return {icon:'🌒', name:'초승달',                desc:'성장·시작의 에너지'};
    if(d<112.5) return {icon:'🌓', name:'상현(First Quarter)',   desc:'결단·행동 요구 구간'};
    if(d<157.5) return {icon:'🌔', name:'차오르는 달',           desc:'모멘텀 축적 구간'};
    if(d<202.5) return {icon:'🌕', name:'보름달(Full Moon)',     desc:'에너지 절정·변곡 가능'};
    if(d<247.5) return {icon:'🌖', name:'기우는 달',             desc:'수확·정리 구간'};
    if(d<292.5) return {icon:'🌗', name:'하현(Last Quarter)',    desc:'전환·방출 구간'};
    if(d<337.5) return {icon:'🌘', name:'그믐달',                desc:'휴식·정화 구간'};
    return      {icon:'🌑', name:'신월(New Moon)',               desc:'새 사이클 시작'};
  }

  /* ═══════════════════════════════════════════════
     1. X-SIGNAL 카드 업데이트 (ovSignals)
     구조: .signal-row > .signal-dot.bull/bear/neutral + .signal-text + .signal-score.up/down
  ═══════════════════════════════════════════════ */
  function updateXSignal(data){
    const el = document.getElementById('ovSignals');
    if(!el) return;

    const aspects = (data.key_reversal_aspects||[]).slice(0,4);
    const alerts  = data.market_alerts||[];
    const g       = data.crd_gauge||{};
    const score   = g.score||0;

    const sigRows = aspects.map(a=>{
      const orb = a.orb_exactness||0;
      const asp = a.aspect||'';
      /* bull/bear/neutral 분류 */
      let dotCls = 'neutral';
      if(asp.includes('Square')||asp.includes('Opposition')||asp.includes('Contra')) dotCls = 'bear';
      else if(asp.includes('Conjunction')||asp.includes('Parallel')||asp.includes('Trine')) dotCls = 'bull';

      const scoreText = dotCls==='bear'?'-주의':dotCls==='bull'?'+강세':'중립';
      const scoreCls  = dotCls==='bear'?'down':dotCls==='bull'?'up':'';
      const scoreStyle= dotCls==='neutral'?'style="color:var(--gold)"':'';

      const pts = (a.planets||'').split(' & ').map(p=>{
        const n=p.trim();
        return (PKR[n]||n)+(PSYM[n]?'('+PSYM[n]+')':'');
      }).join(' & ');

      return `<div class="signal-row">
        <div class="signal-dot ${dotCls}"></div>
        <div class="signal-text">${pts} — ${asp} · 오차 ${orb.toFixed(2)}° ${stars(orb)}</div>
        <div class="signal-score ${scoreCls}" ${scoreStyle}>${scoreText}</div>
      </div>`;
    }).join('');

    const alertRows = alerts.slice(0,2).map(a=>`
      <div class="signal-row">
        <div class="signal-dot bear"></div>
        <div class="signal-text">⚠ ${a.type||''} — ${(a.message||'').substring(0,55)}</div>
        <div class="signal-score down">-주의</div>
      </div>`).join('');

    el.innerHTML = sigRows + alertRows +
      `<div style="font-size:10px;color:var(--text2);margin-top:8px;letter-spacing:1px">` +
      `${data.timestamp_ny||'--'} · Swiss Ephemeris · CRD ${score}/100</div>`;
  }

  /* ═══════════════════════════════════════════════
     2. 행성 그리드 업데이트 (planetGrid)
     구조: .planet-card > .planet-symbol + .planet-name + .planet-sign + .planet-deg
  ═══════════════════════════════════════════════ */
  function updatePlanetGrid(data){
    const planets = data.planets_status||{};

    /* 달 위상 — moonPhaseInfo (천체 탭 행성 그리드 하단) */
    const sun  = planets.Sun||{};
    const moon = planets.Moon||{};
    const phase = moonPhase(sun.longitude||0, moon.longitude||0);

    const phaseInfoEl = document.getElementById('moonPhaseInfo');
    if(phaseInfoEl){
      phaseInfoEl.style.display = 'flex';
      phaseInfoEl.style.alignItems = 'center';
      phaseInfoEl.style.gap = '10px';
      phaseInfoEl.style.textAlign = 'left';
      phaseInfoEl.innerHTML =
        `<span style="font-size:24px">${phase.icon}</span>` +
        `<div><div style="font-size:13px;color:var(--text);font-weight:600">${phase.name}</div>` +
        `<div style="font-size:12px;color:var(--text2)">${phase.desc}</div></div>` +
        `<div style="margin-left:auto;font-size:11px;color:var(--text2)">` +
        `☉ ${(sun.longitude||0).toFixed(2)}°&nbsp;&nbsp;☽ ${(moon.longitude||0).toFixed(2)}°</div>`;
    }

    /* 달 위상 — celestial 탭 (moonPhaseIcon / moonPhaseName / moonPhaseDesc) */
    const piEl = document.getElementById('moonPhaseIcon');
    if(piEl) piEl.textContent = phase.icon;
    const pnEl = document.getElementById('moonPhaseName');
    if(pnEl) pnEl.textContent = phase.name;
    const pdEl = document.getElementById('moonPhaseDesc');
    if(pdEl) pdEl.textContent = phase.desc;

    /* 행성 카드 그리드 */
    const el = document.getElementById('planetGrid');
    if(!el) return;

    el.innerHTML = Object.entries(planets).map(([name,info])=>{
      const sym    = PSYM[name]||'';
      const kr     = PKR[name]||name;
      const retro  = info.is_retrograde;
      const station= info.is_stationing;
      const badge  = retro
        ? '<span style="color:var(--red);font-size:10px;margin-left:3px">℞역행</span>'
        : station
        ? '<span style="color:var(--gold);font-size:10px;margin-left:3px">정지</span>'
        : '';
      const hlStyle = (retro||station)?'border-color:rgba(200,169,110,.5);':'';
      const signInfo = `${info.current_sign||'--'} ${(info.sign_degree||0).toFixed(1)}°`;
      const degInfo  = `총 ${(info.longitude||0).toFixed(2)}°`;
      return `<div class="planet-card" style="${hlStyle}">
        <div class="planet-symbol">${sym}</div>
        <div class="planet-name">${kr}${badge}</div>
        <div class="planet-sign">${signInfo}</div>
        <div class="planet-deg">${degInfo}</div>
      </div>`;
    }).join('');
  }

  /* ═══════════════════════════════════════════════
     오류 표시
  ═══════════════════════════════════════════════ */
  function showError(msg){
    const el = document.getElementById('ovSignals');
    if(el) el.innerHTML =
      `<div class="signal-row"><div class="signal-dot neutral"></div>` +
      `<div class="signal-text" style="color:var(--text2)">⚠ ${msg}</div></div>`;
  }

  /* ═══════════════════════════════════════════════
     메인 초기화
  ═══════════════════════════════════════════════ */
  async function init(){
    try{
      const res = await fetch(DATA_URL + '?t=' + Date.now());
      if(!res.ok) throw new Error(`동기화 필요 (${res.status}) — 앱에서 분석 실행 버튼을 눌러주세요`);
      const data = await res.json();

      updateXSignal(data);
      updatePlanetGrid(data);

    } catch(e){
      console.warn('[astro_widget]', e.message);
      showError(e.message);
    }
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    setTimeout(init, 900);
  }
})();
