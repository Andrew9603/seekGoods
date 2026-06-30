<template>
  <div class="site">
    <header class="site-header">
      <button class="site-brand" type="button" @click="scrollTo('home')">
        <img src="/favicon.svg" alt="" />
        <b>SeekGoods</b>
      </button>
      <span class="header-state"><i></i>2026-03 · 仿真完成</span>
    </header>

    <section id="home" ref="storyEl" class="story" aria-label="SeekGoods 首页与决策回放">
      <div class="story-sticky">
        <div class="home-copy">
          <img src="/favicon.svg" alt="" />
          <h1>让每一次找货都换成最优解</h1>
          <p>面向一个自然月持续决策，在收益、空驶与司机偏好之间找到更好的平衡。</p>
          <span class="scroll-hint">向下滚动，进入决策回放</span>
        </div>

        <div class="home-globe map-wrap" aria-label="全球货运地图与决策路径">
          <div id="hero-map"></div>
          <div class="map-meta">
            <span>当前时间<b>{{ action?.simulation_end_time || '2026-03-01 00:00' }}</b></span>
            <span>当前位置<b>{{ locationText }}</b></span>
          </div>
        </div>

        <div id="replay" class="replay-panel">
          <div class="replay-heading">
            <p>月度决策回放</p>
            <span>STEP {{ step }} / {{ actions.length }}</span>
          </div>
        <div class="driver-tabs">
          <button v-for="driver in drivers" :key="driver.driver_id" :class="{active: selectedId === driver.driver_id}" @click="selectDriver(driver.driver_id)">
            {{ driver.driver_id }}<small>¥{{ money(driver.income.net_income) }}</small>
          </button>
        </div>

        <aside class="decision">
          <div class="decision-title">
            <div><small>STEP {{ step }}</small><h3>{{ actionTitle }}</h3></div>
            <b>{{ debug?.adaptive_mode || 'balanced' }}</b>
          </div>
          <p>{{ decisionText }}</p>
          <dl>
            <div><dt>候选货源</dt><dd>{{ debug?.returned_count ?? '—' }}</dd></div>
            <div><dt>规则拦截</dt><dd>{{ debug?.firewall_blocked_count ?? 0 }}</dd></div>
            <div><dt>预计净收益</dt><dd>{{ debug?.expected_net_profit ? `¥${money(debug.expected_net_profit)}` : '—' }}</dd></div>
            <div><dt>决策耗时</dt><dd>{{ debug?.total_decision_ms ? `${debug.total_decision_ms} ms` : '—' }}</dd></div>
          </dl>
          <div v-if="candidates.length" class="candidates">
            <header><span>候选订单</span><span>综合得分</span></header>
            <div v-for="(item, i) in candidates" :key="item.cargo_id">
              <span><i>{{ i + 1 }}</i><b>{{ item.cargo_id }}<small>净收益 ¥{{ money(item.net_profit) }}</small></b></span>
              <strong>{{ money(item.score) }}</strong>
            </div>
          </div>
          <div v-else class="empty">当前没有同时满足收益阈值与约束条件的订单，等待比低质量接单更有长期价值。</div>
        </aside>

        <div class="timeline">
          <button @click="toggle">{{ playing ? '暂停' : '播放' }}</button>
          <input v-model.number="index" type="range" min="0" :max="Math.max(0, actions.length - 1)" aria-label="决策时间轴">
          <span><b>{{ progress }}%</b></span>
        </div>
      </div>
      </div>
    </section>

    <main class="app">
      <section class="metrics" aria-label="仿真摘要">
        <article><span>仿真周期</span><strong>{{ runSummary.simulation_duration_days }} 天</strong><small>完整自然月</small></article>
        <article><span>决策步数</span><strong>{{ runSummary.completed_steps }}</strong><small>接单、等待与空驶</small></article>
        <article><span>完成订单</span><strong>{{ totalOrders }}</strong><small>两位司机合计</small></article>
        <article><span>约束满足</span><strong class="green">100%</strong><small>{{ totalRules }} 条偏好规则</small></article>
        <article><span>Token 消耗</span><strong>{{ summary.total_token_usage.total_tokens.toLocaleString() }}</strong><small>仅用于偏好理解</small></article>
      </section>

    <section class="driver-detail">
      <div class="income">
        <p class="eyebrow">{{ selected.driver_id }} 月度结果</p>
        <h2>¥{{ money(selected.income.net_income, 2) }}</h2>
        <div class="income-bar"><i :style="{width: `${incomeRatio}%`}"></i></div>
        <p><span>毛收入 ¥{{ money(selected.income.gross_income) }}</span><span>里程成本 ¥{{ money(selected.income.cost) }}</span></p>
      </div>
      <div class="preferences">
        <div class="rules">
          <article v-for="rule in rules" :key="rule[0]"><i></i><div><b>{{ rule[0] }}</b><p>{{ rule[1] }}</p></div><strong>已满足</strong></article>
        </div>
      </div>
    </section>

    <section id="strategies" class="section strategies">
      <div class="strategy-table">
        <div class="strategy-row header"><span>策略</span><span>总净收益</span><span>完成订单</span><span>偏好罚款</span><span>Token</span></div>
        <div v-for="item in strategies" :key="item.profile" class="strategy-row" :class="{winner: item.profile === best.profile}">
          <span><b>{{ strategyName(item.profile) }}</b><small v-if="item.profile === best.profile">本组最佳</small></span>
          <span class="bar"><i :style="{width: `${barWidth(item)}%`}"></i><b>¥{{ money(item.total_net_income_all_drivers) }}</b></span>
          <span>{{ item.order_count }}</span><span class="green">¥{{ money(item.total_preference_penalty) }}</span><span>{{ Number(item.total_tokens).toLocaleString() }}</span>
        </div>
      </div>
    </section>

    <footer><span class="brand"><img src="/favicon.svg" alt=""><b>SeekGoods</b></span><b>Rule-first · Tool-driven · Rolling horizon</b><span>数据来自 2026-03 本地仿真结果</span></footer>
  </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import dashboardData from './data/dashboard.json'

