# -*- coding: utf-8 -*-
"""dashboard：把 snapshot.json 渲染成**单文件 HTML 看板**。

- 纯内联 CSS / JS，零外部请求、零 CDN、零字体外链（断网也能双击打开）。
- 下拉选择房间 → 大号显示剩余电量 + 低电状态；表格按**楼栋分组**、按楼号/房间号自然排序
  （13号楼 → 16号楼 → 23号楼A座 → 23号楼B座）。
- 宿舍名统一为班级站规范名 `{楼号}号楼{座}{房间号}`，由 roomverify 派生；
  只消费 snapshot 里的房间数据（label/building/room/roomverify/quantity/unit/low），
  **不含 occupant 等个人信息**。

本文件是本地化新增代码（非 jialiangh 原项目），MIT 许可，见 NOTICE。
"""
from __future__ import annotations

import html as _html
import json

import util


def _json_for_script(data):
    """嵌进 <script> 的 JSON：转义 </ 防止提前闭合标签。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _num(value, digits=2):
    try:
        return "%.*f" % (digits, float(value))
    except (TypeError, ValueError):
        return "--"


def build_payload(snapshot):
    """只挑看板需要的字段（白名单），统一规范名并按楼栋/房间排序。"""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    rooms = []
    for item in snapshot.get("rooms") or []:
        if not isinstance(item, dict):
            continue
        roomverify = str(item.get("roomverify") or "")
        canonical = util.canonical_room(roomverify)
        rooms.append({
            "label": canonical["label"] if canonical
                     else str(item.get("label") or roomverify),
            "building": canonical["building"] if canonical
                        else str(item.get("building") or ""),
            "room": canonical["room"] if canonical
                    else str(item.get("room") or ""),
            "roomverify": roomverify,
            "quantity": item.get("quantity"),
            "unit": str(item.get("unit") or "度"),
            "low": bool(item.get("low")),
        })
    rooms.sort(key=util.room_sort_key)
    threshold = snapshot.get("low_threshold")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        threshold = 30.0
    return {
        "generated_at": str(snapshot.get("generated_at") or ""),
        "payproid": str(snapshot.get("payproid") or ""),
        "payproname": str(snapshot.get("payproname") or ""),
        "low_threshold": threshold,
        "rooms": rooms,
    }


_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>班级宿舍电量看板</title>
<style>
:root{
  --bg:#f7f8f8; --card:#ffffff; --ink:#243230; --muted:#6b7c78;
  --teal:#4e9082; --teal-d:#3d7468; --sand:#b98f63;
  --ok:#2f8f6b; --ok-bg:#e8f5ef; --low:#c2542e; --low-bg:#fdeee7;
  --line:#e6ebea;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",
              "PingFang SC","Hiragino Sans GB",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:880px;margin:0 auto;padding:28px 18px 48px}
header h1{font-size:22px;margin:0 0 6px;letter-spacing:.5px}
header .meta{margin:0;color:var(--muted);font-size:13px;line-height:1.7}
.card{
  background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:22px;margin-top:18px;box-shadow:0 1px 2px rgba(36,50,48,.04);
}
label.pick{display:block;font-size:13px;color:var(--muted);margin-bottom:8px}
select{
  width:100%;padding:11px 12px;border-radius:12px;border:1px solid var(--line);
  background:#fff;color:var(--ink);font-size:15px;outline:none;
}
select:focus{border-color:var(--teal)}
.big{display:flex;align-items:baseline;gap:8px;margin:18px 0 4px}
.big .num{font-size:52px;font-weight:700;line-height:1;letter-spacing:-1px}
.big .unit{font-size:18px;color:var(--muted)}
.big.low .num{color:var(--low)}
.big.ok .num{color:var(--teal)}
.status{display:inline-block;margin:6px 0 0;padding:5px 12px;border-radius:999px;
  font-size:13px;font-weight:600}
.status.ok{background:var(--ok-bg);color:var(--ok)}
.status.low{background:var(--low-bg);color:var(--low)}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;
  color:var(--muted);margin:10px 0 0;word-break:break-all}
.toolbar{display:flex;align-items:center;justify-content:space-between;
  gap:12px;flex-wrap:wrap;margin-bottom:10px}
.toolbar h2{font-size:16px;margin:0}
.toolbar .filter{font-size:13px;color:var(--muted);display:flex;
  align-items:center;gap:6px;cursor:pointer;user-select:none}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left}
th{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.3px}
tbody tr{cursor:pointer}
tbody tr:hover{background:#f3f7f6}
tbody tr.selected{background:#eef5f3}
tbody tr.group{cursor:default}
tbody tr.group:hover{background:transparent}
tbody tr.group td{
  background:#f3f7f6;color:var(--teal-d);font-weight:700;font-size:13px;
  letter-spacing:.4px;padding:8px;border-bottom:1px solid var(--line);
}
tbody tr.group .count{color:var(--muted);font-weight:400;font-size:12px;margin-left:6px}
td.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:12px;
  font-weight:600}
.badge.ok{background:var(--ok-bg);color:var(--ok)}
.badge.low{background:var(--low-bg);color:var(--low)}
.foot{margin-top:20px;color:var(--muted);font-size:12px;line-height:1.8}
.empty{padding:28px;text-align:center;color:var(--muted)}
@media (max-width:520px){
  .wrap{padding:18px 12px 36px}
  .big .num{font-size:42px}
  th,td{padding:9px 6px}
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>班级宿舍电量看板</h1>
  <p class="meta">数据时间：__GENERATED_AT__ · 缴费项目：__PAYPRO__<br>
  低电阈值：__THRESHOLD__ 度 · 共 __COUNT__ 间 · 低电 __LOW_COUNT__ 间</p>
</header>

<section class="card">
  <label class="pick" for="roomSelect">选择房间</label>
  <select id="roomSelect" __SELECT_DISABLED__></select>
  <div class="big" id="bigBox">
    <span class="num" id="quantity">--</span>
    <span class="unit" id="unit">度</span>
  </div>
  <p class="status" id="status">--</p>
  <p class="mono" id="roomverify"></p>
</section>

<section class="card">
  <div class="toolbar">
    <h2>全部房间（按楼栋）</h2>
    <label class="filter"><input type="checkbox" id="onlyLow"> 只看低电</label>
  </div>
  <table>
    <thead>
      <tr><th>房间</th><th>roomverify</th><th style="text-align:right">剩余电量</th><th>状态</th></tr>
    </thead>
    <tbody id="roomTable"></tbody>
  </table>
  <div class="empty" id="emptyTip" style="display:none">暂无数据</div>
</section>

<p class="foot">非官方接口，仅供班级内部查看；数据来自完美校园「缴费 → 用电支出」的只读查询，
可能因学校/厂商调整而失效。本页面为单文件离线页面，不向任何服务器发送数据。</p>
</div>

<script>
const DATA = __DATA__;

function byId(id){ return document.getElementById(id); }
function fmt(value){
  if (value === null || value === undefined || value === "" || isNaN(Number(value))) return "--";
  return Number(value).toFixed(2);
}
function escapeHtml(text){
  return String(text == null ? "" : text).replace(/[&<>"']/g, function(ch){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
  });
}
function isLow(room){ return !!room.low; }

function groupByBuilding(rooms){
  const groups = [];
  const map = {};
  rooms.forEach(function(room, index){
    const key = room.building || "其他";
    if (!map[key]) { map[key] = {name:key, items:[]}; groups.push(map[key]); }
    map[key].items.push({room: room, index: index});
  });
  return groups;
}

function renderRoom(index){
  const rooms = DATA.rooms;
  const room = rooms[index];
  if (!room) return;
  const lowBox = byId("bigBox");
  byId("quantity").textContent = fmt(room.quantity);
  byId("unit").textContent = room.unit || "度";
  byId("roomverify").textContent = room.roomverify || "";
  byId("status").textContent = isLow(room) ? "电量偏低，建议尽快充值" : "电量正常";
  byId("status").className = "status " + (isLow(room) ? "low" : "ok");
  lowBox.className = "big " + (isLow(room) ? "low" : "ok");
  const select = byId("roomSelect");
  if (select.value !== String(index)) select.value = String(index);
  document.querySelectorAll("#roomTable tr[data-i]").forEach(function(row){
    row.classList.toggle("selected", row.getAttribute("data-i") === String(index));
  });
}

function applyFilter(){
  const onlyLow = byId("onlyLow").checked;
  const rows = Array.prototype.slice.call(
    document.querySelectorAll("#roomTable tr"));
  rows.forEach(function(row){
    if (row.classList.contains("group")) return;
    const low = row.getAttribute("data-low") === "1";
    row.style.display = (onlyLow && !low) ? "none" : "";
  });
  let currentGroup = null;
  const groups = [];
  rows.forEach(function(row){
    if (row.classList.contains("group")) {
      currentGroup = row;
      currentGroup.setAttribute("data-visible", "0");
      groups.push(currentGroup);
      return;
    }
    if (currentGroup && row.style.display !== "none") {
      currentGroup.setAttribute("data-visible", "1");
    }
  });
  groups.forEach(function(group){
    group.style.display = group.getAttribute("data-visible") === "1" ? "" : "none";
  });
}

function build(){
  const rooms = DATA.rooms || [];
  const select = byId("roomSelect");
  const body = byId("roomTable");
  byId("emptyTip").style.display = rooms.length ? "none" : "block";
  if (!rooms.length){
    select.disabled = true;
    return;
  }
  groupByBuilding(rooms).forEach(function(group){
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.name;
    group.items.forEach(function(entry){
      const option = document.createElement("option");
      option.value = String(entry.index);
      option.textContent = entry.room.label || entry.room.roomverify;
      optgroup.appendChild(option);
    });
    select.appendChild(optgroup);

    const groupRow = document.createElement("tr");
    groupRow.className = "group";
    groupRow.innerHTML = "<td colspan='4'>" + escapeHtml(group.name) +
      "<span class='count'>" + group.items.length + " 间</span></td>";
    body.appendChild(groupRow);

    group.items.forEach(function(entry){
      const room = entry.room;
      const row = document.createElement("tr");
      row.setAttribute("data-i", String(entry.index));
      row.setAttribute("data-low", isLow(room) ? "1" : "0");
      const badgeClass = isLow(room) ? "low" : "ok";
      const badgeText = isLow(room) ? "低电" : "正常";
      row.innerHTML =
        "<td>" + escapeHtml(room.label || room.roomverify) + "</td>" +
        "<td class='mono' style='margin:0'>" + escapeHtml(room.roomverify) + "</td>" +
        "<td class='num'>" + escapeHtml(fmt(room.quantity)) + " " +
        escapeHtml(room.unit || "度") + "</td>" +
        "<td><span class='badge " + badgeClass + "'>" + badgeText + "</span></td>";
      row.addEventListener("click", function(){ renderRoom(entry.index); });
      body.appendChild(row);
    });
  });
  select.addEventListener("change", function(){ renderRoom(Number(select.value)); });
  byId("onlyLow").addEventListener("change", applyFilter);

  let initial = 0;
  for (let i = 0; i < rooms.length; i++){ if (isLow(rooms[i])) { initial = i; break; } }
  renderRoom(initial);
}

document.addEventListener("DOMContentLoaded", build);
</script>
</body>
</html>
"""


def render(snapshot):
    """snapshot dict -> 单文件 HTML 字符串。"""
    payload = build_payload(snapshot)
    rooms = payload["rooms"]
    low_count = sum(1 for room in rooms if room["low"])
    data_json = _json_for_script(payload)
    return (_HTML_HEAD
            .replace("__GENERATED_AT__", _html.escape(payload["generated_at"] or "未知"))
            .replace("__PAYPRO__", _html.escape(payload["payproname"] or "用电支出"))
            .replace("__THRESHOLD__", _num(payload["low_threshold"], 0))
            .replace("__COUNT__", str(len(rooms)))
            .replace("__LOW_COUNT__", str(low_count))
            .replace("__SELECT_DISABLED__", "" if rooms else "disabled")
            .replace("__DATA__", data_json))
