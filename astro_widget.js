/**
 * jhonber.com 천체 점성술 위젯 — index.html 구조 대응
 * 타겟: ovSignals, ovCrdScore/Gauge/Level, planetGrid, moonPhaseInfo, moonPhaseName/Icon/Desc
 * 클릭 → 어스펙트 해설 모달
 */
(function () {
  'use strict';

  const DATA_URL = 'https://gist.githubusercontent.com/JHONBERMAN/fee5f407cb28e180a9e692a12055d987/raw/data.json';

  /* ── 행성 한글·심볼 ── */
  const PKR  = { Sun:'태양',Moon:'달',Mercury:'수성',Venus:'금성',Mars:'화성',
                 Jupiter:'목성',Saturn:'토성',Uranus:'천왕성',Neptune:'해왕성',
                 Pluto:'명왕성','True Node':'노스노드' };
  const PSYM = { Sun:'☉',Moon:'☽',Mercury:'☿',Venus:'♀',Mars:'♂',
                 Jupiter:'♃',Saturn:'♄',Uranus:'♅',Neptune:'♆',
                 Pluto:'♇','True Node':'☊' };

  /* ── 어스펙트 기본 해설 ── */
  const ASP_INFO = {
    'Conjunction':       { ko:'합 (0°)',      color:'#00e5ff', crd:'HIGH', tone:'변곡',  base:'두 행성 에너지가 융합되어 새로운 사이클을 시작합니다. 메리먼 통계에서 합은 시장 전환점 형성 확률이 가장 높은 어스펙트입니다. 특히 외행성 합은 수십 년 단위 시장 구조 변화의 시작점이 됩니다.' },
    'Opposition':        { ko:'대립각 (180°)', color:'#ff4444', crd:'HIGH', tone:'반전',  base:'두 행성이 정반대에서 긴장을 형성합니다. 에너지 절정에서 반전이 일어나기 쉬운 구간으로, 과도한 포지션은 위험합니다. 보름달과 유사한 "가득 찬 후 비워지는" 에너지입니다.' },
    'Square':            { ko:'스퀘어 (90°)',  color:'#ff4444', crd:'HIGH', tone:'변동',  base:'마찰과 도전 에너지로 단기 변동성이 확대됩니다. 예상치 못한 뉴스·정책 변화가 동반될 수 있으며, 메리먼 통계상 스퀘어 전후 ±3 거래일 내 급등락 빈도가 높습니다.' },
    'Trine':             { ko:'트라인 (120°)', color:'#00e676', crd:'LOW',  tone:'순풍',  base:'두 행성이 조화롭게 협력합니다. 추세 지속 및 모멘텀 강화 구간으로, 기존 방향성이 가속될 가능성이 높습니다. 레버리지 포지션이 유리한 구간입니다.' },
    'Sextile':           { ko:'섹스타일 (60°)',color:'#00e676', crd:'LOW',  tone:'기회',  base:'소규모 기회 에너지입니다. 트라인보다 약하지만 안정적인 상승 모멘텀을 지지합니다. 단기 매수 기회를 탐색하기 좋은 구간입니다.' },
    'Parallel':          { ko:'평행 (적위 동일)',color:'#00e5ff',crd:'MID', tone:'강화',  base:'두 행성의 적위(하늘의 위도)가 일치합니다. 합(Conjunction)과 유사한 효과를 내며, 해당 어스펙트의 CRD 에너지를 증폭시킵니다. 동시에 활성화될 경우 효과가 배가됩니다.' },
    'Contra-Parallel':   { ko:'역평행 (적위 반대)',color:'#ff4444',crd:'MID',tone:'경고', base:'두 행성의 적위가 반대 방향으로 일치합니다. 대립각(Opposition)과 유사한 긴장 에너지로, 반전·충돌 가능성을 높입니다. 기존 추세에 대한 경고 신호입니다.' },
    'Quincunx':          { ko:'퀸쿤크스 (150°)',color:'#f59e0b',crd:'MID', tone:'조정',  base:'불편한 조정이 요구되는 어스펙트입니다. 두 에너지가 서로 어색하게 맞닿아 예측하기 어려운 변화를 만듭니다. 포트폴리오 재조정 신호로 해석하세요.' },
  };

  /* ── 행성 쌍 해설 (메리먼 금융 점성술) ── */
  const PAIR_INFO = {
    'Sun-Saturn':       { sector:'규제·비용·채권', desc:'책임과 제약의 에너지. 주식시장에 압박을 주는 조합으로, 비용 상승·규제 강화·경기 둔화 우려와 연결됩니다. 메리먼은 이 조합을 "시장의 억제력"으로 정의합니다.' },
    'Sun-Mars':         { sector:'에너지·원자재·방산', desc:'공격적 행동과 충돌 에너지. 원자재·에너지 섹터의 급격한 움직임과 연관되며, 지정학적 리스크가 부각될 수 있습니다. 단기 변동성 급등 유발 가능.' },
    'Sun-Jupiter':      { sector:'성장주·부동산·헬스', desc:'팽창과 낙관의 에너지. 시장 전반에 활력을 불어넣는 조합으로 역사적으로 주가 상승과 연관성이 높습니다. 과도한 낙관주의로 인한 거품 형성에도 주의 필요.' },
    'Sun-Uranus':       { sector:'테크·AI·가상자산', desc:'예측 불가능한 돌발 변수. 기술 혁신 또는 갑작스러운 시스템 변화를 상징합니다. 시장 서프라이즈 뉴스와 동반되는 경우가 많으며, 변동성 급등 경보 구간입니다.' },
    'Sun-Neptune':      { sector:'에너지·제약·가상자산', desc:'불확실성과 환상의 에너지. 정보의 혼탁함, 사기·루머로 인한 시장 혼선 가능성. 가상자산·바이오 섹터에서 비이성적 움직임 발생 경향.' },
    'Sun-Pluto':        { sector:'금융권·자원·M&A', desc:'권력 집중과 근본적 변혁. 대형 M&A, 금융 구조 개편, 자원 패권 다툼과 연관됩니다. 극단적 고점 또는 저점 형성의 촉매제가 될 수 있습니다.' },
    'Moon-Saturn':      { sector:'부동산·방어주·채권', desc:'군중 심리의 위축. 소비자 심리 지수 하락, 안전 자산 선호 증가와 연관됩니다. 단기적 매도 압력이 나타날 수 있습니다.' },
    'Moon-Mars':        { sector:'소비재·에너지', desc:'감정적 충동과 과잉 반응. 군중의 공황 매도 또는 FOMO 매수가 유발될 수 있는 구간. 단기 과열·과냉 후 급반전 패턴.' },
    'Moon-Jupiter':     { sector:'소비재·부동산·식품', desc:'감정적 낙관주의. 소비 지출 증가, 소매·외식·부동산 섹터 강세와 연관됩니다. 일반 대중의 투자 심리가 개선되는 구간.' },
    'Mercury-Mars':     { sector:'반도체·통신·물류', desc:'빠른 결정과 충동적 행동. 과속 거래·뉴스 오버리액션에 주의. 정보 이동 속도가 빨라지는 구간으로 알고리즘 트레이딩 변동성 증가 가능.' },
    'Mercury-Saturn':   { sector:'채권·금융데이터·계약', desc:'신중한 분석과 지연. 기업 실적 발표·계약 체결의 지연 또는 부정적 정보 공개. 채권 시장의 긴축 기대가 반영되는 구간.' },
    'Mercury-Uranus':   { sector:'테크·AI·통신', desc:'혁신적 아이디어와 돌발 발표. 기술 관련 서프라이즈 뉴스(신제품, 규제 변화, 해킹) 발생 빈도가 높습니다. 알트코인·반도체 급등 유발 가능.' },
    'Venus-Mars':       { sector:'소비재·사치품·부동산', desc:'욕망과 행동의 결합. 소비 심리 자극, 부동산·사치재·화장품 섹터 호재. 단기 매수세 유입이 예상되는 구간입니다.' },
    'Venus-Jupiter':    { sector:'금융·사치재·엔터', desc:'메리먼이 "행운의 조합"으로 분류하는 상승 어스펙트. 금융 확장, 주식 강세, 소비 낙관론. 역사적으로 주요 고점 형성과도 연관됩니다.' },
    'Venus-Saturn':     { sector:'채권·부동산·방어주', desc:'절제와 가치 재평가. 고평가 자산의 조정 압력. 장기 채권 선호, 부동산 시장 안정화 또는 소폭 하락 기대.' },
    'Venus-Pluto':      { sector:'금융·M&A·사치재', desc:'강력한 끌어당김과 집착. 대규모 자금 이동, 적대적 M&A, 헤지펀드 포지션 전환. 사치재·금융주 극단적 움직임 가능.' },
    'Mars-Jupiter':     { sector:'성장주·에너지·방산', desc:'공격적 팽창 에너지. 위험 자산 선호 급등, 성장주 강세, 원자재 상승. 과도한 레버리지가 쌓이는 구간으로 고점 경계 필요.' },
    'Mars-Saturn':      { sector:'방산·에너지·기간산업', desc:'메리먼이 "붉은 신호"라 부르는 조합. 에너지·방산·기간 산업에서 제약과 마찰. 지정학적 긴장이 고조되고 공급망 문제가 부각되는 경향.' },
    'Mars-Uranus':      { sector:'테크·가상자산·방산', desc:'폭발적 돌발 에너지. 예측 불가능한 급등락의 가장 위험한 조합 중 하나. 사고·사건·갑작스러운 정책 변화가 동반될 수 있습니다. 레버리지 청산 주의.' },
    'Mars-Pluto':       { sector:'자원·금융권·방산', desc:'권력 투쟁의 극한 에너지. 적대적 시장 조작, 대규모 청산, 자원 패권 갈등. 메리먼은 이 조합을 역사적 시장 붕괴와 연관 짓습니다.' },
    'Jupiter-Saturn':   { sector:'전 섹터 (대사이클)', desc:'20년 주기 사회경제 대사이클의 핵심. 합은 새 성장 사이클 시작, 대립각·스퀘어는 구조 재편 압력. 현재 위상에 따라 10~20년 단위 투자 전략이 결정됩니다.' },
    'Jupiter-Uranus':   { sector:'테크·AI·가상자산·바이오', desc:'기술 혁신 붐과 투기 과열의 조합. 역사적으로 닷컴 버블·AI 붐·가상자산 랠리와 일치. 메리먼 통계: 합 전후 ±6개월 나스닥 평균 +22%. 단, 이후 조정 폭도 큼.' },
    'Jupiter-Neptune':  { sector:'가상자산·에너지·제약', desc:'환상적 팽창과 버블 에너지. 가상자산·AI·제약 섹터의 비이성적 급등과 연관. 낙관론이 극에 달할 때 반전이 일어납니다. 투기 포지션 주의.' },
    'Jupiter-Pluto':    { sector:'금융·자원·M&A', desc:'부와 권력의 극대화 에너지. 대형 M&A, 원자재 슈퍼사이클, 금융 팽창. 2020년 목성-명왕성 합은 코로나 후 유동성 폭발과 일치했습니다.' },
    'Saturn-Uranus':    { ko:'규제 vs 혁신', sector:'테크·금융규제·가상자산', desc:'45년 주기 사이클. 기존 질서(토성)와 혁신(천왕성)의 충돌. 2021~22년 스퀘어는 인플레·긴축과 정확히 일치. 현재 이완기이나 재충돌 시 가상자산·테크 규제 리스크 재부상 가능.' },
    'Saturn-Neptune':   { ko:'현실 vs 환상', sector:'가상자산·에너지·금융시스템', desc:'36년 주기 메이저 사이클. 2026년 합은 1989년 이후 처음. 금융 시스템의 근본적 재편, 가상자산 제도화, AI 거버넌스 규제 프레임워크 수립의 신호. 장기 구조적 전환점.' },
    'Saturn-Pluto':     { sector:'금융시스템·자원·지정학', desc:'33~38년 주기. 2020년 합은 코로나·팬데믹·공급망 붕괴와 일치. 기존 금융·지정학 질서의 강제 해체와 재구성. 대규모 위기 후 새 패러다임 형성.' },
    'Uranus-Neptune':   { sector:'에너지·AI·금융혁명', desc:'171년 주기 초장기 사이클. 기술 문명과 집단 의식의 대전환. 현 세대가 목격할 수 있는 가장 근본적인 사회·경제 패러다임 변화를 예고합니다.' },
    'Uranus-Pluto':     { sector:'체제·기술·자원 혁명', desc:'127년 주기. 1960년대 합은 인권혁명·기술혁명. 스퀘어(2010~2020)는 아랍의 봄·금융위기·포퓰리즘 부상과 일치. 사회 체제 변혁과 시장 구조 재편의 장기 신호.' },
    'Neptune-Pluto':    { sector:'문명·에너지·금융체제', desc:'492년 주기 초초장기 사이클. 문명 단위의 에너지·경제 시스템 전환. 현재 세대의 투자 결정보다 다음 세대의 산업 패러다임에 영향을 미칩니다.' },
  };

  /* ── 행성 쌍 키 정규화 ── */
  function pairKey(planets){
    const order = ['Sun','Moon','Mercury','Venus','Mars','Jupiter','Saturn','Uranus','Neptune','Pluto','True Node'];
    const parts = planets.split(' & ').map(s=>s.trim());
    parts.sort((a,b)=>order.indexOf(a)-order.indexOf(b));
    return parts.join('-');
  }

  /* ── 어스펙트 타입 매칭 ── */
  function matchAsp(asp){
    for(const key of Object.keys(ASP_INFO)){
      if(asp.includes(key)) return ASP_INFO[key];
    }
    return null;
  }

  /* ── 별점 ── */
  function stars(orb){
    if(orb<=1) return '<span style="color:#f59e0b;font-size:11px">★★★ EXACT</span>';
    if(orb<=3) return '<span style="color:#f59e0b;font-size:11px">★★☆</span>';
    return '<span style="color:#c8a96e;font-size:11px">★☆☆</span>';
  }

  /* ── 달 위상 ── */
  function moonPhase(sunLon, moonLon){
    let d = moonLon - sunLon; if(d<0) d+=360;
    if(d<22.5)  return {icon:'🌑',name:'신월(New Moon)',       desc:'새 사이클 시작, 씨앗 에너지'};
    if(d<67.5)  return {icon:'🌒',name:'초승달',               desc:'성장·시작의 에너지'};
    if(d<112.5) return {icon:'🌓',name:'상현(First Quarter)',  desc:'결단·행동 요구 구간'};
    if(d<157.5) return {icon:'🌔',name:'차오르는 달',          desc:'모멘텀 축적 구간'};
    if(d<202.5) return {icon:'🌕',name:'보름달(Full Moon)',    desc:'에너지 절정·변곡 가능'};
    if(d<247.5) return {icon:'🌖',name:'기우는 달',            desc:'수확·정리 구간'};
    if(d<292.5) return {icon:'🌗',name:'하현(Last Quarter)',   desc:'전환·방출 구간'};
    if(d<337.5) return {icon:'🌘',name:'그믐달',               desc:'휴식·정화 구간'};
    return      {icon:'🌑',name:'신월(New Moon)',              desc:'새 사이클 시작'};
  }

  /* ══════════════════════════════════════════════
     모달 생성 (최초 1회)
  ══════════════════════════════════════════════ */
  function ensureModal(){
    if(document.getElementById('aw-modal')) return;
    const overlay = document.createElement('div');
    overlay.id = 'aw-modal';
    overlay.style.cssText = [
      'display:none;position:fixed;inset:0;z-index:9999',
      'background:rgba(0,0,0,.72);backdrop-filter:blur(4px)',
      'align-items:center;justify-content:center;padding:20px',
    ].join(';');
    overlay.innerHTML = `
      <div id="aw-modal-box" style="
        background:#131728;border:1px solid rgba(201,168,76,.3);border-radius:14px;
        max-width:480px;width:100%;max-height:80vh;overflow-y:auto;
        box-shadow:0 0 40px rgba(0,0,0,.6);position:relative;
      ">
        <button id="aw-modal-close" style="
          position:absolute;top:12px;right:14px;background:none;border:none;
          color:#8892b0;font-size:20px;cursor:pointer;line-height:1;padding:4px 8px;
        ">✕</button>
        <div id="aw-modal-body" style="padding:24px 24px 20px"></div>
      </div>`;
    document.body.appendChild(overlay);

    /* 닫기 */
    overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });
    document.getElementById('aw-modal-close').addEventListener('click', closeModal);
    document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });
  }

  function closeModal(){
    const m = document.getElementById('aw-modal');
    if(m){ m.style.display='none'; }
  }

  function openModal(aspect){
    ensureModal();
    const m   = document.getElementById('aw-modal');
    const body= document.getElementById('aw-modal-body');
    if(!m||!body) return;

    const orb   = aspect.orb_exactness||0;
    const asp   = aspect.aspect||'';
    const planets = aspect.planets||'';
    const impact  = aspect.impact||'';
    const sign1   = aspect.sign1||'';
    const sign2   = aspect.sign2||'';

    const aspInfo  = matchAsp(asp) || {ko:asp, color:'#c8a96e', crd:'--', tone:'--', base:''};
    const key      = pairKey(planets);
    const pairInfo = PAIR_INFO[key] || null;

    const ptsHtml = planets.split(' & ').map(p=>{
      const n=p.trim();
      return `<span style="font-size:1.1em">${PSYM[n]||''}</span> <b>${PKR[n]||n}</b>`;
    }).join(`<span style="color:${aspInfo.color};margin:0 6px;font-weight:700">× </span>`);

    const crdColor = aspInfo.crd==='HIGH'?'#ff4444':aspInfo.crd==='MID'?'#f59e0b':'#00e676';

    /* 정확도 바 */
    const exactPct = Math.max(0, Math.min(100, 100 - orb*20));
    const exactColor = orb<=1?'#f59e0b':orb<=3?'#c8a96e':'#445566';

    body.innerHTML = `
      <!-- 헤더 -->
      <div style="margin-bottom:18px">
        <div style="font-size:18px;font-weight:700;color:#e8eaf6;line-height:1.4;margin-bottom:6px">
          ${ptsHtml}
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-size:13px;font-weight:700;color:${aspInfo.color};
            border:1px solid ${aspInfo.color}44;padding:2px 10px;border-radius:20px">
            ${aspInfo.ko}
          </span>
          <span style="font-size:12px;color:#8892b0">${sign1||''}${sign2?' → '+sign2:''}</span>
          <span style="margin-left:auto;font-size:12px;
            color:${crdColor};border:1px solid ${crdColor}44;padding:2px 8px;border-radius:20px">
            CRD ${aspInfo.crd}
          </span>
        </div>
      </div>

      <!-- 정확도 -->
      <div style="margin-bottom:16px;padding:12px;background:rgba(255,255,255,.03);border-radius:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:11px;color:#8892b0;letter-spacing:1px">EXACTNESS</span>
          <span style="font-family:'Space Mono',monospace;font-size:13px;font-weight:700;color:${exactColor}">
            오차 ${orb.toFixed(2)}° &nbsp; ${stars(orb)}
          </span>
        </div>
        <div style="width:100%;height:5px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${exactPct}%;background:${exactColor};border-radius:3px;transition:width .8s"></div>
        </div>
        <div style="display:flex;justify-content:space-between;font-size:10px;color:#445566;margin-top:3px">
          <span>느슨함 (5°+)</span><span>강함 (3°)</span><span>EXACT (1°↓)</span>
        </div>
      </div>

      <!-- 어스펙트 해설 -->
      <div style="margin-bottom:14px">
        <div style="font-size:10px;color:${aspInfo.color};letter-spacing:2px;margin-bottom:6px">
          ASPECT — ${aspInfo.tone} 에너지
        </div>
        <div style="font-size:13px;color:#c8cfe0;line-height:1.8">${aspInfo.base}</div>
      </div>

      <!-- 행성 쌍 해설 -->
      ${pairInfo ? `
      <div style="margin-bottom:14px;padding:12px;background:rgba(201,168,76,.04);
        border:1px solid rgba(201,168,76,.15);border-radius:8px">
        <div style="font-size:10px;color:#c8a96e;letter-spacing:2px;margin-bottom:6px">
          PLANET PAIR — 관련 섹터: ${pairInfo.sector}
        </div>
        <div style="font-size:13px;color:#c8cfe0;line-height:1.8">${pairInfo.desc}</div>
      </div>` : ''}

      <!-- 앱 분석 결과 impact -->
      ${impact ? `
      <div style="padding:12px;background:rgba(0,229,255,.04);
        border:1px solid rgba(0,229,255,.12);border-radius:8px">
        <div style="font-size:10px;color:#00e5ff;letter-spacing:2px;margin-bottom:6px">
          TODAY'S SIGNAL
        </div>
        <div style="font-size:13px;color:#c8cfe0;line-height:1.8">${impact}</div>
      </div>` : ''}
    `;

    m.style.display = 'flex';
    /* 애니메이션 */
    const box = document.getElementById('aw-modal-box');
    if(box){ box.style.transform='scale(.95)';box.style.opacity='0';box.style.transition='transform .18s,opacity .18s';
      requestAnimationFrame(()=>requestAnimationFrame(()=>{ box.style.transform='scale(1)';box.style.opacity='1'; }));
    }
  }

  /* ══════════════════════════════════════════════
     X-SIGNAL 업데이트 (ovSignals + CRD 게이지)
  ══════════════════════════════════════════════ */
  function updateXSignal(data){
    const el = document.getElementById('ovSignals');
    if(!el) return;

    const aspects = (data.key_reversal_aspects||[]).slice(0,4);
    const alerts  = data.market_alerts||[];
    const g       = data.crd_gauge||{};
    const score   = g.score||0;
    const level   = g.level||'Low';

    /* CRD 게이지 */
    let gc='var(--green)', lc='var(--green)';
    if(score>=80){gc='var(--red)';lc='var(--red)';}
    else if(score>=50){gc='var(--gold)';lc='var(--gold)';}
    else if(score>=20){gc='#f59e0b';lc='#f59e0b';}
    const scoreEl=document.getElementById('ovCrdScore');
    if(scoreEl){scoreEl.textContent=score+' / 100';scoreEl.style.color=lc;}
    const gaugeEl=document.getElementById('ovCrdGauge');
    if(gaugeEl){gaugeEl.style.width=score+'%';gaugeEl.style.background=gc;}
    const levelEl=document.getElementById('ovCrdLevel');
    if(levelEl){
      const icon=score>=80?'⚡':score>=50?'⚠️':score>=20?'📊':'✅';
      levelEl.style.color=lc;
      levelEl.textContent=`${icon} ${level} — ${g.description||''}`;
    }

    /* 시그널 행 */
    el.innerHTML = aspects.map((a,i)=>{
      const orb=a.orb_exactness||0, asp=a.aspect||'';
      let dotCls='neutral';
      if(asp.includes('Square')||asp.includes('Opposition')||asp.includes('Contra')) dotCls='bear';
      else if(asp.includes('Conjunction')||asp.includes('Parallel')||asp.includes('Trine')) dotCls='bull';
      const scoreText=dotCls==='bear'?'-주의':dotCls==='bull'?'+강세':'중립';
      const scoreCls=dotCls==='bear'?'down':dotCls==='bull'?'up':'';
      const scoreStyle=dotCls==='neutral'?'style="color:var(--gold)"':'';
      const pts=(a.planets||'').split(' & ').map(p=>{const n=p.trim();return(PKR[n]||n)+(PSYM[n]?'('+PSYM[n]+')':'');}).join(' & ');
      const aspInfo = matchAsp(asp);
      const aspColor = aspInfo?aspInfo.color:'#c8a96e';
      return `<div class="signal-row aw-clickable" data-idx="${i}"
        style="cursor:pointer;border-radius:6px;padding:4px 6px;margin:0 -6px;transition:background .15s"
        onmouseover="this.style.background='rgba(255,255,255,.04)'"
        onmouseout="this.style.background='transparent'">
        <div class="signal-dot ${dotCls}"></div>
        <div class="signal-text">${pts}
          <span style="color:${aspColor};font-size:11px;margin-left:4px">${aspInfo?aspInfo.ko:asp}</span>
          · 오차 ${orb.toFixed(2)}° ${stars(orb)}
        </div>
        <div class="signal-score ${scoreCls}" ${scoreStyle}>${scoreText}</div>
      </div>`;
    }).join('') +
    alerts.slice(0,2).map(a=>`
      <div class="signal-row">
        <div class="signal-dot bear"></div>
        <div class="signal-text">⚠ ${a.type||''} — ${(a.message||'').substring(0,55)}</div>
        <div class="signal-score down">-주의</div>
      </div>`).join('') +
    `<div style="font-size:10px;color:var(--text2);margin-top:8px;letter-spacing:1px">
      ${data.timestamp_ny||'--'} · Swiss Ephemeris · CRD ${score}/100
      <span style="color:#445;margin-left:6px">· 각 시그널 클릭 시 해설</span>
    </div>`;

    /* 클릭 이벤트 바인딩 */
    el.querySelectorAll('.aw-clickable').forEach(row=>{
      row.addEventListener('click', ()=>{
        const idx = parseInt(row.dataset.idx);
        if(!isNaN(idx) && aspects[idx]) openModal(aspects[idx]);
      });
    });
  }

  /* ══════════════════════════════════════════════
     행성 그리드 업데이트
  ══════════════════════════════════════════════ */
  function updatePlanetGrid(data){
    const planets=data.planets_status||{};
    const sun=planets.Sun||{}, moon=planets.Moon||{};
    const phase=moonPhase(sun.longitude||0, moon.longitude||0);

    const phaseInfoEl=document.getElementById('moonPhaseInfo');
    if(phaseInfoEl){
      phaseInfoEl.style.cssText+='display:flex;align-items:center;gap:10px;text-align:left';
      phaseInfoEl.innerHTML=
        `<span style="font-size:24px">${phase.icon}</span>`+
        `<div><div style="font-size:13px;color:var(--text);font-weight:600">${phase.name}</div>`+
        `<div style="font-size:12px;color:var(--text2)">${phase.desc}</div></div>`+
        `<div style="margin-left:auto;font-size:11px;color:var(--text2)">☉${(sun.longitude||0).toFixed(2)}° ☽${(moon.longitude||0).toFixed(2)}°</div>`;
    }
    const piEl=document.getElementById('moonPhaseIcon'); if(piEl) piEl.textContent=phase.icon;
    const pnEl=document.getElementById('moonPhaseName'); if(pnEl) pnEl.textContent=phase.name;
    const pdEl=document.getElementById('moonPhaseDesc'); if(pdEl) pdEl.textContent=phase.desc;

    const el=document.getElementById('planetGrid');
    if(!el) return;
    el.innerHTML=Object.entries(planets).map(([name,info])=>{
      const retro=info.is_retrograde, station=info.is_stationing;
      const badge=retro?'<span style="color:var(--red);font-size:10px;margin-left:3px">℞역행</span>':
                  station?'<span style="color:var(--gold);font-size:10px;margin-left:3px">정지</span>':'';
      const hl=(retro||station)?'border-color:rgba(200,169,110,.5);':'';
      return `<div class="planet-card" style="${hl}">
        <div class="planet-symbol">${PSYM[name]||''}</div>
        <div class="planet-name">${PKR[name]||name}${badge}</div>
        <div class="planet-sign">${info.current_sign||'--'} ${(info.sign_degree||0).toFixed(1)}°</div>
        <div class="planet-deg">총 ${(info.longitude||0).toFixed(2)}°</div>
      </div>`;
    }).join('');
  }

  function showError(msg){
    const el=document.getElementById('ovSignals');
    if(el) el.innerHTML=`<div class="signal-row"><div class="signal-dot neutral"></div><div class="signal-text" style="color:var(--text2)">⚠ ${msg}</div></div>`;
  }

  /* ══════════════════════════════════════════════
     초기화
  ══════════════════════════════════════════════ */
  async function init(){
    ensureModal();
    try{
      const res=await fetch(DATA_URL+'?t='+Date.now());
      if(!res.ok) throw new Error(`동기화 필요 (${res.status}) — 앱에서 분석 실행 버튼을 눌러주세요`);
      const data=await res.json();
      updateXSignal(data);
      updatePlanetGrid(data);
    }catch(e){
      console.warn('[astro_widget]',e.message);
      showError(e.message);
    }
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',init);
  } else {
    setTimeout(init,900);
  }
})();