const runSummary = dashboardData.runSummary
const income = dashboardData.income
const actionData = dashboardData.actions
const debugData = dashboardData.debug
const csvRaw = dashboardData.strategyCsv
const csvLine = line => {
  const out = []; let value = ''; let quoted = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (c === '"' && line[i + 1] === '"') { value += '"'; i++ }
    else if (c === '"') quoted = !quoted
    else if (c === ',' && !quoted) { out.push(value); value = '' }
    else value += c
  }
  out.push(value); return out
}
const lines = csvRaw.trim().split(/\r?\n/); const heads = csvLine(lines[0])
const strategies = lines.slice(1).map(line => Object.fromEntries(heads.map((h, i) => [h, csvLine(line)[i]])))
const summary = income.summary
const drivers = income.drivers
const selectedId = ref('D001')
const index = ref(0)
const playing = ref(false)
const storyEl = ref(null)
let storyProgress = 0
let storyTarget = 0
let timer, marker, heroMap, heroAnimation, scrollFrame, markerFrame
let heroLng = 108
const heroStartZoom = 1.62
let heroPaused = false
let heroResumeTimer
let globeCircleInset = 0
let markerPosition = null

const selected = computed(() => drivers.find(x => x.driver_id === selectedId.value))
const actions = computed(() => actionData[selectedId.value])
const debugs = computed(() => debugData[selectedId.value])
const action = computed(() => actions.value[index.value])
const debug = computed(() => debugs.value[index.value])
const step = computed(() => index.value + 1)
const progress = computed(() => Math.round(step.value / actions.value.length * 100))
const candidates = computed(() => debug.value?.top_5_order_scores?.slice(0, 4) || [])
const totalOrders = computed(() => strategies.find(x => x.profile === 'robust_mpc_adaptive')?.order_count || 140)
const totalRules = computed(() => drivers.reduce((sum, x) => sum + x.preference_check.rules.length, 0))
const best = computed(() => [...strategies].sort((a,b) => +b.total_net_income_all_drivers - +a.total_net_income_all_drivers)[0])
const incomeRatio = computed(() => selected.value.income.net_income / selected.value.income.gross_income * 100)
const locationText = computed(() => action.value ? `${action.value.position_after.lat.toFixed(2)}, ${action.value.position_after.lng.toFixed(2)}` : '22.54, 114.06')
const actionTitle = computed(() => action.value?.action.action === 'take_order' ? `接单 ${action.value.action.params.cargo_id}` : action.value?.action.action === 'reposition' ? '主动空驶' : '原地等待')
const decisionText = computed(() => {
  if (action.value?.action.action === 'take_order') return `在过滤 ${debug.value?.firewall_blocked_count || 0} 个约束风险候选后，滚动规划选择当前综合价值最高的订单。`
  if (action.value?.action.action === 'reposition') return '当前位置短期货源价值偏低，Agent 前往更有机会或必须到达的区域。'
  return '当前没有合适订单，或需要满足休息与日期约束。等待为后续决策保留空间。'
})
const ruleText = {
  D001: [['每日连续休息不少于 5 小时','31 天休息窗口均满足，未发生疲劳驾驶风险。'],['禁止承接机械设备类货源','候选货源先经过品类防火墙过滤。'],['不承接惠州起讫货源','限制区域订单不会进入评分阶段。'],['每月至少 3 个完整休息日','实际完成 5 个完整休息日。'],['3 月 4–5 日避开深圳','指定日期区域约束已完成。']],
  D002: [['每日 00:00–06:00 停车休息','夜间时间窗内不接单、不空驶。'],['禁止承接蔬菜类货源','品类限制由偏好防火墙硬性执行。'],['增城业务覆盖不少于 4 天','实际在 19 个不同日期完成相关订单。'],['接货空驶距离不超过 55 km','超出阈值的订单直接过滤。'],['每月至少 2 个完整休息日','实际完成 2 个完整休息日。'],['完成指定地点与日期任务','增城盘库及四会行程均按时完成。']]
}
const rules = computed(() => ruleText[selectedId.value])
const money = (v, digits=0) => Number(v || 0).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits})
const strategyName = id => ({safe_profit_plus:'安全收益增强',robust_mpc:'稳健滚动规划',robust_mpc_adaptive:'自适应滚动规划'})[id] || id
const barWidth = item => +item.total_net_income_all_drivers / +best.value.total_net_income_all_drivers * 100
function selectDriver(id){ selectedId.value=id; index.value=0; stop() }
function toggle(){
  if(playing.value) return stop()
  if(index.value >= actions.value.length-1) index.value=0
  playing.value=true
  timer=setInterval(()=> index.value >= actions.value.length-1 ? stop() : index.value++,800)
}
function stop(){ playing.value=false; clearInterval(timer);cancelAnimationFrame(markerFrame) }
function scrollTo(id){
  const story=storyEl.value
  if(!story)return
  const top=id === 'replay'
    ? story.offsetTop+(story.offsetHeight-window.innerHeight)*.86
    : story.offsetTop
  window.scrollTo({top,behavior:'smooth'})
}
function updateStory(){
  const el=storyEl.value
  if(!el){scrollFrame=0;return}
  const delta=storyTarget-storyProgress
  storyProgress=Math.abs(delta)<.0005?storyTarget:storyProgress+delta*.13
  el.closest('.site')?.style.setProperty('--story-progress',String(storyProgress))
  const globe=el.querySelector('.home-globe')
  if(globe){
    globe.style.setProperty('--globe-inset',`${globeCircleInset*(1-storyProgress)}px`)
  }
  if(heroMap?.loaded()&&storyProgress < .98){
    const cameraProgress=Math.min(1,Math.max(0,(storyProgress-.06)/.86))
    const eased=cameraProgress*cameraProgress*cameraProgress*(cameraProgress*(cameraProgress*6-15)+10)
    heroMap.jumpTo({
      center:[heroLng+(113.35-heroLng)*eased,28+(23.15-28)*eased],
      zoom:heroStartZoom+(7.35-heroStartZoom)*eased
    })
  }
  if(Math.abs(storyTarget-storyProgress)>.0005)scrollFrame=requestAnimationFrame(updateStory)
  else scrollFrame=0
}
function onScroll(){
  const el=storyEl.value
  if(!el)return
  const rect=el.getBoundingClientRect()
  const distance=Math.max(1,el.offsetHeight-window.innerHeight)
  storyTarget=Math.min(1,Math.max(0,-rect.top/distance))
  if(!scrollFrame)scrollFrame=requestAnimationFrame(updateStory)
}
function updateLayoutMetrics(){
  const globe=storyEl.value?.querySelector('.home-globe')
  if(globe)globeCircleInset=Math.max(0,(globe.offsetWidth-globe.offsetHeight)/2)
  heroMap?.resize()
  onScroll()
}
function waitMap(n=40){ if(window.mapboxgl){ initHeroMap() } else if(n) setTimeout(()=>waitMap(n-1),100) }
function initHeroMap(){
  window.mapboxgl.accessToken='pk.eyJ1IjoiZGFyeWxnaW5uIiwiYSI6ImNtOTExN2o2azA0M3AybXB2NDd6eWgxYm0ifQ.tFmufPBOwV7ALPsDXMg8jg'
  heroMap=new window.mapboxgl.Map({
    container:'hero-map',
    style:'mapbox://styles/mapbox/standard',
    projection:'globe',
    center:[heroLng,28],
    zoom:heroStartZoom,
    minZoom:1.35,
    maxZoom:11,
    bearing:0,
    pitch:0,
    attributionControl:false,
    dragRotate:true,
    dragPan:true,
    scrollZoom:false,
    doubleClickZoom:false,
    touchZoomRotate:true,
    renderWorldCopies:false,
    antialias:true,
    config:{basemap:{lightPreset:'day',showPointOfInterestLabels:false,showTransitLabels:false,showRoadLabels:true,showPlaceLabels:true}}
  })
  heroMap.on('style.load',()=>{
    heroMap.setProjection('globe')
    heroMap.setFog({range:[.5,10],color:'rgba(255,255,255,0)','high-color':'rgba(255,255,255,0)','space-color':'rgba(0,0,0,0)','horizon-blend':0,'star-intensity':0})
    heroMap.addSource('route',{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:[]}}})
    heroMap.addLayer({id:'route',type:'line',source:'route',paint:{'line-color':'#176bff','line-width':3,'line-opacity':.82}})
    updateMap()
  })
  const pause=()=>{
    heroPaused=true
    clearTimeout(heroResumeTimer)
    heroResumeTimer=setTimeout(()=>{heroPaused=false},2600)
  }
  ;['dragstart','zoomstart','rotatestart','touchstart','mousedown','wheel'].forEach(event=>heroMap.on(event,pause))
  const rotate=()=>{
    if(heroMap?.loaded()&&!heroPaused&&storyProgress<.02){
      heroLng=(heroLng+.045)%360
      heroMap.setCenter([heroLng,28])
    }
  }
  heroAnimation=setInterval(rotate,80)
}
function animateMarker(target,duration=650,followCamera=false){
  if(!marker||!markerPosition){marker?.setLngLat(target);markerPosition=target;return}
  if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){
    marker.setLngLat(target)
    if(followCamera)heroMap?.jumpTo({center:target,zoom:7.35})
    markerPosition=target
    return
  }
  cancelAnimationFrame(markerFrame)
  const from=[...markerPosition]
  const cameraFrom=followCamera&&heroMap ? heroMap.getCenter() : null
  const start=performance.now()
  const tick=now=>{
    const t=Math.min(1,(now-start)/duration)
    const eased=1-Math.pow(1-t,4)
    const current=[from[0]+(target[0]-from[0])*eased,from[1]+(target[1]-from[1])*eased]
    marker.setLngLat(current)
    if(cameraFrom){
      heroMap.jumpTo({
        center:[
          cameraFrom.lng+(target[0]-cameraFrom.lng)*eased,
          cameraFrom.lat+(target[1]-cameraFrom.lat)*eased
        ],
        zoom:7.35
      })
    }
    markerPosition=current
    if(t<1)markerFrame=requestAnimationFrame(tick)
  }
  markerFrame=requestAnimationFrame(tick)
}
function updateMap(){
  if(!heroMap?.getSource('route')) return
  const coords=actions.value.slice(0,index.value+1).map(x=>x.position_after).filter(Boolean).map(x=>[x.lng,x.lat])
  heroMap.getSource('route').setData({type:'Feature',geometry:{type:'LineString',coordinates:coords}})
  const p=action.value?.position_after;if(!p)return
  const target=[p.lng,p.lat]
  if(!marker){
    marker=new window.mapboxgl.Marker({color:'#111'}).setLngLat(target).addTo(heroMap)
    markerPosition=target
  }else if(playing.value){
    animateMarker(target,720,storyProgress>.78)
  }
  else{cancelAnimationFrame(markerFrame);marker.setLngLat(target);markerPosition=target}
}
watch([selectedId,index],()=>nextTick(updateMap))
onMounted(()=>{waitMap();updateLayoutMetrics();window.addEventListener('scroll',onScroll,{passive:true});window.addEventListener('resize',updateLayoutMetrics)})
onBeforeUnmount(()=>{stop();heroMap?.remove();clearInterval(heroAnimation);clearTimeout(heroResumeTimer);cancelAnimationFrame(scrollFrame);cancelAnimationFrame(markerFrame);window.removeEventListener('scroll',onScroll);window.removeEventListener('resize',updateLayoutMetrics)})
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;600;700&display=swap');
:root{--ink:#111214;--muted:#70747b;--line:#e7e8ea;--soft:#f5f6f7;--blue:#176bff;--green:#16845b;font-family:Manrope,'Noto Sans SC',sans-serif;color:var(--ink);background:#fff;font-synthesis:none}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;min-width:320px}button,input{font:inherit}a{color:inherit;text-decoration:none}.site{width:100%;overflow:hidden}.site:not(.show-dashboard){height:100vh}.site-header{position:fixed;z-index:100;top:0;left:0;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;width:100%;height:68px;padding:0 32px;border-bottom:1px solid rgba(223,225,228,.8);background:rgba(255,255,255,.9);backdrop-filter:blur(14px)}.site-brand{display:flex;align-items:center;gap:10px;width:max-content;padding:0;border:0;background:transparent;cursor:pointer}.site-brand img{width:30px;height:30px}.site-brand b{letter-spacing:-.04em}.site-header nav{display:flex;gap:4px;padding:4px;border-radius:999px;background:#f3f4f5}.site-header nav button{padding:8px 17px;border:0;border-radius:999px;color:#777b82;background:transparent;cursor:pointer;font-size:11px;font-weight:700}.site-header nav button.active{color:#fff;background:#111}.header-state{justify-self:end;display:flex;align-items:center;gap:8px;color:#666a70;font-size:11px;font-weight:600}.header-state i{width:7px;height:7px;border-radius:50%;background:#20ad73;box-shadow:0 0 0 4px #e7f7f0}.page-track{display:flex;align-items:flex-start;width:200vw;transition:transform .72s cubic-bezier(.22,1,.36,1);will-change:transform}.slide{flex:0 0 100vw;width:100vw}.site:not(.show-dashboard) .dashboard-slide{height:100vh;overflow:hidden}.home-page{position:relative;height:100vh;min-height:620px;overflow:hidden;padding-top:68px;background:#fff}.home-copy{position:relative;z-index:5;display:flex;align-items:center;flex-direction:column;padding-top:clamp(30px,4.5vh,48px);text-align:center}.home-copy>img{width:clamp(52px,5vw,68px);height:clamp(52px,5vw,68px);margin-bottom:18px}.home-copy h1{margin:0;font-size:clamp(38px,4.3vw,64px);font-weight:500;line-height:1.04;letter-spacing:-.04em}.home-copy p{max-width:650px;margin:14px 20px 0;color:#81848a;font-size:clamp(13px,1.1vw,16px);line-height:1.6}.home-globe{position:absolute;top:clamp(315px,38vh,355px);left:50%;width:min(64vh,680px);height:min(64vh,680px);transform:translateX(-50%);overflow:hidden;border-radius:50%}.home-globe #hero-map{position:absolute;inset:-14%}.home-globe .maplibregl-control-container{display:none}.app{width:min(1440px,100%);margin:auto;padding:68px 42px 48px}.brand{display:inline-flex;align-items:center;gap:10px;width:max-content;letter-spacing:-.04em}.brand img{width:30px;height:30px}.hero{display:grid;grid-template-columns:1.45fr .55fr;gap:70px;align-items:end;padding:88px 0 62px}.eyebrow{margin:0 0 15px;color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.hero h1{max-width:800px;margin:0;font-size:clamp(48px,6.2vw,90px);line-height:.98;letter-spacing:-.055em}.intro{max-width:650px;margin:28px 0 0;color:var(--muted);font-size:18px;line-height:1.75}.score{padding-left:34px;border-left:1px solid var(--line)}.score span,.score small{display:block;color:var(--muted)}.score strong{display:block;margin:14px 0 8px;font-size:clamp(44px,5vw,72px);line-height:1;letter-spacing:-.055em}.score small,.green{color:var(--green)!important}.metrics{display:grid;grid-template-columns:repeat(5,1fr);border-block:1px solid var(--line)}.metrics article{padding:26px 22px;border-right:1px solid var(--line)}.metrics article:first-child{padding-left:0}.metrics article:last-child{border:0}.metrics span,.metrics small{display:block;color:var(--muted);font-size:12px}.metrics strong{display:block;margin:9px 0 6px;font-size:26px;letter-spacing:-.04em}.section{padding-top:100px;scroll-margin-top:80px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:30px;margin-bottom:32px}.section-head h2,.driver-detail h2{margin:0;font-size:clamp(28px,3vw,42px);line-height:1.14;letter-spacing:-.045em}.section-head>p{max-width:420px;margin:0;color:var(--muted);line-height:1.7}.driver-tabs{display:flex;padding:4px;border-radius:10px;background:var(--soft)}.driver-tabs button{min-width:110px;padding:10px 14px;border:0;border-radius:7px;color:#6d7177;background:transparent;cursor:pointer;font-size:12px;font-weight:800;text-align:left}.driver-tabs small{display:block;margin-top:3px;font-weight:500}.driver-tabs .active{color:#fff;background:var(--ink)}.replay{display:grid;grid-template-columns:1.55fr .65fr;min-height:590px;border:1px solid var(--line);border-radius:16px;overflow:hidden}.map-wrap{position:relative;min-height:590px;background:#edf0f1}#map{position:absolute;inset:0}.map-meta{position:absolute;z-index:5;bottom:18px;left:18px;display:flex;gap:28px;padding:13px 16px;border-radius:10px;background:rgba(17,18,20,.88);color:#fff}.map-meta span{color:#b9bdc3;font-size:10px}.map-meta b{display:block;margin-top:4px;color:#fff;font-size:12px}.decision{display:flex;flex-direction:column;padding:30px;border-left:1px solid var(--line)}.decision-title{display:flex;justify-content:space-between;align-items:start}.decision-title small{color:var(--blue);font-size:10px;font-weight:800;letter-spacing:.1em}.decision-title h3{margin:8px 0 0;font-size:25px;letter-spacing:-.04em}.decision-title>b{padding:6px 9px;border-radius:6px;color:var(--green);background:#eaf7f2;font-size:10px}.decision>p{margin:24px 0;color:#62666d;font-size:14px;line-height:1.75}.decision dl{display:grid;grid-template-columns:1fr 1fr;margin:0;border-top:1px solid var(--line);border-left:1px solid var(--line)}.decision dl div{padding:15px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}dt{color:var(--muted);font-size:10px}dd{margin:6px 0 0;font-size:16px;font-weight:800}.candidates{margin-top:25px}.candidates header{display:flex;justify-content:space-between;color:var(--muted);font-size:10px}.candidates>div{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--line)}.candidates>div>span{display:flex;align-items:center;gap:11px}.candidates i{display:grid;place-items:center;width:25px;height:25px;border-radius:50%;background:var(--soft);font-style:normal;font-size:10px}.candidates small{display:block;margin-top:2px;color:var(--muted);font-weight:500}.empty{margin-top:25px;padding:18px;color:var(--muted);background:var(--soft);font-size:12px;line-height:1.7}.timeline{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:20px;padding-top:20px}.timeline button{width:70px;padding:9px 0;border:0;border-radius:7px;color:#fff;background:var(--ink);cursor:pointer;font-size:12px;font-weight:800}.timeline input{width:100%;accent-color:var(--blue)}.timeline>span{display:flex;gap:14px;color:var(--muted);font-size:11px}.timeline>span b{color:var(--ink)}.driver-detail{display:grid;grid-template-columns:.72fr 1.28fr;gap:70px;padding:105px 0;border-bottom:1px solid var(--line)}.income h2{font-size:clamp(48px,6vw,78px)}.income-bar{height:8px;margin:35px 0 14px;overflow:hidden;background:#e9eaec}.income-bar i{display:block;height:100%;background:var(--blue)}.income>p:last-child{display:flex;justify-content:space-between;color:var(--muted);font-size:11px}.pref-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:22px}.pref-head>b{color:var(--green);font-size:13px}.rules{border-top:1px solid var(--line)}.rules article{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:start;padding:17px 0;border-bottom:1px solid var(--line)}.rules article>i{width:9px;height:9px;margin-top:5px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px #e9f7f1}.rules b{font-size:13px}.rules p{margin:4px 0 0;color:var(--muted);font-size:11px;line-height:1.6}.rules strong{color:var(--green);font-size:11px}.strategy-table{border-top:1px solid var(--ink)}.strategy-row{display:grid;grid-template-columns:1.25fr 1.5fr .7fr .7fr .6fr;gap:18px;align-items:center;min-height:74px;padding:10px 14px;border-bottom:1px solid var(--line);font-size:13px}.strategy-row.header{min-height:44px;color:var(--muted);font-size:10px}.strategy-row small{display:block;margin-top:4px;color:var(--blue);font-size:9px}.strategy-row.winner{background:#f5f8ff}.bar{position:relative;display:flex;align-items:center;min-height:34px;padding:0 12px;overflow:hidden}.bar i{position:absolute;inset:0 auto 0 0;background:#e6edff}.bar b{position:relative}footer{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;margin-top:110px;padding-top:28px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}footer>b{color:var(--ink)}footer>span:last-child{justify-self:end}
@media(max-width:980px){.app{padding-inline:24px}.topbar{grid-template-columns:1fr auto}.topbar nav{display:none}.hero{grid-template-columns:1fr;gap:42px}.score{padding:0;border:0}.metrics{grid-template-columns:repeat(3,1fr)}.replay{grid-template-columns:1fr}.decision{border-top:1px solid var(--line);border-left:0}.driver-detail{grid-template-columns:1fr}.metrics article:nth-child(3){border-right:0}}
@media(max-width:680px){.site-header{height:60px;padding:0 14px}.site-brand b,.header-state{display:none}.site-header nav button{padding:7px 12px}.home-page{padding-top:60px}.home-copy{padding:30px 18px 0}.home-copy>img{width:48px;height:48px;margin-bottom:14px}.home-copy h1{font-size:33px;line-height:1.08}.home-copy p{max-width:330px;margin-top:11px;font-size:12px;line-height:1.55}.home-globe{top:278px;width:min(58vh,108vw);height:min(58vh,108vw)}.home-globe #hero-map{inset:-12%}.app{padding:60px 16px 48px}.hero{padding:64px 0 46px}.hero h1{font-size:49px}.intro{font-size:15px}.metrics{grid-template-columns:1fr 1fr}.metrics article,.metrics article:first-child{padding:18px 12px}.section{padding-top:75px}.section-head{align-items:stretch;flex-direction:column}.driver-tabs button{flex:1}.map-wrap{min-height:420px}.map-meta{right:12px;bottom:12px;left:12px;justify-content:space-between}.decision{padding:22px}.timeline{grid-template-columns:auto 1fr}.timeline>span{grid-column:1/-1;justify-content:space-between}.driver-detail{padding:80px 0}.pref-head{align-items:start;flex-direction:column}.strategy-table{overflow-x:auto}.strategy-row{min-width:720px}footer{grid-template-columns:1fr;gap:12px}footer>span:last-child{justify-self:start}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style>

<style>
.site{--story-progress:0;height:auto!important;overflow:clip}
.site-header{grid-template-columns:1fr auto;border-bottom:0}
.story{position:relative;height:230vh;background:#fff}
.story-sticky{position:sticky;top:0;height:100vh;min-height:680px;overflow:hidden;padding-top:68px}
.home-copy{position:absolute;z-index:8;top:clamp(96px,13vh,132px);left:50%;width:min(1120px,94vw);padding:0;transform:translate3d(-50%,calc(var(--story-progress) * -48px),0);opacity:clamp(0,calc(1 - var(--story-progress) * 2.5),1);pointer-events:none}
.home-copy>img{width:64px;height:64px;margin-bottom:18px}
.home-copy h1{font-size:clamp(42px,4.15vw,64px);line-height:1.03;letter-spacing:-.04em;white-space:nowrap}
.home-copy p{margin-top:16px;color:#70747b}
.scroll-hint{display:flex;align-items:center;gap:8px;margin-top:14px;transform:translateY(-10px);color:#8b8e94;font-size:11px;font-weight:700}
.scroll-hint::before{content:"";width:18px;height:28px;border:1px solid #c9cbd0;border-radius:999px;background:radial-gradient(circle at 50% 7px,#777 1.5px,transparent 2px)}
.home-globe{--globe-inset:max(0px,calc((57vw - min(82vh,760px))/2));position:absolute;z-index:3;top:calc(50% + 34px);left:3vw;width:57vw;height:min(82vh,760px);min-height:0;transform:translate3d(calc((1 - var(--story-progress)) * 19.5vw),calc(-50% + (1 - var(--story-progress)) * 34vh),0) scale(calc(1.345 - var(--story-progress) * .345));clip-path:inset(0 var(--globe-inset) round calc(14px + (1 - var(--story-progress)) * 490px));border-radius:14px;background:transparent;box-shadow:none;contain:layout paint;overflow:hidden;will-change:transform,clip-path}
.home-globe::after{content:"";position:absolute;z-index:8;inset:0;border:1px solid rgba(17,18,20,.1);border-radius:14px;opacity:clamp(0,calc((var(--story-progress) - .72) * 4),1);pointer-events:none}
.home-globe #hero-map{position:absolute;inset:0;overflow:hidden;border-radius:inherit;background:transparent}
.home-globe .mapboxgl-canvas-container,.home-globe .mapboxgl-canvas{border-radius:inherit;transform:none}
.home-globe .mapboxgl-control-container{display:none}
.home-globe .mapboxgl-marker{opacity:clamp(0,calc((var(--story-progress) - .58) * 4),1);backface-visibility:hidden;will-change:transform}
.home-globe .map-meta{opacity:clamp(0,calc((var(--story-progress) - .62) * 3.4),1);transform:translateY(calc((1 - var(--story-progress)) * 12px));pointer-events:none}
.replay-panel{position:absolute;z-index:5;top:calc(50% + 34px);right:3vw;display:flex;flex-direction:column;width:34vw;height:min(82vh,760px);padding:0;transform:translate3d(calc((1 - var(--story-progress)) * 52px),-50%,0) scale(calc(.955 + var(--story-progress) * .045));opacity:clamp(0,calc((var(--story-progress) - .42) * 2.2),1);pointer-events:auto}
.replay-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:10px}
.replay-heading p{margin:0;color:var(--blue);font-size:11px;font-weight:800}
.replay-heading>span{color:#8b8e94;font-size:10px;font-weight:700}
.replay-panel .driver-tabs{margin-bottom:10px}
.replay-panel .driver-tabs button{flex:1;min-width:0}
.replay-panel .decision{min-height:0;padding:18px 0 0;border:0;overflow:auto}
.replay-panel .decision>p{margin:18px 0;font-size:13px;line-height:1.65}
.replay-panel .decision dl div{padding:11px}
.replay-panel .candidates{margin-top:16px}
.replay-panel .candidates>div{padding:9px 0}
.replay-panel .empty{margin-top:16px}
.replay-panel .timeline{margin-top:auto;padding-top:16px}
.replay-panel .timeline button{min-width:76px;height:42px}
.replay-panel .timeline input{cursor:pointer}
.app{padding-top:78px}
.metrics{margin-top:0}
.preferences{padding-top:0}
.strategies{padding-top:72px}
.rules,.strategy-table{border-top:0}

@media(max-width:1080px){
  .home-globe{left:3vw;width:57vw}
  .replay-panel{right:3vw;width:34vw}
  .replay-panel .candidates>div:nth-child(n+4){display:none}
}

@media(max-width:820px){
  .story{height:auto}
  .story-sticky{position:relative;height:auto;min-height:0;padding:100px 16px 48px;overflow:visible}
  .home-copy{position:relative;top:auto;left:auto;width:100%;margin:0 auto 32px;transform:none;opacity:1}
  .home-copy h1{font-size:38px;white-space:normal}
  .scroll-hint{display:none}
  .home-globe{position:relative;top:auto;left:auto;width:100%;height:min(62vh,520px);margin:0;transform:none;clip-path:inset(0 round 14px);box-shadow:none;contain:layout paint}
  .home-globe .mapboxgl-canvas-container{transform:none}
  .home-globe .map-meta{opacity:1;transform:none}
  .replay-panel{position:relative;top:auto;right:auto;width:100%;height:auto;margin-top:28px;padding-bottom:0;transform:none;opacity:1}
  .replay-panel .decision{overflow:visible}
  .replay-panel .timeline{margin-top:8px}
}

@media(max-width:520px){
  .story-sticky{padding-top:88px}
  .home-copy h1{font-size:33px}
  .home-copy>img{width:48px;height:48px}
  .home-globe{height:420px}
  .map-meta{right:12px;bottom:12px;left:12px;gap:12px}
  .replay-heading{align-items:center}
}

@media(prefers-reduced-motion:reduce){
  .home-copy,.home-globe,.home-globe .map-meta,.replay-panel{will-change:auto}
}
</style>
