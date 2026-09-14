#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dashboard.py
====================
อ่าน schedule_data.json (สร้างจาก consolidate_schedule.py) แล้วประกอบเป็น
หน้า dashboard.html แบบ self-contained หนึ่งไฟล์ (ปฏิทิน + กราฟสรุปสายเรือ +
ตารางรายละเอียด ที่กรอง/เรียงลำดับได้)

วิธีใช้:
    python consolidate_schedule.py
    python build_dashboard.py
"""

import json
from pathlib import Path

FOLDER = Path(__file__).parent

HTML_TEMPLATE = r"""<title>BKK/LCB → HCMC Sailing Board</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

  :root{
    color-scheme: light;
    --page:        #f9f9f7;
    --surface:     #fcfcfb;
    --surface-2:   #f1efe9;
    --ink:         #171614;
    --ink-2:       #52514e;
    --muted:       #898781;
    --grid:        #e1e0d9;
    --baseline:    #c3c2b7;
    --border:      rgba(11,11,11,0.10);
    --accent:      #4a3aa7;
    --accent-ink:  #ffffff;
    --accent-soft: #ece9fb;
    --good:        #0ca30c;
    --cat-1: #2a78d6; --cat-2: #eb6834; --cat-3: #1baf7a; --cat-4: #eda100;
    --cat-5: #e87ba4; --cat-6: #008300; --cat-7: #4a3aa7; --cat-8: #e34948;
    --cat-other: #9c9a92;
    --today-ring:  #e34948;
    --shadow: 0 1px 2px rgba(11,11,11,0.06), 0 6px 20px -8px rgba(11,11,11,0.12);
  }
  @media (prefers-color-scheme: dark){
    :root:not([data-theme="light"]){
      color-scheme: dark;
      --page:        #0d0d0d;
      --surface:     #1a1a19;
      --surface-2:   #232320;
      --ink:         #ffffff;
      --ink-2:       #c3c2b7;
      --muted:       #898781;
      --grid:        #2c2c2a;
      --baseline:    #383835;
      --border:      rgba(255,255,255,0.10);
      --accent:      #9085e9;
      --accent-ink:  #16142b;
      --accent-soft: #26224a;
      --good:        #0ca30c;
      --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70; --cat-4: #c98500;
      --cat-5: #d55181; --cat-6: #008300; --cat-7: #9085e9; --cat-8: #e66767;
      --cat-other: #6f6d66;
      --today-ring:  #e66767;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 10px 30px -10px rgba(0,0,0,0.5);
    }
  }
  :root[data-theme="dark"]{
    color-scheme: dark;
    --page:        #0d0d0d;
    --surface:     #1a1a19;
    --surface-2:   #232320;
    --ink:         #ffffff;
    --ink-2:       #c3c2b7;
    --muted:       #898781;
    --grid:        #2c2c2a;
    --baseline:    #383835;
    --border:      rgba(255,255,255,0.10);
    --accent:      #9085e9;
    --accent-ink:  #16142b;
    --accent-soft: #26224a;
    --good:        #0ca30c;
    --cat-1: #3987e5; --cat-2: #d95926; --cat-3: #199e70; --cat-4: #c98500;
    --cat-5: #d55181; --cat-6: #008300; --cat-7: #9085e9; --cat-8: #e66767;
    --cat-other: #6f6d66;
    --today-ring:  #e66767;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 10px 30px -10px rgba(0,0,0,0.5);
  }

  *{ box-sizing:border-box; }
  body{
    background:var(--page);
    color:var(--ink);
    font-family:"Noto Sans Thai","Segoe UI",system-ui,sans-serif;
    font-size:14px;
    line-height:1.5;
  }
  .wrap{ max-width:1180px; margin:0 auto; padding:28px 20px 64px; }
  .mono{ font-family:"JetBrains Mono",ui-monospace,monospace; font-variant-numeric: tabular-nums; }

  header.top{ display:flex; flex-wrap:wrap; gap:16px; justify-content:space-between; align-items:flex-end; margin-bottom:22px; }
  header.top h1{ font-size:24px; font-weight:800; letter-spacing:-0.01em; margin:0 0 6px; text-wrap:balance; }
  header.top .route{ display:flex; align-items:center; gap:8px; color:var(--ink-2); font-size:13.5px; }
  header.top .route b{ color:var(--ink); font-weight:600; }
  .arrow{ color:var(--accent); font-weight:700; }
  .meta{ text-align:right; font-size:12px; color:var(--muted); }
  .meta .pill{ display:inline-flex; align-items:center; gap:6px; background:var(--surface-2); border:1px solid var(--border); color:var(--ink-2); padding:4px 10px; border-radius:99px; font-size:11.5px; margin-top:6px; }
  .pill.warn{ color:#a35400; border-color:rgba(211,138,0,0.35); background:rgba(250,178,25,0.12); }
  @media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) .pill.warn{ color:#fab219; } }
  :root[data-theme="dark"] .pill.warn{ color:#fab219; }
  .pill .dot{ width:6px; height:6px; border-radius:50%; background:currentColor; }

  .kpis{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:26px; }
  .kpi{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:14px 16px; box-shadow:var(--shadow); }
  .kpi .label{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:6px; }
  .kpi .value{ font-size:24px; font-weight:800; letter-spacing:-0.01em; }
  .kpi .sub{ font-size:12px; color:var(--ink-2); margin-top:2px; }

  section{ margin-bottom:30px; }
  section > h2{ font-size:15px; font-weight:700; margin:0 0 4px; display:flex; align-items:center; gap:8px; }
  .month-badge{ font-size:11.5px; font-weight:600; color:var(--accent); background:var(--accent-soft); border:1px solid var(--accent); padding:2px 10px; border-radius:99px; }
  section > .lead{ font-size:12.5px; color:var(--muted); margin:0 0 14px; }

  .panel{ background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:18px; box-shadow:var(--shadow); }

  .filters{ display:flex; flex-wrap:wrap; gap:18px; align-items:flex-start; margin-bottom:16px; }
  .filter-group{ display:flex; flex-direction:column; gap:6px; }
  .filter-group .fg-label{ font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
  .chips{ display:flex; flex-wrap:wrap; gap:6px; }
  .chip{ appearance:none; border:1px solid var(--border); background:var(--surface-2); color:var(--ink-2); font:inherit; font-size:12.5px; padding:6px 12px; border-radius:99px; cursor:pointer; display:inline-flex; align-items:center; gap:7px; transition:background .15s,color .15s,border-color .15s; }
  .chip:hover{ border-color:var(--accent); }
  .chip.active{ background:var(--accent-soft); color:var(--accent); border-color:var(--accent); font-weight:600; }
  .chip .swatch{ width:8px; height:8px; border-radius:50%; box-shadow:0 0 0 1px var(--border); }
  .chip .n{ opacity:.75; font-variant-numeric: tabular-nums; }
  .reset-btn{ appearance:none; border:1px dashed var(--baseline); background:transparent; color:var(--muted); font:inherit; font-size:12px; padding:6px 12px; border-radius:99px; cursor:pointer; }
  .reset-btn:hover{ color:var(--ink); border-color:var(--ink-2); }

  /* Calendar */
  .month-tabs{ display:flex; align-items:center; gap:6px; margin-bottom:14px; }
  .month-tabs .nav-btn{ appearance:none; border:1px solid var(--border); background:var(--surface-2); color:var(--ink-2); width:30px; height:30px; border-radius:8px; cursor:pointer; font-size:14px; line-height:1; display:flex; align-items:center; justify-content:center; flex:none; }
  .month-tabs .nav-btn:hover{ border-color:var(--accent); color:var(--accent); }
  .month-tabs .nav-btn:disabled{ opacity:.35; cursor:default; }
  .month-tabs .nav-btn:disabled:hover{ border-color:var(--border); color:var(--ink-2); }
  .month-tabs .tabs{ display:flex; flex-wrap:wrap; gap:6px; flex:1; }
  .month-tab{ appearance:none; border:1px solid var(--border); background:var(--surface-2); color:var(--ink-2); font:inherit; font-size:12.5px; padding:6px 14px; border-radius:99px; cursor:pointer; display:inline-flex; align-items:center; gap:7px; }
  .month-tab:hover{ border-color:var(--accent); }
  .month-tab.active{ background:var(--accent-soft); color:var(--accent); border-color:var(--accent); font-weight:600; }
  .month-tab .n{ opacity:.75; font-variant-numeric: tabular-nums; }
  .cal-grid{ display:grid; grid-template-columns:1fr; gap:16px; }
  .month{ background:var(--surface-2); border:1px solid var(--border); border-radius:10px; padding:12px; }
  .month h3{ margin:0 0 10px; font-size:13px; font-weight:700; padding:0 4px; }
  .dow{ display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin-bottom:4px; }
  .dow span{ font-size:10px; text-align:center; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  .days{ display:grid; grid-template-columns:repeat(7,1fr); gap:4px; }
  .day{ min-height:88px; background:var(--surface); border:1px solid var(--border); border-radius:7px; padding:5px 5px 6px; display:flex; flex-direction:column; gap:3px; }
  .day.empty{ background:transparent; border-color:transparent; }
  .day.today{ box-shadow:inset 0 0 0 1.5px var(--today-ring); }
  .day .num{ font-size:10.5px; color:var(--muted); font-variant-numeric: tabular-nums; padding:0 2px; }
  .day.has .num{ color:var(--ink); font-weight:600; }
  .day .evts{ display:flex; flex-direction:column; gap:2px; overflow:hidden; }
  .evt{ font-size:10.5px; line-height:1.3; padding:2px 5px; border-radius:4px; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:default; }
  .evt.o-bkk{ opacity:1; }
  .evt.o-lcb{ opacity:.82; }
  .day .more{ font-size:9px; color:var(--muted); padding:0 4px; }

  .legend{ display:flex; flex-wrap:wrap; gap:14px; margin-top:14px; font-size:11.5px; color:var(--ink-2); }
  .legend .item{ display:flex; align-items:center; gap:6px; }
  .legend .sw{ width:10px; height:10px; border-radius:3px; box-shadow:0 0 0 1px var(--border); }
  .legend .origin-note{ display:flex; align-items:center; gap:5px; }

  /* Line breakdown */
  .lines{ display:flex; flex-direction:column; gap:10px; }
  .line-row{ display:grid; grid-template-columns:180px 1fr 46px; gap:12px; align-items:center; }
  .line-row .name{ display:flex; align-items:center; gap:8px; font-weight:600; font-size:13px; }
  .line-row .name .sw{ width:10px; height:10px; border-radius:3px; flex:none; box-shadow:0 0 0 1px var(--border); }
  .bar-track{ background:var(--surface-2); border-radius:6px; height:20px; overflow:hidden; position:relative; }
  .bar-fill{ height:100%; border-radius:6px; }
  .line-row .count{ text-align:right; font-weight:700; font-variant-numeric: tabular-nums; }
  .vessel-lists{ margin-top:18px; display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }
  .vessel-card{ background:var(--surface-2); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }
  .vessel-card h4{ margin:0 0 8px; font-size:12px; display:flex; align-items:center; gap:7px; }
  .vessel-card h4 .sw{ width:9px; height:9px; border-radius:3px; box-shadow:0 0 0 1px var(--border); }
  .vessel-card ul{ margin:0; padding:0; list-style:none; display:flex; flex-direction:column; gap:4px; max-height:200px; overflow-y:auto; }
  .vessel-card li{ font-size:12px; color:var(--ink-2); display:flex; justify-content:space-between; gap:8px; }
  .vessel-card li .vn{ color:var(--ink); }
  .vessel-card li .vc{ font-variant-numeric: tabular-nums; color:var(--muted); }

  /* Table */
  .table-wrap{ overflow-x:auto; border:1px solid var(--border); border-radius:12px; }
  table{ border-collapse:collapse; width:100%; min-width:840px; font-size:12.5px; background:var(--surface); }
  thead th{ position:sticky; top:0; background:var(--surface-2); text-align:left; font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); padding:9px 12px; border-bottom:1px solid var(--border); cursor:pointer; user-select:none; white-space:nowrap; }
  thead th:hover{ color:var(--ink); }
  thead th.sorted{ color:var(--accent); }
  thead th .arrow{ font-size:9px; margin-left:3px; }
  tbody td{ padding:8px 12px; border-bottom:1px solid var(--grid); vertical-align:middle; white-space:nowrap; }
  tbody tr:last-child td{ border-bottom:none; }
  tbody tr:hover{ background:var(--surface-2); }
  .origin-tag{ display:inline-flex; align-items:center; gap:5px; font-size:11.5px; color:var(--ink-2); }
  .origin-tag .sw{ width:6px; height:6px; border-radius:50%; }
  .line-tag{ display:inline-flex; align-items:center; gap:6px; font-weight:600; font-size:12px; }
  .line-tag .sw{ width:8px; height:8px; border-radius:3px; box-shadow:0 0 0 1px var(--border); }
  .src-chip{ display:inline-block; font-size:10px; padding:2px 7px; border-radius:99px; background:var(--surface-2); color:var(--ink-2); border:1px solid var(--border); margin-right:3px; }
  .merged-badge{ display:inline-flex; align-items:center; gap:4px; font-size:10.5px; color:var(--good); background:rgba(12,163,12,0.10); border:1px solid rgba(12,163,12,0.25); padding:2px 7px; border-radius:99px; margin-left:6px; }
  .rowcount{ font-size:12px; color:var(--muted); margin:8px 2px 0; }

  footer{ margin-top:34px; padding-top:18px; border-top:1px solid var(--border); font-size:11.5px; color:var(--muted); display:flex; flex-direction:column; gap:6px; }
  footer a{ color:var(--ink-2); }
  .src-list{ display:flex; flex-wrap:wrap; gap:8px 18px; }
  .src-list span b{ color:var(--ink-2); font-weight:600; }
</style>

<div class="wrap">

  <header class="top">
    <div>
      <h1>ตารางเรือ Bangkok / Laem Chabang <span class="arrow">&rarr;</span> Ho Chi Minh City</h1>
      <div class="route">ช่วงที่พบข้อมูล: <b id="dateRangeLabel">-</b> &nbsp;&middot;&nbsp; รวบรวมจาก <b id="sourceCountLabel">-</b> แหล่งข้อมูล แล้วรวมเที่ยวเรือที่ซ้ำกันให้เหลือรายการเดียว</div>
    </div>
    <div class="meta">
      อัปเดตล่าสุด 2026-09-14 (Asia/Bangkok)
      <div id="warnPills"></div>
    </div>
  </header>

  <div class="kpis" id="kpiRow"></div>

  <section>
    <h2>ปฏิทินเที่ยวเรือ</h2>
    <p class="lead">แต่ละแท่งสีคือ 1 เที่ยวเรือในวันนั้น (สีตามสายเรือ) &mdash; ชี้ค้างเพื่อดูชื่อเรือ/เที่ยว/ต้นทางเต็ม</p>
    <div class="panel">
      <div class="filters">
        <div class="filter-group">
          <span class="fg-label">ต้นทาง</span>
          <div class="chips" id="originChips"></div>
        </div>
        <div class="filter-group">
          <span class="fg-label">สายเรือ</span>
          <div class="chips" id="lineChips"></div>
        </div>
        <div class="filter-group">
          <span class="fg-label">&nbsp;</span>
          <button class="reset-btn" id="resetBtn">ล้างตัวกรอง</button>
        </div>
      </div>
      <div class="month-tabs" id="monthTabs"></div>
      <div class="cal-grid" id="calGrid"></div>
      <div class="legend" id="calLegend"></div>
    </div>
  </section>

  <section>
    <h2>แจกแจงตามสายเรือ <span class="month-badge" id="lineBreakdownMonth"></span></h2>
    <p class="lead">จำนวนเที่ยวเรือ (หลังรวมรายการซ้ำ) แยกตามสายเรือที่ให้บริการเส้นทางนี้ &mdash; เปลี่ยนเดือนได้จากแท็บในปฏิทินด้านบน</p>
    <div class="panel">
      <div class="lines" id="lineBars"></div>
      <div class="vessel-lists" id="vesselLists"></div>
    </div>
  </section>

  <section>
    <h2>รายละเอียดเที่ยวเรือ <span class="month-badge" id="tableMonth"></span></h2>
    <p class="lead">คลิกหัวคอลัมน์เพื่อเรียงลำดับ &mdash; ใช้ตัวกรองต้นทาง/สายเรือ/เดือนด้านบนร่วมกับตารางนี้ได้</p>
    <div class="table-wrap">
      <table id="dataTable">
        <thead>
          <tr>
            <th data-key="etd">วันออก (ETD) <span class="arrow"></span></th>
            <th data-key="origin">ต้นทาง <span class="arrow"></span></th>
            <th data-key="vessel">เรือ / เที่ยว <span class="arrow"></span></th>
            <th data-key="line">สายเรือ <span class="arrow"></span></th>
            <th data-key="eta">วันถึง (ETA) <span class="arrow"></span></th>
            <th data-key="transit">ระยะเวลาเดินทาง <span class="arrow"></span></th>
            <th>แหล่งข้อมูล</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
    <div class="rowcount" id="rowCount"></div>
  </section>

  <footer>
    <div class="src-list" id="srcList"></div>
    <div>ตารางนี้เป็นข้อมูลอ้างอิงจากเว็บไซต์สายเรือ/ตัวแทน/เว็บตรวจสอบตารางเรือ (vessel schedule checker) ของสายเรือพันธมิตร ณ เวลาที่ดึงข้อมูล อาจมีการเปลี่ยนแปลง กรุณายืนยันกับตัวแทนเรือ/สายเรือก่อนทำการจองจริง "สายเรือ" ในตารางนี้จัดกลุ่มตามแหล่งข้อมูล/เว็บไซต์ที่พบเที่ยวเรือนั้น (9 แหล่งข้อมูลตามสคริปต์ที่ใช้ดึงข้อมูล) ไม่ใช่ผู้ให้บริการเรือจริงเสมอไป เนื่องจากหลายเว็บแสดงเที่ยวเรือของสายพันธมิตร (VSA) ปะปนกัน</div>
  </footer>
</div>

<script id="schedule-data" type="application/json">__SCHEDULE_JSON__</script>
<script>
(function(){
  "use strict";
  var raw = JSON.parse(document.getElementById('schedule-data').textContent);
  var sailings = raw.sailings;
  var sourcesStatus = raw.sources_status || {};

  // ---------- Source status (header warn pills + footer) ----------
  var okSources = [], badSources = [];
  Object.keys(sourcesStatus).forEach(function(name){
    var status = sourcesStatus[name];
    if(status.indexOf('ok') === 0){ okSources.push({name:name, status:status}); }
    else if(status.indexOf('blocked') === 0){ badSources.push({name:name, status:status}); }
  });
  document.getElementById('sourceCountLabel').textContent = okSources.length;
  document.getElementById('warnPills').innerHTML = badSources.map(function(b){
    return '<span class="pill warn"><span class="dot"></span> '+b.name+': '+b.status+'</span>';
  }).join(' ');
  document.getElementById('srcList').innerHTML = Object.keys(sourcesStatus).map(function(name){
    return '<span><b>'+name+'</b> &mdash; '+sourcesStatus[name]+'</span>';
  }).join('');

  function fmtDate(iso){
    if(!iso) return "-";
    var d = new Date(iso+"T00:00:00");
    var days = ["อา","จ","อ","พ","พฤ","ศ","ส"];
    return d.getDate() + " " + ["ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค.","ก.ย.","ต.ค.","พ.ย.","ธ.ค."][d.getMonth()] + " (" + days[d.getDay()] + ")";
  }
  function transitDays(etd, eta){
    if(!etd || !eta) return "-";
    var a = new Date(etd+"T00:00:00"), b = new Date(eta+"T00:00:00");
    var diff = Math.round((b-a)/86400000);
    return diff >= 0 ? diff + " วัน" : "-";
  }

  // ---------- KPI ----------
  var etds = sailings.map(function(s){return s.etd;}).sort();
  var uniqueVessels = new Set(sailings.map(function(s){return s.vessel;}));
  var byOrigin = {};
  sailings.forEach(function(s){ byOrigin[s.origin] = (byOrigin[s.origin]||0)+1; });
  var mergedCount = sailings.filter(function(s){ return s.duplicate_count>1; }).length;

  document.getElementById('dateRangeLabel').textContent = fmtDate(etds[0]) + '  →  ' + fmtDate(etds[etds.length-1]);

  var uniqueLinesCount = new Set(sailings.map(function(s){return s.line;})).size;
  var kpis = [
    {label:"เที่ยวเรือทั้งหมด", value: sailings.length, sub:"หลังรวมรายการซ้ำจากทุกแหล่ง"},
    {label:"เรือที่พบ (ไม่ซ้ำ)", value: uniqueVessels.size, sub:"ลำเรือต่างกันที่วิ่งเส้นทางนี้"},
    {label:"สายเรือที่พบ", value: uniqueLinesCount, sub:"กลุ่มสายเรือ/แหล่งข้อมูล"},
    {label:"จาก Bangkok", value: byOrigin["Bangkok"]||0, sub:"เที่ยวเรือ"},
    {label:"จาก Laem Chabang", value: byOrigin["Laem Chabang"]||0, sub:"เที่ยวเรือ"},
    {label:"รวมรายการซ้ำ", value: mergedCount, sub:"เที่ยวที่พบซ้ำมากกว่า 1 แหล่ง"}
  ];
  document.getElementById('kpiRow').innerHTML = kpis.map(function(k){
    return '<div class="kpi"><div class="label">'+k.label+'</div><div class="value mono">'+k.value+'</div><div class="sub">'+k.sub+'</div></div>';
  }).join('');

  // ---------- Filters ----------
  var state = { origin: "ALL", lines: new Set(sailings.map(function(s){return s.line;})) };
  var allLines = Array.from(new Set(sailings.map(function(s){return s.line;})))
    .sort(function(a,b){ return sailings.filter(function(s){return s.line===b;}).length - sailings.filter(function(s){return s.line===a;}).length; });
  var origins = Array.from(new Set(sailings.map(function(s){return s.origin;})));

  // สีตามสายเรือ: เรียงลำดับตามจำนวนเที่ยว (มาก -> น้อย) จากข้อมูลทั้งหมด (ไม่ใช่ข้อมูลที่กรองแล้ว)
  // แล้วไล่สีตามลำดับคงที่ของชุดสี 8 สี ถ้าเกิน 8 สายเรือ ที่เหลือใช้สีเทากลาง ("อื่นๆ")
  // เพื่อไม่ให้สีชนกันตอนกรอง (fixed categorical order, never cycled)
  var PALETTE = ["var(--cat-1)","var(--cat-2)","var(--cat-3)","var(--cat-4)","var(--cat-5)","var(--cat-6)","var(--cat-7)","var(--cat-8)"];
  var LINE_COLOR = {};
  allLines.forEach(function(l, i){ LINE_COLOR[l] = i < PALETTE.length ? PALETTE[i] : "var(--cat-other)"; });
  function colorFor(line){ return LINE_COLOR[line] || "var(--cat-other)"; }

  function renderOriginChips(){
    var html = '<button class="chip'+(state.origin==="ALL"?" active":"")+'" data-o="ALL">ทั้งหมด <span class="n">'+sailings.length+'</span></button>';
    origins.forEach(function(o){
      var n = sailings.filter(function(s){return s.origin===o;}).length;
      html += '<button class="chip'+(state.origin===o?" active":"")+'" data-o="'+o+'">'+o+' <span class="n">'+n+'</span></button>';
    });
    document.getElementById('originChips').innerHTML = html;
    Array.prototype.forEach.call(document.querySelectorAll('#originChips .chip'), function(btn){
      btn.addEventListener('click', function(){ state.origin = btn.getAttribute('data-o'); render(); });
    });
  }

  function renderLineChips(){
    var html = allLines.map(function(l){
      var n = sailings.filter(function(s){return s.line===l;}).length;
      var active = state.lines.has(l);
      return '<button class="chip'+(active?" active":"")+'" data-l="'+l.replace(/"/g,'&quot;')+'"><span class="swatch" style="background:'+colorFor(l)+'"></span>'+l+' <span class="n">'+n+'</span></button>';
    }).join('');
    document.getElementById('lineChips').innerHTML = html;
    Array.prototype.forEach.call(document.querySelectorAll('#lineChips .chip'), function(btn){
      btn.addEventListener('click', function(){
        var l = btn.getAttribute('data-l');
        if(state.lines.has(l)){ state.lines.delete(l); } else { state.lines.add(l); }
        render();
      });
    });
  }

  document.getElementById('resetBtn').addEventListener('click', function(){
    state.origin = "ALL"; state.lines = new Set(allLines); render();
  });

  function filtered(){
    return sailings.filter(function(s){
      return (state.origin==="ALL" || s.origin===state.origin) && state.lines.has(s.line);
    });
  }

  // ---------- Calendar ----------
  var MONTHS = [
    {y:2026,m:8,label:"กันยายน 2026"},
    {y:2026,m:9,label:"ตุลาคม 2026"},
    {y:2026,m:10,label:"พฤศจิกายน 2026"},
    {y:2026,m:11,label:"ธันวาคม 2026"}
  ]; // m is 0-indexed
  var TODAY_ISO = "2026-09-14";
  var DOW = ["อา","จ","อ","พ","พฤ","ศ","ส"];

  // เปิดเดือนที่ตรงกับวันนี้เป็นค่าเริ่มต้น (fallback เดือนแรกถ้าไม่พบ)
  state.monthIndex = MONTHS.findIndex(function(mo){
    return mo.y === parseInt(TODAY_ISO.slice(0,4),10) && mo.m === parseInt(TODAY_ISO.slice(5,7),10) - 1;
  });
  if(state.monthIndex < 0) state.monthIndex = 0;

  function monthPrefix(mo){ return mo.y + '-' + String(mo.m+1).padStart(2,'0'); }

  function monthCount(list, mo){
    var prefix = monthPrefix(mo);
    var n = 0;
    for(var i=0;i<list.length;i++){ if(list[i].etd && list[i].etd.indexOf(prefix) === 0) n++; }
    return n;
  }

  function renderMonthTabs(list){
    var tabsHtml = MONTHS.map(function(mo, i){
      var shortLabel = mo.label.replace(' 2026', '');
      return '<button class="month-tab'+(i===state.monthIndex?' active':'')+'" data-mi="'+i+'">'+shortLabel+' <span class="n">'+monthCount(list, mo)+'</span></button>';
    }).join('');
    document.getElementById('monthTabs').innerHTML =
      '<button class="nav-btn" id="prevMonthBtn" '+(state.monthIndex<=0?'disabled':'')+' aria-label="เดือนก่อนหน้า">&lsaquo;</button>' +
      '<div class="tabs">'+tabsHtml+'</div>' +
      '<button class="nav-btn" id="nextMonthBtn" '+(state.monthIndex>=MONTHS.length-1?'disabled':'')+' aria-label="เดือนถัดไป">&rsaquo;</button>';
    var prevBtn = document.getElementById('prevMonthBtn'), nextBtn = document.getElementById('nextMonthBtn');
    prevBtn.addEventListener('click', function(){ if(state.monthIndex>0){ state.monthIndex--; render(); } });
    nextBtn.addEventListener('click', function(){ if(state.monthIndex<MONTHS.length-1){ state.monthIndex++; render(); } });
    Array.prototype.forEach.call(document.querySelectorAll('.month-tab'), function(btn){
      btn.addEventListener('click', function(){ state.monthIndex = parseInt(btn.getAttribute('data-mi'),10); render(); });
    });
  }

  function renderCalendar(list){
    var byDate = {};
    list.forEach(function(s){
      (byDate[s.etd] = byDate[s.etd] || []).push(s);
    });

    var mo = MONTHS[state.monthIndex];
    var first = new Date(mo.y, mo.m, 1);
    var startDow = first.getDay();
    var daysInMonth = new Date(mo.y, mo.m+1, 0).getDate();
    var cells = '';
    for(var i=0;i<startDow;i++){ cells += '<div class="day empty"></div>'; }
    for(var d=1; d<=daysInMonth; d++){
      var iso = mo.y + '-' + String(mo.m+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
      var evts = byDate[iso] || [];
      var isToday = iso === TODAY_ISO;
      var evtHtml = evts.slice(0,4).map(function(e){
        var oc = e.origin === "Bangkok" ? "o-bkk" : "o-lcb";
        var title = e.vessel + ' ' + e.voyage + '  |  ' + e.origin + ' → ' + e.destination + '  |  ' + e.line + (e.duplicate_count>1 ? '  |  ✓ พบซ้ำ '+e.duplicate_count+' แหล่ง' : '');
        return '<div class="evt '+oc+'" style="background:'+colorFor(e.line)+'" title="'+title.replace(/"/g,'&quot;')+'">'+e.vessel+'</div>';
      }).join('');
      var more = evts.length>4 ? '<div class="more">+'+(evts.length-4)+' more</div>' : '';
      cells += '<div class="day'+(evts.length?' has':'')+(isToday?' today':'')+'"><div class="num">'+d+'</div><div class="evts">'+evtHtml+more+'</div></div>';
    }
    var html = '<div class="month"><h3>'+mo.label+'</h3><div class="dow">'+DOW.map(function(x){return '<span>'+x+'</span>';}).join('')+'</div><div class="days">'+cells+'</div></div>';
    document.getElementById('calGrid').innerHTML = html;
    renderMonthTabs(list);

    document.getElementById('calLegend').innerHTML =
      allLines.map(function(l){ return '<span class="item"><span class="sw" style="background:'+colorFor(l)+'"></span>'+l+'</span>'; }).join('') +
      '<span class="item origin-note">&nbsp;&middot;&nbsp; ทึบ = ต้นทาง Bangkok, จาง = ต้นทาง Laem Chabang &nbsp;&middot;&nbsp; กรอบแดง = วันนี้ (14 ก.ย. 2026)</span>';
  }

  // ---------- Line breakdown ----------
  function renderLineBreakdown(list){
    var counts = {};
    list.forEach(function(s){ counts[s.line] = (counts[s.line]||0)+1; });
    var max = Math.max.apply(null, Object.values(counts).concat([1]));
    var total = list.length || 1;

    document.getElementById('lineBars').innerHTML = allLines.map(function(l){
      var n = counts[l] || 0;
      var pct = Math.round(n/total*100);
      var w = Math.round(n/max*100);
      return '<div class="line-row"><div class="name"><span class="sw" style="background:'+colorFor(l)+'"></span>'+l+'</div>' +
             '<div class="bar-track"><div class="bar-fill" style="width:'+w+'%;background:'+colorFor(l)+'"></div></div>' +
             '<div class="count mono">'+n+'</div></div>';
    }).join('');

    var byLineVessels = {};
    list.forEach(function(s){
      byLineVessels[s.line] = byLineVessels[s.line] || {};
      var key = s.vessel + ' ' + s.voyage;
      byLineVessels[s.line][key] = (byLineVessels[s.line][key]||0) + 1;
    });
    document.getElementById('vesselLists').innerHTML = allLines.map(function(l){
      var entries = Object.keys(byLineVessels[l]||{}).sort();
      if(!entries.length) return '';
      var items = entries.map(function(k){
        var n = byLineVessels[l][k];
        return '<li><span class="vn">'+k+'</span><span class="vc mono">&times;'+n+'</span></li>';
      }).join('');
      return '<div class="vessel-card"><h4><span class="sw" style="background:'+colorFor(l)+'"></span>'+l+' &mdash; '+entries.length+' เที่ยว/เที่ยวย่อย</h4><ul>'+items+'</ul></div>';
    }).join('');
  }

  // ---------- Table ----------
  var sortState = { key: "etd", dir: 1 };
  function renderTable(list){
    var sorted = list.slice().sort(function(a,b){
      var ka, kb;
      if(sortState.key === "transit"){
        ka = a.eta && a.etd ? (new Date(a.eta) - new Date(a.etd)) : -1;
        kb = b.eta && b.etd ? (new Date(b.eta) - new Date(b.etd)) : -1;
      } else {
        ka = a[sortState.key] || ""; kb = b[sortState.key] || "";
      }
      if(ka < kb) return -1*sortState.dir;
      if(ka > kb) return 1*sortState.dir;
      return 0;
    });

    document.getElementById('tableBody').innerHTML = sorted.map(function(s){
      var oc = s.origin === "Bangkok" ? "var(--line-sitc)" : "var(--muted)";
      var srcChips = s.sources.map(function(src){ return '<span class="src-chip">'+src.replace(' (forwarder','').replace(')','')+'</span>'; }).join('');
      var merged = s.duplicate_count>1 ? '<span class="merged-badge">&#10003; '+s.duplicate_count+' แหล่ง</span>' : '';
      return '<tr>' +
        '<td class="mono">'+fmtDate(s.etd)+'</td>' +
        '<td><span class="origin-tag"><span class="sw" style="background:'+oc+'"></span>'+s.origin+'</span></td>' +
        '<td><b>'+s.vessel+'</b> <span class="mono" style="color:var(--muted)">'+s.voyage+'</span></td>' +
        '<td><span class="line-tag"><span class="sw" style="background:'+colorFor(s.line)+'"></span>'+s.line+'</span></td>' +
        '<td class="mono">'+fmtDate(s.eta)+'</td>' +
        '<td class="mono">'+transitDays(s.etd, s.eta)+'</td>' +
        '<td>'+srcChips+merged+'</td>' +
      '</tr>';
    }).join('');
    document.getElementById('rowCount').textContent = 'แสดง ' + sorted.length + ' เที่ยวเรือในเดือนนี้ (จากทั้งหมด ' + sailings.length + ' เที่ยวเรือ ก.ย.-ธ.ค. 2026)';
  }

  Array.prototype.forEach.call(document.querySelectorAll('#dataTable thead th[data-key]'), function(th){
    th.addEventListener('click', function(){
      var key = th.getAttribute('data-key');
      if(sortState.key === key){ sortState.dir *= -1; } else { sortState.key = key; sortState.dir = 1; }
      Array.prototype.forEach.call(document.querySelectorAll('#dataTable thead th'), function(x){
        x.classList.remove('sorted');
        var a = x.querySelector('.arrow'); if(a) a.textContent = '';
      });
      th.classList.add('sorted');
      var arrowEl = th.querySelector('.arrow'); if(arrowEl) arrowEl.textContent = sortState.dir===1 ? '↑' : '↓';
      render();
    });
  });

  function render(){
    renderOriginChips();
    renderLineChips();
    var list = filtered();
    var mo = MONTHS[state.monthIndex];
    var prefix = monthPrefix(mo);
    var monthList = list.filter(function(s){ return s.etd && s.etd.indexOf(prefix) === 0; });

    renderCalendar(list);
    renderLineBreakdown(monthList);
    renderTable(monthList);

    document.getElementById('lineBreakdownMonth').textContent = mo.label;
    document.getElementById('tableMonth').textContent = mo.label;
  }

  render();
})();
</script>
"""


def main():
    data_path = FOLDER / "schedule_data.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    schedule_json = json.dumps(data, ensure_ascii=False)
    html = HTML_TEMPLATE.replace("__SCHEDULE_JSON__", schedule_json)
    out_path = FOLDER / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"บันทึกไฟล์: {out_path.name} ({len(html):,} ตัวอักษร)")


if __name__ == "__main__":
    main()
