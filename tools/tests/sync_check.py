# -*- coding: utf-8 -*-
r"""用户数据同步 v6 + 通知已处理同步 专项自检（web 端）—— 2026-11-05 新增

用法：
    cd C:\Users\Ko_Li\.openclaw\workspace\web\tools
    python tests\sync_check.py
    set SYNC_SRC=某副本.html    # 复盘任意副本（如线上字节落盘的 index.html）

覆盖（契约 _sync_task/CONTRACT.md §2/§3/§4，夹具已内嵌，不再依赖 _sync_task 目录）：
1) marks：远端 kind=ntdone 行 → NT.done/AN_DONE；新写入 kind=ntdone ref/val/id 结构；
   旧 localStorage zq_auto_nt_done 一次性迁移（按 sid 标记，迁移后清除）；
2) 通知 iframe：window.state.done 应用；iframe 内点「标记已处理」→ postMessage → 父页持久化
   （不二次 __zqApplyDone）→ PT 同步；再点一次回退；
3) userdata v6：远端 mp blob（at 全量）→ UI 定向应用（工具顺序/抽签/体测/点名/隐藏/课表/昵称），
   禁止 refreshAll 清空结果（A.result 保留）；本地改动（工具栏顺序/体测/抽签个数）→
   捕获 POST：blob 契约（v/at/顶层 homeToolsAt 镜像/prefs 原样保留/14 顶层键顺序 = v+at+11 section+homeToolsAt）；
   新增 power section（关注宿舍）：本地选择 → 推送 sel/at；远端 power 赢/本机 power 赢的合并都覆盖；
   新增 water section（水量抄表，2026-11-06）：本机保存 → blob.water.rooms[rv].recs / at.water 数字 / 14 键序；
   远端 water 赢/本机 water 赢的合并都覆盖；旧数据无 water → {rooms:{}} 不报错；
4) merge 与 expected_merge_web_mp / expected_merge_mp_web / expected_v5_migrate 逐字节一致；
5) TTL：cloudPull(false) 60s 内不重复拉 userdata；
6) 坏 JSON 云端：不覆盖本机、不崩，本地改动仍写出合法 v6；
7) 断网/推失败：保留 zq_udpend 待补发，恢复后 cloudPull 自动重试成功并清 pending；
8) 0 JS 报错 / 0 console.error / 无外部请求；文案不再出现「只存本机 / 不会上传」；
9) 管理员自动采用教务课表属后台逻辑（rebaseline，不产生推送）；用户显式切周/日视图正常推送；
   ttAdopt/ttSyncAt 不进 blob；
10) 远端 v5 blob：pull 合并后必须写回 v6（保留 v5 的 homeTools/fit），且再次 pull 幂等。
退出码 0 = 全绿。
"""
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.abspath(os.environ.get("SYNC_SRC") or os.path.join(ROOT, "index.html"))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 8941
BASE = "http://127.0.0.1:%d/" % PORT
REPORT_DIR = os.path.join(HERE, "_sync_reports")

SID = "3260799999"
NAME = "测试账号"
TOKEN = "mock-token-" + SID
AN_PREFIX = "[[CLASS_NOTICE_V1]]"
BASE_TS = 1762300000000

# ---------------------------------------------------------------- 夹具（与 _sync_task/fixtures 原样一致）
WEB = json.loads(r"""{
  "v": 6,
  "at": {
    "homeTools": 1762300000000,
    "fit": 1762300100000,
    "draw": 1762300200000,
    "group": 1762300300000,
    "roster": 1762300400000,
    "hide": 1762300500000,
    "tt": 1762300600000,
    "prefs": 1762290000000,
    "nick": 1762300700000,
    "power": 1762300800000,
    "water": 1762300900000
  },
  "homeTools": ["tt", "draw", "hw", "nt"],
  "fit": {
    "sex": "f",
    "grade": "34",
    "h": "165",
    "w": "52",
    "vc": "2600",
    "r50": "8.2",
    "sit": "30",
    "jump": "175",
    "pull": "5",
    "durM": "3",
    "durS": "45"
  },
  "draw": { "start": 1, "end": 60, "count": 8, "dup": true, "excl": "3,7", "sort": "desc" },
  "group": { "source": "names", "mode": "pergroup", "n": 3, "shuffle": true, "sel": [1, 2, 3, 4, 5, 6] },
  "roster": {
    "rosterSel": [1, 2, 3, 4, 5],
    "rollSel": [6, 7, 8],
    "rollSt": { "0": "到", "1": "假" },
    "rollNames": "6 李四\n7 王五\n8 赵六"
  },
  "hide": { "hwHide": { "hw_x": true }, "ntHide": { "nt_y": true } },
  "tt": {
    "ttView": "day",
    "ttUseMine": true,
    "ttLocal": {
      "c": [{ "name": "高等数学", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all", "teacher": "龚志伟", "room": "自强楼" }],
      "t": "2026-08-31"
    },
    "termStart": "2026-08-31"
  },
  "prefs": { "hwRemind": { "hw_x": true }, "ntSub": true, "ntSubAt": 1762290000000 },
  "nick": "陈同学",
  "power": { "sel": "4-23A---321", "at": 1762300800000 },
  "water": {
    "rooms": {
      "4-23A---321": {
        "p": 4,
        "recs": [
          { "m": "2026-09", "r": 100.5, "ts": 1762000000000 },
          { "m": "2026-10", "r": 106.2, "ts": 1762100000000 }
        ]
      }
    }
  },
  "homeToolsAt": 1762300000000
}""")
MP = json.loads(r"""{
  "v": 6,
  "at": {
    "homeTools": 1762310000000,
    "fit": 1762310100000,
    "draw": 1762310200000,
    "group": 1762310300000,
    "roster": 1762310400000,
    "hide": 1762310500000,
    "tt": 1762300600000,
    "prefs": 1762310700000,
    "nick": 1762300700000,
    "power": 1762300800000,
    "water": 1762310900000
  },
  "homeTools": ["hw", "nt", "ft", "draw"],
  "fit": {
    "sex": "m",
    "grade": "12",
    "h": "178",
    "w": "65",
    "vc": "4200",
    "r50": "7.0",
    "sit": "40",
    "jump": "220",
    "pull": "12",
    "durM": "3",
    "durS": "30"
  },
  "draw": { "start": 2, "end": 50, "count": 10, "dup": false, "excl": "", "sort": "draw" },
  "group": { "source": "prev", "mode": "groups", "n": 4, "shuffle": false, "sel": [10, 11, 12] },
  "roster": {
    "rosterSel": [10, 11, 12],
    "rollSel": [13, 14],
    "rollSt": { "0": "到" },
    "rollNames": "13 张一\n14 张二"
  },
  "hide": { "hwHide": { "hw_mp": true }, "ntHide": {} },
  "tt": {
    "ttView": "day",
    "ttUseMine": true,
    "ttLocal": {
      "c": [{ "name": "高等数学", "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all", "teacher": "龚志伟", "room": "自强楼" }],
      "t": "2026-08-31"
    },
    "termStart": "2026-09-07"
  },
  "prefs": { "hwRemind": { "hw_mp": true }, "ntSub": false, "ntSubAt": 1762310700000 },
  "nick": "陈同学",
  "water": {
    "rooms": {
      "1-16---305": {
        "p": 6,
        "recs": [
          { "m": "2026-09", "r": 80, "ts": 1762010000000 },
          { "m": "2026-10", "r": 93.5, "ts": 1762110000000 },
          { "m": "2026-11", "r": 100, "ts": 1762210000000 }
        ]
      }
    }
  },
  "homeToolsAt": 1762310000000
}""")
V5 = json.loads(r"""{
  "v": 5,
  "fit": { "sex": "m", "grade": "12", "h": "170", "w": "60", "vc": "", "r50": "", "sit": "", "jump": "", "pull": "", "durM": "", "durS": "" },
  "homeTools": ["draw", "hw", "nt", "tt"],
  "homeToolsAt": 1762200000000
}""")
MARKS = json.loads(r"""[
  {
    "id": "3260799999|ntdone|auto_g_testA",
    "seat": "3260799999",
    "kind": "ntdone",
    "ref": "auto_g_testA",
    "val": true,
    "ts": 1762300000000
  },
  {
    "id": "3260799999|ntdone|auto_g_testB",
    "seat": "3260799999",
    "kind": "ntdone",
    "ref": "auto_g_testB",
    "val": false,
    "ts": 1762300001000
  },
  {
    "id": "3260799999|hw|hw_test1",
    "seat": "3260799999",
    "kind": "hw",
    "ref": "hw_test1",
    "val": true,
    "ts": 1762300002000
  },
  {
    "id": "3260799999|nt|notice_test1",
    "seat": "3260799999",
    "kind": "nt",
    "ref": "notice_test1",
    "val": true,
    "ts": 1762300003000
  }
]""")
EXP_WEB_MP = json.loads(r"""{
  "v": 6,
  "at": {
    "homeTools": 1762310000000,
    "fit": 1762310100000,
    "draw": 1762310200000,
    "group": 1762310300000,
    "roster": 1762310400000,
    "hide": 1762310500000,
    "tt": 1762300600000,
    "prefs": 1762310700000,
    "nick": 1762300700000,
    "power": 1762300800000,
    "water": 1762310900000
  },
  "homeTools": [
    "hw",
    "nt",
    "ft",
    "draw"
  ],
  "fit": {
    "sex": "m",
    "grade": "12",
    "h": "178",
    "w": "65",
    "vc": "4200",
    "r50": "7.0",
    "sit": "40",
    "jump": "220",
    "pull": "12",
    "durM": "3",
    "durS": "30"
  },
  "draw": {
    "start": 2,
    "end": 50,
    "count": 10,
    "dup": false,
    "excl": "",
    "sort": "draw",
    "names": ""
  },
  "group": {
    "source": "prev",
    "mode": "groups",
    "n": 4,
    "shuffle": false,
    "sel": [
      10,
      11,
      12
    ]
  },
  "roster": {
    "rosterSel": [
      10,
      11,
      12
    ],
    "rollSel": [
      13,
      14
    ],
    "rollSt": {
      "0": "到"
    },
    "rollNames": "13 张一\n14 张二"
  },
  "hide": {
    "hwHide": {
      "hw_mp": true
    },
    "ntHide": {}
  },
  "tt": {
    "ttView": "day",
    "ttUseMine": true,
    "ttLocal": {
      "c": [
        {
          "name": "高等数学",
          "day": 0,
          "start": 1,
          "end": 2,
          "weeks": "1-16",
          "parity": "all",
          "teacher": "龚志伟",
          "room": "自强楼"
        }
      ],
      "t": "2026-08-31"
    },
    "termStart": "2026-09-07"
  },
  "prefs": {
    "hwRemind": {
      "hw_mp": true
    },
    "ntSub": false,
    "ntSubAt": 1762310700000
  },
  "nick": "陈同学",
  "power": {
    "sel": "4-23A---321",
    "at": 1762300800000
  },
  "water": {
    "rooms": {
      "1-16---305": {
        "p": 6,
        "recs": [
          {
            "m": "2026-09",
            "r": 80,
            "ts": 1762010000000
          },
          {
            "m": "2026-10",
            "r": 93.5,
            "ts": 1762110000000
          },
          {
            "m": "2026-11",
            "r": 100,
            "ts": 1762210000000
          }
        ]
      }
    }
  },
  "homeToolsAt": 1762310000000
}""")   # mergeBlob(mp, web)  —— 云端=mp，本机=web
EXP_MP_WEB = json.loads(r"""{
  "v": 6,
  "at": {
    "homeTools": 1762310000000,
    "fit": 1762310100000,
    "draw": 1762310200000,
    "group": 1762310300000,
    "roster": 1762310400000,
    "hide": 1762310500000,
    "tt": 1762300600000,
    "prefs": 1762310700000,
    "nick": 1762300700000,
    "power": 1762300800000,
    "water": 1762310900000
  },
  "homeTools": [
    "hw",
    "nt",
    "ft",
    "draw"
  ],
  "fit": {
    "sex": "m",
    "grade": "12",
    "h": "178",
    "w": "65",
    "vc": "4200",
    "r50": "7.0",
    "sit": "40",
    "jump": "220",
    "pull": "12",
    "durM": "3",
    "durS": "30"
  },
  "draw": {
    "start": 2,
    "end": 50,
    "count": 10,
    "dup": false,
    "excl": "",
    "sort": "draw",
    "names": ""
  },
  "group": {
    "source": "prev",
    "mode": "groups",
    "n": 4,
    "shuffle": false,
    "sel": [
      10,
      11,
      12
    ]
  },
  "roster": {
    "rosterSel": [
      10,
      11,
      12
    ],
    "rollSel": [
      13,
      14
    ],
    "rollSt": {
      "0": "到"
    },
    "rollNames": "13 张一\n14 张二"
  },
  "hide": {
    "hwHide": {
      "hw_mp": true
    },
    "ntHide": {}
  },
  "tt": {
    "ttView": "day",
    "ttUseMine": true,
    "ttLocal": {
      "c": [
        {
          "name": "高等数学",
          "day": 0,
          "start": 1,
          "end": 2,
          "weeks": "1-16",
          "parity": "all",
          "teacher": "龚志伟",
          "room": "自强楼"
        }
      ],
      "t": "2026-08-31"
    },
    "termStart": "2026-08-31"
  },
  "prefs": {
    "hwRemind": {
      "hw_mp": true
    },
    "ntSub": false,
    "ntSubAt": 1762310700000
  },
  "nick": "陈同学",
  "power": {
    "sel": "4-23A---321",
    "at": 1762300800000
  },
  "water": {
    "rooms": {
      "1-16---305": {
        "p": 6,
        "recs": [
          {
            "m": "2026-09",
            "r": 80,
            "ts": 1762010000000
          },
          {
            "m": "2026-10",
            "r": 93.5,
            "ts": 1762110000000
          },
          {
            "m": "2026-11",
            "r": 100,
            "ts": 1762210000000
          }
        ]
      }
    }
  },
  "homeToolsAt": 1762310000000
}""")   # mergeBlob(web, mp)  —— 云端=web，本机=mp
EXP_V5 = json.loads(r"""{
  "v": 6,
  "at": {
    "homeTools": 1762200000000,
    "fit": 0,
    "draw": 0,
    "group": 0,
    "roster": 0,
    "hide": 0,
    "tt": 0,
    "prefs": 0,
    "nick": 0,
    "power": 0,
    "water": 0
  },
  "homeTools": [
    "draw",
    "hw",
    "nt",
    "tt"
  ],
  "fit": {
    "sex": "m",
    "grade": "12",
    "h": "170",
    "w": "60",
    "vc": "",
    "r50": "",
    "sit": "",
    "jump": "",
    "pull": "",
    "durM": "",
    "durS": ""
  },
  "draw": { "names": "" },
  "group": {},
  "roster": {
    "rosterSel": [],
    "rollSel": [],
    "rollSt": {},
    "rollNames": ""
  },
  "hide": {
    "hwHide": {},
    "ntHide": {}
  },
  "tt": {
    "ttView": "",
    "ttUseMine": false,
    "ttLocal": null,
    "termStart": ""
  },
  "prefs": {
    "hwRemind": {},
    "ntSub": false,
    "ntSubAt": 0
  },
  "nick": "",
  "power": {
    "sel": "",
    "at": 0,
    "low": 30
  },
  "water": {
    "rooms": {}
  },
  "homeToolsAt": 1762200000000
}""")

MEMBERS = [{"seat": i, "sid": "9000%06d" % i, "name": "同学%02d" % i,
            "role": ("班长" if i == 1 else ""), "badge": ("班委" if i == 1 else ""),
            "is_admin": (i == 1)} for i in range(1, 71)]


def build_data():
    groups = []
    for gid, title in (("auto_g_testA", "合成通知 A"), ("auto_g_testB", "合成通知 B"), ("auto_g_testC", "合成通知 C")):
        groups.append({
            "id": gid, "cat": "教务", "title": title,
            "source": "合成测试群", "group": "合成测试群",
            "items": [{"kind": "text", "label": "原消息", "time": "11-05 10:00",
                       "from": "测试发送者", "fromName": "测试发送者", "fromRole": "老师", "fromBadge": "师",
                       "text": title + "正文：仅用于同步测试，不含真实班级信息。"}],
            "aiSummary": title + " 摘要", "aiPoints": ["合成要点"], "aiSegments": [{"type": "时间", "text": "11-05 12:00"}],
            "actionable": True,
        })
    notices = []
    for i, g in enumerate(groups):
        notices.append({"id": g["id"], "title": "", "body": AN_PREFIX + json.dumps(g, ensure_ascii=False),
                        "archived": False, "ts": BASE_TS + i * 1000})
    notices.append({"id": "notice_test1", "title": "合成手动通知", "body": "手动通知正文（同步测试用）",
                    "archived": False, "imp": False, "author": "测试发送者", "owner": "9000000001",
                    "attachments": "", "ts": BASE_TS + 900000})
    homework = [
        {"id": "hw_test1", "subject": "合成作业1", "content": "已完成作业（marks hw）", "due": "2026-11-20",
         "date": "2026-11-15", "time": "23:59", "author": "测试发送者", "owner": "9000000001",
         "attachments": "", "done": False, "archived": False, "ts": BASE_TS + 1},
        {"id": "hw_mp", "subject": "隐藏作业", "content": "该作业在远端 hide.hwHide 中被隐藏", "due": "2026-11-20",
         "date": "2026-11-16", "time": "23:59", "author": "测试发送者", "owner": "9000000001",
         "attachments": "", "done": False, "archived": False, "ts": BASE_TS + 2},
        {"id": "hw_other", "subject": "合成作业2", "content": "普通作业", "due": "2026-11-21",
         "date": "2026-11-17", "time": "23:59", "author": "测试发送者", "owner": "9000000001",
         "attachments": "", "done": False, "archived": False, "ts": BASE_TS + 3},
    ]
    tt = {"c": [{"name": "合成课程", "teacher": "测试老师", "room": "合成楼(101)",
                 "day": 0, "start": 1, "end": 2, "weeks": "1-16", "parity": "all"}],
          "t": "2026-08-31", "meta": {"fetchedAt": BASE_TS}}
    # 旧数据（v6 但还没有 water section，2026-11-06 之前的客户端写出）：用于「默认 {rooms:{}}」用例
    mp_old = json.loads(json.dumps(MP, ensure_ascii=False))
    mp_old.pop("water", None)
    mp_old["at"] = {k: v for k, v in mp_old["at"].items() if k != "water"}
    return {"sid": SID, "name": NAME, "members": MEMBERS, "notices": notices, "homework": homework,
            "marks": MARKS, "fitrecs": [], "tt": tt, "v5": V5,
            "userdata": {"id": SID, "blob": json.dumps(MP, ensure_ascii=False), "ts": 1762310000000},
            "userdata_no_water": {"id": SID, "blob": json.dumps(mp_old, ensure_ascii=False), "ts": 1762310000000}}


DATA = build_data()

# ---------------------------------------------------------------- 预览页注入（假身份 + fetch mock）
MOCK_JS = r"""
<script>
(function(){
window.__errs=[];window.__cerrs=[];
window.addEventListener("error",function(e){window.__errs.push(String((e&&e.message)||(e&&e.error)||"error"));});
window.addEventListener("unhandledrejection",function(e){var r=e&&e.reason;window.__errs.push("rejection:"+String((r&&r.message)||r));});
var _ce=console.error;console.error=function(){window.__cerrs.push(Array.prototype.map.call(arguments,function(x){try{return String(x);}catch(e){return "?";}}).join(" "));try{_ce.apply(console,arguments);}catch(e){}};
var DATA=__DATA__;
var ADM=(function(){try{return localStorage.getItem("_sync_admin")==="1";}catch(e){return false;}})();
var PH="";try{PH=localStorage.getItem("_sync_phase")||"";}catch(e){PH="";}
if(PH==="bad"&&DATA.userdata){DATA.userdata={id:DATA.sid,blob:"{{{bad-json",ts:1};}
if(PH==="v5"&&DATA.v5){DATA.userdata={id:DATA.sid,blob:JSON.stringify(DATA.v5),ts:1762200000000};}
if(PH==="oldwo"&&DATA.userdata_no_water){DATA.userdata=DATA.userdata_no_water;} /* 旧数据无 water section */
try{
  if(!localStorage.getItem("_sync_seeded")){
    localStorage.setItem("_sync_seeded","1");
    localStorage.setItem("zq_auto_nt_done",JSON.stringify({auto_g_legacy:true}));
  }
}catch(e){}
try{
  localStorage.setItem("zq_class_identity",JSON.stringify({token:"mock-token-"+DATA.sid,sid:DATA.sid,name:DATA.name,role:"",badge:"",is_admin:ADM,ts:Date.now()}));
}catch(e){}
window.__net={counts:{},writes:[],external:[],urls:[]};
window.__mk={
  failUdPost:false,failUdGet:false,delay:0,
  getUd:function(){try{return DATA.userdata?JSON.parse(DATA.userdata.blob):null;}catch(e){return null;}},
  setUd:function(b){DATA.userdata={id:DATA.sid,blob:JSON.stringify(b),ts:Date.now()};},
  rawUd:function(s){DATA.userdata={id:DATA.sid,blob:s,ts:Date.now()};}
};
function hdrs(o){var h={},k;o=o||{};for(k in o){try{h[k]=String(o[k]);}catch(e){h[k]="";}}return h;}
function resp(obj,ok,status){ok=(ok===undefined)?true:ok;status=status||(ok?200:500);
  return Promise.resolve({ok:ok,status:status,json:function(){return Promise.resolve(obj);},text:function(){return Promise.resolve("");}});}
function later(p){if(!window.__mk.delay)return p;return new Promise(function(res){setTimeout(function(){res(p);},window.__mk.delay);});}
function sink(kind,method,url,payload,ok,headers){
  window.__net.counts[kind]=(window.__net.counts[kind]||0)+1;
  if(window.__net.urls.length<500)window.__net.urls.push(kind+" "+method+" "+url.slice(0,180));
  window.__net.writes.push({kind:kind,method:method,url:url,ok:(ok!==false),body:payload,headers:headers||{}});
}
window.fetch=function(u,o){
  o=o||{};var method=String(o.method||"GET").toUpperCase();
  var s=String((u&&u.url!==undefined)?u.url:u);
  var hh=hdrs(o.headers);
  if(s.indexOf("tcloudbasegateway")>=0){
    if(s.indexOf("/userdata")>=0){
      if(method==="GET"){
        if(window.__mk.failUdGet){sink("userdata","GET",s,"",false,hh);return Promise.reject(new Error("ud-get-fail"));}
        sink("userdata","GET",s,"",true,hh);
        var rows=DATA.userdata?[{id:DATA.userdata.id,blob:DATA.userdata.blob,ts:DATA.userdata.ts}]:[];
        return later(resp(rows));
      }
      var ub=String(o.body||"[]");
      if(window.__mk.failUdPost){sink("userdata_post","POST",s,ub,false,hh);return Promise.reject(new Error("ud-post-fail"));}
      sink("userdata_post","POST",s,ub,true,hh);
      var urows=null;try{urows=JSON.parse(ub);}catch(e){urows=null;}
      var urow=(urows&&urows[0])||{};
      if(urow&&urow.id!=null&&urow.blob!=null){DATA.userdata={id:urow.id,blob:String(urow.blob),ts:Number(urow.ts)||Date.now()};}
      return later(resp([{id:urow.id,blob:urow.blob,ts:urow.ts}]));
    }
    if(s.indexOf("/marks")>=0){
      if(method==="GET"){sink("marks","GET",s,"",true,hh);return later(resp(DATA.marks));}
      var mb=String(o.body||"[]"),mrows=null;try{mrows=JSON.parse(mb);}catch(e){mrows=null;}
      sink("marks_post","POST",s,mb,true,hh);
      (mrows||[]).forEach(function(r){
        if(!r||!r.id)return;
        DATA.marks=DATA.marks.filter(function(x){return x.id!==r.id;});
        DATA.marks.push(r);
      });
      return later(resp(mrows||[]));
    }
    if(s.indexOf("rpc/class_members")>=0){sink("members","POST",s,"",true,hh);return later(resp(DATA.members));}
    if(s.indexOf("rpc/class_verify")>=0){sink("verify","POST",s,"",true,hh);return later(resp({ok:true,token:"mock-token-"+DATA.sid,sid:DATA.sid,name:DATA.name,role:"",badge:"",is_admin:ADM}));}
    if(s.indexOf("/notices")>=0){
      if(method==="GET"&&s.indexOf("select=id,ts")>=0){sink("notices_sig","GET",s,"",true,hh);return later(resp(DATA.notices.map(function(r){return {id:r.id,ts:r.ts};})));}
      if(method==="GET"){sink("notices","GET",s,"",true,hh);return later(resp(DATA.notices));}
      sink("write","POST",s,o.body,true,hh);return later(resp([]));
    }
    if(s.indexOf("/homework")>=0){if(method==="GET"){sink("homework","GET",s,"",true,hh);return later(resp(DATA.homework));}sink("write","POST",s,o.body,true,hh);return later(resp([]));}
    if(s.indexOf("/fitrecs")>=0){if(method==="GET"){sink("fitrecs","GET",s,"",true,hh);return later(resp(DATA.fitrecs));}sink("write","POST",s,o.body,true,hh);return later(resp([]));}
    if(s.indexOf("/power")>=0){
      /* 宿舍电费：按 id=eq.<roomverify> 返回一行（关注宿舍） */
      var pv="4-23A---321",prow;
      try{var pm=s.match(/[?&]id=eq\.([^&]+)/);if(pm)pv=decodeURIComponent(pm[1]);}catch(e){}
      prow={id:pv,label:pv,building:"23号楼A座",room:"321",quantity:382.02,unit:"度",low:false,
            updated_at:"2026-11-05T22:04:00+08:00"};
      if(pv==="1-16---305"){prow.label="16号楼305";prow.building="16号楼";prow.room="305";prow.quantity=22.25;prow.low=true;}
      if(pv==="1-13---324"){prow.label="13号楼324";prow.building="13号楼";prow.room="324";}
      sink("power","GET",s,"",true,hh);return later(resp([prow]));
    }
    if(s.indexOf("/visits")>=0){sink("visits","POST",s,"",true,hh);return later(resp([]));}
    if(s.indexOf("/feedback")>=0){sink("write","POST",s,"",true,hh);return later(resp([]));}
    sink("write",method,s,o.body,true,hh);
    if(method==="PATCH")return later(resp([]));
    return later(resp([]));
  }
  if(s.indexOf("tt.json")>=0){sink("tt","GET",s,"",true,hh);return later(resp(DATA.tt));}
  window.__net.counts.external=(window.__net.counts.external||0)+1;
  window.__net.external.push(s.slice(0,200));
  window.__net.writes.push({kind:"external",method:method,url:s,ok:false});
  return Promise.reject(new Error("external-blocked"));
};
})();
</script>
"""

PREVIEW = "_sync_preview.html"
H_FUNC = "_sync_harness.html"


def build_preview():
    html = open(SRC, encoding="utf-8", newline="").read()
    hook = ("window.__sync={UD:UD,NT:NT,D:D,AUTH:AUTH,A:A,TT:TT,gotoTab:gotoTab,ttSyncPull:ttSyncPull,"
            "POWER:(typeof POWER!==\"undefined\"?POWER:null),"
            "WATER:(typeof WATER!==\"undefined\"?WATER:null),"
            "AN_DONE:function(){return AN_DONE;},cloudPull:cloudPull,"
            "noticeApplyDone:noticeApplyDone,renderAutoNT:renderAutoNT,fixtures:window.__SYNC_FIX};")
    anchor = "})();\r\n</script>"
    idx = html.rfind(anchor)
    if idx < 0:
        # 行尾兼容：2026-11-21 仓库整理后 index.html 为 LF；CRLF/LF 两种都接受
        idx = html.rfind("})();\n</script>")
    if idx < 0:
        raise SystemExit("[sync_check] 找不到主脚本结尾锚点")
    fix = ("window.__SYNC_FIX={web:%s,mp:%s,v5:%s,marks:%s,exp_web_mp:%s,exp_mp_web:%s,exp_v5:%s};"
           % (json.dumps(WEB, ensure_ascii=False),
              json.dumps(MP, ensure_ascii=False),
              json.dumps(V5, ensure_ascii=False),
              json.dumps(MARKS, ensure_ascii=False),
              json.dumps(EXP_WEB_MP, ensure_ascii=False),
              json.dumps(EXP_MP_WEB, ensure_ascii=False),
              json.dumps(EXP_V5, ensure_ascii=False)))
    html = html[:idx] + hook + "\r\n" + html[idx:]
    mock = MOCK_JS.replace("__DATA__", json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c"))
    out = html.replace("<head>", "<head><script>" + fix + "</script>" + mock, 1)
    with open(os.path.join(HERE, PREVIEW), "w", encoding="utf-8", newline="") as fh:
        fh.write(out)


COMMON_JS = r"""
var SRC="__SRC__";
var SID="__SID__";
function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
function pump(){return new Promise(function(res){try{var ch=new MessageChannel();ch.port1.onmessage=function(){res();};ch.port2.postMessage(0);}catch(e){setTimeout(res,0);}});}
async function pumpN(n){for(var i=0;i<(n||1);i++)await pump();}
async function waitCond(fn,maxTries){var n=maxTries||8000;for(var i=0;i<n;i++){var v=false;try{v=!!fn();}catch(e){v=false;}if(v)return true;await pump();}return false;}
function mount(src,w,h){return new Promise(function(res,rej){
  var old=document.getElementById("fr");if(old&&old.parentNode)old.parentNode.removeChild(old);
  var f=document.createElement("iframe");f.id="fr";f.style.cssText="width:"+w+"px;height:"+h+"px;border:0;display:block";f.src=src;
  var done=false;f.onload=function(){if(done)return;done=true;setTimeout(function(){res(f);},80);};
  f.onerror=function(){if(done)return;done=true;rej(new Error("iframe load failed: "+src));};
  document.body.appendChild(f);setTimeout(function(){if(!done){done=true;res(f);}},15000);});}
function q(f,s){return f.contentDocument.querySelector(s);}
function qa(f,s){return Array.prototype.slice.call(f.contentDocument.querySelectorAll(s));}
function txt(f,s){var e=q(f,s);return e?e.textContent:"";}
function tab(f,k){var b=q(f,'#tabsBar button[data-tab="'+k+'"]');if(b){b.click();return true;}throw new Error("no tab: "+k);}
function frame(f){return q(f,"#noticeHost iframe");}
function frameDoc(f){var fr=frame(f);return fr?fr.contentDocument:null;}
function net(f){try{return f.contentWindow.__net||{counts:{},writes:[],external:[],urls:[]};}catch(e){return {counts:{},writes:[],external:[],urls:[]};}}
function counts(f){var c=net(f).counts||{},o={},k;for(k in c)o[k]=c[k];return o;}
function count(f,k){return counts(f)[k]||0;}
function errsOf(f){try{return (f.contentWindow.__errs||[]).slice();}catch(e){return ["<inaccessible>"];}}
function cerrsOf(f){try{return (f.contentWindow.__cerrs||[]).slice();}catch(e){return ["<inaccessible>"];}}
function ws(f,kind){return (net(f).writes||[]).filter(function(x){return x.kind===kind;});}
function udPosts(f){return ws(f,"userdata_post").filter(function(x){return x.ok!==false;});}
function udGets(f){return ws(f,"userdata").filter(function(x){return x.ok!==false;});}
function blobs(f){var a=udPosts(f),out=[];a.forEach(function(p){try{out.push(JSON.parse(JSON.parse(p.body)[0].blob));}catch(e){out.push(null);}});return out;}
function markRows(f){var a=ws(f,"marks_post"),out=[];a.forEach(function(p){try{var rows=JSON.parse(p.body);out.push(rows[0]||null);}catch(e){out.push(null);}});return out;}
/* 等 userdata POST 到位；防抖计时器在虚拟时间下可能不触发时，用 cloudPull(true) 走「拉取→补推送」权威路径 */
async function waitPost(f,expect){
  var ok=await waitCond(function(){return udPosts(f).length>=expect;},20000);
  if(!ok){try{f.contentWindow.__sync.cloudPull(true);}catch(e){}ok=await waitCond(function(){return udPosts(f).length>=expect;},20000);}
  return ok;
}
function setV(f,sel,val){var e=q(f,sel);if(!e)throw new Error("missing "+sel);e.value=val;e.dispatchEvent(new Event("input",{bubbles:true}));return e;}
function lsGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){}}
function lsDel(k){try{localStorage.removeItem(k);}catch(e){}}
function clearAllCache(){try{var ks=[],i;for(i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(/^zq_ud(cache|pend|at)_/.test(k)||/^zq_marks_cache_/.test(k)||/^zq_synced_at_/.test(k)||/^zq_visited_/.test(k)||/^zq_migrated_/.test(k))ks.push(k);}ks.forEach(function(k){localStorage.removeItem(k);});}catch(e){}}
function clearUd(){try{var ks=[],i;for(i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(/^zq_ud(cache|pend|at)_/.test(k))ks.push(k);}ks.forEach(function(k){localStorage.removeItem(k);});}catch(e){}}
function report(slot,data){data=data||{};data.slot=slot;
  try{var x=new XMLHttpRequest();x.open("POST","/_report?slot="+slot,false);x.setRequestHeader("Content-Type","application/json");x.send(JSON.stringify(data));}catch(e){}}
"""

FUNC_JS = r"""
async function run(){
  var R={steps:[],diag:{}};
  function T(k,ok,note){R.steps.push({k:k,ok:!!ok,note:note==null?"":String(note)});}
  var ALLERR=[],ALLCERR=[],ALLEXT=[];
  function collect(f){
    try{ALLERR=ALLERR.concat(errsOf(f));}catch(e){}
    try{ALLCERR=ALLCERR.concat(cerrsOf(f));}catch(e){}
    try{ALLEXT=ALLEXT.concat((net(f).external)||[]);}catch(e){}
  }
  try{
    /* ============ A. mount1：远端 mp blob + marks(ntdone) 应用 ============ */
    clearAllCache(); lsDel("_sync_seeded"); lsDel("zq_auto_nt_done"); lsSet("_sync_phase","boot");
    var f=await mount(SRC,430,940), w=f.contentWindow, doc=f.contentDocument;
    await waitCond(function(){return w.__sync&&w.__sync.D&&w.__sync.D.d&&w.__sync.D.d.seat;},20000);
    w.__sync.cloudPull(true);
    var pulled=await waitCond(function(){return w.__sync.D.d.homeTools.join(",")==="hw,nt,ft,draw";},20000);
    T("远端 userdata v6（mp 写的 blob）已拉取并应用 homeTools", pulled, JSON.stringify(w.__sync.D.d.homeTools));
    /* 诊断：拉取后仍被判脏的 section（用于定位“无本地改动却推送”的问题） */
    try{
      var _cache=JSON.parse(lsGet("zq_udcache_"+SID)||"null")||{};
      var _sec=w.__sync.UD.sections(),_diff={};
      ["homeTools","fit","draw","group","roster","hide","tt","nick"].forEach(function(k){
        if(JSON.stringify(_cache[k])!==JSON.stringify(_sec[k]))_diff[k]={cache:_cache[k],cur:_sec[k]};
      });
      R.diag.afterPullDirty=w.__sync.UD.dirtySections();
      R.diag.afterPullDiff=_diff;
      R.diag.afterPullPosts=udPosts(f).length;
    }catch(e){R.diag.afterPullErr=String(e);}
    T("拉取请求为 GET userdata?select=*&id=eq.<sid>", udGets(f).length>=1 && /userdata\?select=\*&id=eq\./.test(udGets(f)[0].url), udGets(f).map(function(x){return x.url;})[0]||"");
    T("拉取请求带 X-Device-Id 身份头", !!(udGets(f)[0]&&udGets(f)[0].headers&&udGets(f)[0].headers["X-Device-Id"]), udGets(f)[0]?JSON.stringify(Object.keys(udGets(f)[0].headers||{})):"");
    T("拉取后写出本机缓存 zq_udcache_<sid>（v=6）", (function(){try{var b=JSON.parse(lsGet("zq_udcache_"+w.__sync.D.d.seat)||"null");return b&&b.v===6;}catch(e){return false;}})());

    /* marks：ntdone 行 → NT.done / AN_DONE；旧 localStorage 一次性迁移 */
    var mig=await waitCond(function(){return markRows(f).some(function(r){return r&&r.kind==="ntdone"&&r.ref==="auto_g_legacy"&&r.val===true;});},20000);
    T("旧 zq_auto_nt_done 已迁移为 marks(kind=ntdone)", mig, JSON.stringify(markRows(f).map(function(r){return r?r.ref+":"+r.kind:null;})));
    T("迁移后清除 localStorage zq_auto_nt_done", lsGet("zq_auto_nt_done")===null, lsGet("zq_auto_nt_done"));
    T("按 sid 标记迁移只做一次（zq_migrated_ntdone）", (function(){try{var m=JSON.parse(lsGet("zq_migrated_"+w.__sync.D.d.seat)||"{}");return !!m.ntdone;}catch(e){return false;}})());
    var nd=w.__sync.NT.done||{};
    T("marks(kind=ntdone,val=true) 应用为 NT.done", !!nd.auto_g_testA && !!nd.auto_g_legacy, JSON.stringify(nd));
    T("val=false 的 ntdone 行不进入 NT.done", !nd.auto_g_testB, JSON.stringify(nd));
    T("旧 AN_DONE 兼容镜像同步维护", !!(w.__sync.AN_DONE().auto_g_testA && w.__sync.AN_DONE().auto_g_legacy), JSON.stringify(w.__sync.AN_DONE()));

    /* UI 定向应用断言 */
    var tabs=qa(f,"#tabsBar button").map(function(b){return b.getAttribute("data-tab");});
    T("工具栏顺序来自远端 homeTools", tabs.join(",")==="hw,nt,ft,all", tabs.join(","));
    T("D.d.homeTools 为远端 4 项", (w.__sync.D.d.homeTools||[]).join(",")==="hw,nt,ft,draw", JSON.stringify(w.__sync.D.d.homeTools));
    T("抽签参数已应用（start/end/count）", q(f,"#aStart").value==="2" && q(f,"#aEnd").value==="50" && q(f,"#aCount").value==="10", [q(f,"#aStart").value,q(f,"#aEnd").value,q(f,"#aCount").value].join("/"));
    T("体测输入已应用（身高/体重/肺活量）", q(f,"#fH").value==="178"&&q(f,"#fW").value==="65"&&q(f,"#fVc").value==="4200", [q(f,"#fH").value,q(f,"#fW").value,q(f,"#fVc").value].join("/"));
    T("体测性别/年级组已应用", q(f,'input[name=ftsex][value="m"]').checked && q(f,"#fGrade").value==="12", q(f,"#fGrade").value);
    T("点名名单已应用（rollSel 2 人 + 渲染）", (w.__sync.D.d.rollSel||[]).join(",")==="13,14" && qa(f,"#rGrid .rcard").length===2, JSON.stringify(w.__sync.D.d.rollSel)+"/"+(qa(f,"#rGrid .rcard").length));
    T("点名到·假状态保留远端值", JSON.stringify(w.__sync.D.d.rollSt)==='{"0":"到"}', JSON.stringify(w.__sync.D.d.rollSt));
    T("课表偏好已应用（ttView/ttUseMine/termStart）", w.__sync.D.d.ttView==="day"&&w.__sync.D.d.ttUseMine===true&&w.__sync.D.d.termStart==="2026-09-07", [w.__sync.D.d.ttView,w.__sync.D.d.ttUseMine,w.__sync.D.d.termStart].join("/"));
    T("昵称已应用（输入框）", w.__sync.D.d.nick==="陈同学"&&q(f,"#hAuthor").value==="陈同学", w.__sync.D.d.nick);
    T("隐藏项已应用（hwHide）", !!(w.__sync.D.d.hwHide&&w.__sync.D.d.hwHide.hw_mp), JSON.stringify(w.__sync.D.d.hwHide));

    /* 隐藏项 UI：进作业 tab 拉取作业，被隐藏项不渲染 */
    tab(f,"hw");
    var hwOk=await waitCond(function(){return qa(f,"#hList .item").length>0;},20000);
    await pumpN(5);
    var hwItems=qa(f,"#hList .item");
    T("隐藏作业在作业列表不可见", hwOk && hwItems.length===2 && q(f,"#hList").textContent.indexOf("隐藏作业")<0, hwItems.length+"/"+q(f,"#hList").textContent.slice(0,60));

    /* 通知 iframe：window.state.done */
    tab(f,"nt");
    var hasFrame=await waitCond(function(){return !!frame(f);},25000);
    var idoc=frameDoc(f), iw=hasFrame?frame(f).contentWindow:null;
    T("通知 iframe 已创建", hasFrame);
    T("iframe 内 window.state.done 已应用 ntdone", !!(hasFrame&&iw.state&&iw.state.done&&iw.state.done.auto_g_testA===true), hasFrame?JSON.stringify(iw.state.done):"");
    T("iframe 内 val=false 组未标记已处理", !!(hasFrame&&iw.state&&iw.state.done&&!iw.state.done.auto_g_testB), "");
    T("iframe 内 testA 卡片按钮为 done 态", !!(idoc&&idoc.querySelector('[data-act="done"][data-gid="auto_g_testA"].done')), "");

    /* TTL 60s：cloudPull(false) 不重复拉 userdata */
    await sleep(50);
    var g0=count(f,"userdata");
    w.__sync.cloudPull(false); await pumpN(20);
    T("userdata TTL 60s 内 cloudPull(false) 不重复拉取", count(f,"userdata")===g0, g0+"->"+count(f,"userdata"));

    /* ============ B. merge 逐字节一致（页面内 UD.merge vs 夹具） ============ */
    var FX=w.__sync.fixtures;
    var b_mp_web=JSON.stringify(w.__sync.UD.merge(FX.mp,FX.web));
    var b_web_mp=JSON.stringify(w.__sync.UD.merge(FX.web,FX.mp));
    var b_v5=JSON.stringify(w.__sync.UD.merge(FX.v5,{at:{},fit:{sex:"m"}}));
    T("merge(mp,web) 与 expected_merge_web_mp 逐字节一致", b_mp_web===JSON.stringify(FX.exp_web_mp), "");
    T("merge(web,mp) 与 expected_merge_mp_web 逐字节一致", b_web_mp===JSON.stringify(FX.exp_mp_web), "");
    T("v5 迁移合并与 expected_v5_migrate 逐字节一致", b_v5===JSON.stringify(FX.exp_v5), "");

    /* ============ C. 本地改动 → POST userdata blob 契约 ============ */
    /* 诊断：C 之前是否已经出现多余推送 */
    try{
      R.diag.preC1Posts=udPosts(f).length;
      R.diag.preC1Dirty=w.__sync.UD.dirtySections();
    }catch(e){R.diag.preC1Err=String(e);}
    /* C1 切工具栏顺序（真实 UI：全部页拖动卡片 handle → 拖到工具栏第 1 格） */
    tab(f,"all");
    await pumpN(5);
    function pev(f,type,x,y){var d=f.contentDocument;
      return new PointerEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,pointerId:1,button:0,pointerType:"mouse"});}
    function dragCardToTab(f,key,tabKey){
      var d=f.contentDocument;
      var h=q(f,'[data-handle="'+key+'"]'); if(!h)return false;
      try{h.scrollIntoView({block:"center"});}catch(e){}
      var tb=tabKey?q(f,'#tabsBar button[data-tab="'+tabKey+'"]'):q(f,'#tabsBar button[data-tab]'); if(!tb)return false;
      var bar=q(f,'#tabsBar'); var hr=h.getBoundingClientRect(), tr=tb.getBoundingClientRect(), br=bar.getBoundingClientRect();
      var x0=hr.left+hr.width/2,y0=hr.top+hr.height/2;
      var x1=br.left+2,y1=tr.top+tr.height/2;
      h.dispatchEvent(pev(f,"pointerdown",x0,y0));
      for(var i=1;i<=10;i++)d.dispatchEvent(pev(f,"pointermove",x0+(x1-x0)*i/10,y0+(y1-y0)*i/10));
      d.dispatchEvent(pev(f,"pointerup",x1,y1));
      return true;
    }
    var rollHandle=q(f,'[data-handle="roll"]');
    T("全部栏卡片有拖动 handle（新交互，旧「设为首页」已删除）", !!rollHandle&&!q(f,'[data-home]'), "");
    dragCardToTab(f,"roll","");
    await pumpN(4);
    await sleep(300);
    await waitPost(f,1);
    var p1=udPosts(f);
    T("本地改工具栏顺序 → POST userdata 1 次", p1.length===1, p1.length);
    var b1=blobs(f)[0]||null;
    T("POST userdata body 为 [{id,blob,ts}]", !!(p1[0]&&(function(){try{var a=JSON.parse(p1[0].body);return a.length===1&&a[0].id===w.__sync.D.d.seat&&typeof a[0].blob==="string"&&typeof a[0].ts==="number";}catch(e){return false;}})()), "");
    T("POST userdata 头含 Prefer: merge-duplicates", !!(p1[0]&&p1[0].headers&&/merge-duplicates/.test(p1[0].headers["Prefer"]||"")), p1[0]?JSON.stringify(p1[0].headers):"");
    T("blob 顶层键顺序符合契约（v/at/11 section/homeToolsAt）", !!b1 && Object.keys(b1).join(",")==="v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt", b1?Object.keys(b1).join(","):"");
    T("blob.v===6 且无重复顶层键", !!b1 && b1.v===6 && Object.keys(b1).length===14, b1?Object.keys(b1).length:"");
    T("blob.homeTools 已更新为新顺序", !!b1 && b1.homeTools[0]==="roll", b1?JSON.stringify(b1.homeTools):"");
    T("blob.at.homeTools 为最新且 homeToolsAt 镜像一致", !!b1 && b1.at.homeTools>FX.mp.at.homeTools && b1.homeToolsAt===b1.at.homeTools, b1?b1.at.homeTools+"/"+b1.homeToolsAt+"/"+FX.mp.at.homeTools:"");
    T("at 覆盖全部 11 个 section（数字）", !!b1 && ["homeTools","fit","draw","group","roster","hide","tt","prefs","nick","power","water"].every(function(k){return typeof b1.at[k]==="number";}), "");
    T("power section 契约（未选宿舍时 sel=\"\"/at=0）", !!b1 && b1.power.sel==="" && b1.power.at===0, b1?JSON.stringify(b1.power):"");
    T("water section 契约（沿用云端 rooms，默认 {rooms:{}}）", !!b1 && b1.water && b1.water.rooms && b1.water.rooms["1-16---305"] && b1.water.rooms["1-16---305"].p===6, b1?JSON.stringify(b1.water):"");
    T("未拥有的 prefs 原样保留云端值（不被默认值覆盖）", !!b1 && JSON.stringify(b1.prefs)===JSON.stringify(FX.mp.prefs), b1?JSON.stringify(b1.prefs):"");
    T("未改动的 nick 保留", !!b1 && b1.nick==="陈同学", b1?b1.nick:"");
    T("未改动的 fit 不被默认值覆盖", !!b1 && b1.fit.h==="178" && b1.fit.vc==="4200", b1?JSON.stringify(b1.fit):"");

    /* C2 改体测值（真实输入事件） */
    setV(f,"#fH","180");
    await sleep(300);
    await waitPost(f,2);
    var p2=udPosts(f);
    T("本地改体测 → 第 2 次 POST userdata", p2.length===2, p2.length);
    var b2=blobs(f)[1]||null;
    T("blob.fit 已更新且 at.fit 更新", !!b2 && b2.fit.h==="180" && b2.at.fit>FX.mp.at.fit, b2?b2.fit.h+"/"+b2.at.fit:"");
    T("第二次推送仍原样保留 prefs / homeTools", !!b2 && JSON.stringify(b2.prefs)===JSON.stringify(FX.mp.prefs) && b2.homeTools[0]==="roll", "");

    /* C3 改抽签个数（真实点击「开始抽签」触发 aRead→D.save） */
    setV(f,"#aCount","3");
    q(f,"#aRun").click();
    await sleep(300);
    await waitPost(f,3);
    var p3=udPosts(f);
    T("本地改抽签个数 → 第 3 次 POST userdata", p3.length===3, p3.length);
    var b3=blobs(f)[2]||null;
    T("blob.draw 已更新（count=3，参数完整）", !!b3 && b3.draw.count===3 && b3.draw.start===2 && b3.draw.end===50, b3?JSON.stringify(b3.draw):"");
    T("本机 udCache 同步更新（draw.count=3）", (function(){try{var c=JSON.parse(lsGet("zq_udcache_"+w.__sync.D.d.seat)||"null");return c&&c.draw&&c.draw.count===3;}catch(e){return false;}})());
    T("抽签结果已生成（A.result）", !!(w.__sync.A&&w.__sync.A.result&&w.__sync.A.result.length===3), w.__sync.A&&w.__sync.A.result?w.__sync.A.result.length:0);

    /* C4 关注宿舍（power section）：本地选择 → POST blob.power（sel/at 一致） */
    var PW_RV="4-23A---321";
    T("POWER 模块已挂到 __sync（测试钩子）", !!(w.__sync.POWER&&typeof w.__sync.POWER.pick==="function"), "");
    w.__sync.POWER.pick(PW_RV);
    await sleep(300);
    await waitPost(f,4);
    var p4=udPosts(f);
    T("选关注宿舍 → 第 4 次 POST userdata", p4.length===4, p4.length);
    var b4=blobs(f)[3]||null;
    T("blob.power 记录关注宿舍（sel=roomverify）", !!b4&&b4.power&&b4.power.sel===PW_RV, b4?JSON.stringify(b4.power):"");
    T("blob.at.power 为数字且与值内 at 镜像一致", !!b4&&typeof b4.at.power==="number"&&b4.at.power>0&&b4.power.at===b4.at.power, b4?b4.at.power+"/"+(b4.power&&b4.power.at):"");
    T("blob 顶层键顺序仍为契约（power 在 nick 后、water 在 power 后）", !!b4&&Object.keys(b4).join(",")==="v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt", b4?Object.keys(b4).join(","):"");
    /* 清掉本机 power 兜底键：后续阶段重新 mount 时不让 C4 选择产生额外推送（真源仍是 UD） */
    lsDel("zq_power_sel_"+SID); lsDel("zq_power_cache_"+SID);

    /* C5 水量（water section，2026-11-06 契约）：本机保存抄表 → POST blob.water.rooms[rv].recs */
    var WT_RV=PW_RV;
    T("WATER 模块已挂到 __sync（测试钩子）", !!(w.__sync.WATER&&typeof w.__sync.WATER.save==="function"&&typeof w.__sync.WATER.sel==="function"), "");
    T("WATER 沿用关注宿舍选择（与电费共用 POWER.sel）", !!(w.__sync.WATER&&w.__sync.WATER.sel()===WT_RV), w.__sync.WATER?String(w.__sync.WATER.sel()):"");
    setV(f,"#wtMonth","2026-10"); setV(f,"#wtReading","123.45");
    var wt1=w.__sync.WATER.save();
    T("水量页保存一条抄表（WATER.save=true）", wt1===true, String(wt1));
    await sleep(300);
    await waitPost(f,5);
    var p5=udPosts(f);
    T("保存抄表 → 第 5 次 POST userdata", p5.length===5, p5.length);
    var b5=blobs(f)[4]||null;
    T("blob.water.rooms[rv] 记录 {p,recs:[{m,r,ts}]}", !!(b5&&b5.water&&b5.water.rooms&&b5.water.rooms[WT_RV]&&(function(){var r=b5.water.rooms[WT_RV],x=r.recs[r.recs.length-1];return r.p===4&&x&&x.m==="2026-10"&&Math.abs(x.r-123.45)<1e-9&&typeof x.ts==="number";})()), b5?JSON.stringify(b5.water):"");
    T("blob.at.water 为数字且本机赢（> 云端 mp fixture at.water）", !!(b5&&typeof b5.at.water==="number"&&b5.at.water>FX.mp.at.water), b5?b5.at.water+"/"+FX.mp.at.water:"");
    T("water 值内不镜像 at（只有 rooms）", !!(b5&&b5.water&&Object.keys(b5.water).join(",")==="rooms"&&b5.water.at===undefined&&b5.water.rooms[WT_RV].at===undefined), b5?Object.keys(b5.water).join(","):"");
    T("blob 顶层 14 键（water 在 power 后 / homeToolsAt 前）", !!b5&&Object.keys(b5).join(",")==="v,at,homeTools,fit,draw,group,roster,hide,tt,prefs,nick,power,water,homeToolsAt", b5?Object.keys(b5).join(","):"");
    /* 同月覆盖：再次保存同一月份 → 覆盖该条（recs 仍 1 条、读数更新） */
    setV(f,"#wtReading","125.60");
    w.__sync.WATER.save();
    await sleep(300);
    await waitPost(f,6);
    var b6=blobs(f)[5]||null;
    var wr6=(b6&&b6.water&&b6.water.rooms&&b6.water.rooms[WT_RV])?b6.water.rooms[WT_RV].recs:[];
    T("同月再次保存 → 覆盖该月记录（仍 1 条且读数更新）", wr6.length===1&&Math.abs(wr6[0].r-125.6)<1e-9, JSON.stringify(wr6));
    /* 新增下一条：用量/水费按 web WATER.cost 同口径可算（6.5 吨 4 人间定额内 = 0 元 0 度） */
    setV(f,"#wtMonth","2026-11"); setV(f,"#wtReading","132.10");
    w.__sync.WATER.save();
    await sleep(300);
    await waitPost(f,7);
    var b7=blobs(f)[6]||null;
    var wr7=(b7&&b7.water&&b7.water.rooms&&b7.water.rooms[WT_RV])?b7.water.rooms[WT_RV].recs:[];
    T("跨月保存 → water.rooms[rv].recs 按月升序", wr7.length===2&&wr7[0].m==="2026-10"&&wr7[1].m==="2026-11", JSON.stringify(wr7));
    T("WATER.cost 同口径（用量 6.5 吨 · 4 人间 · 定额内 0 元 / 0 度）", (function(){var c=w.__sync.WATER.cost(6.5,4);return c.fee===0&&c.deg===0&&c.within;})());
    /* 远端 water 赢：远端 at.water 抬到未来 + 换成别间 → pull 后应用远端 rooms（覆盖本机视图） */
    var curW=w.__mk.getUd()||{}; curW.at=curW.at||{};
    var remoteWAt=Date.now()+5000;
    curW.at.water=remoteWAt;
    curW.water={rooms:{"4-23B---424":{p:6,recs:[{m:"2026-11",r:210.5,ts:1}]}}};
    w.__mk.setUd(curW);
    w.__sync.cloudPull(true);
    var wtRemote=await waitCond(function(){try{var r=w.__sync.D.d.water&&w.__sync.D.d.water.rooms&&w.__sync.D.d.water.rooms["4-23B---424"];return !!(r&&r.p===6);}catch(e){return false;}},20000);
    T("远端 water 赢：拉取后 D.d.water 应用远端 rooms", wtRemote, JSON.stringify(w.__sync.D.d.water&&w.__sync.D.d.water.rooms));
    T("远端 water 赢：UD 缓存 at.water = 远端时间戳", (function(){try{var c=JSON.parse(lsGet("zq_udcache_"+SID)||"null");return !!(c&&c.at&&c.at.water===remoteWAt);}catch(e){return false;}})(), String(remoteWAt));
    T("远端 water 赢：拉取后 0 JS 报错", errsOf(f).length===0, errsOf(f).join(" | "));

    /* ============ D. 远端再次变化：定向应用且不重置进行中的结果 ============ */
    /* 用当前远端 blob 改 draw + 拉高 at */
    var cur=w.__mk.getUd()||{};
    if(cur&&cur.draw){
      cur.at=cur.at||{};
      cur.at.draw=Date.now()+5000;
      cur.draw={start:5,end:60,count:6,dup:true,excl:"",sort:"draw"};
      w.__mk.setUd(cur);
    }
    w.__sync.cloudPull(true);
    var applied=await waitCond(function(){return w.__sync.D.d.draw.count===6;},20000);
    T("远端改 draw 参数：已应用（定向应用）", applied, w.__sync.D.d.draw.count);
    T("远端改 draw：不重置进行中的抽签结果 A.result", !!(w.__sync.A&&w.__sync.A.result) && qa(f,"#aOut .rcell").length>0, w.__sync.A?String(w.__sync.A.result&&w.__sync.A.result.length):"");
    T("远端改 draw：输入框已同步", q(f,"#aCount").value==="6", q(f,"#aCount").value);

    /* 体测输入聚焦时：远端值只存数据、不写 DOM */
    tab(f,"ft");
    await pumpN(3);
    var fh=q(f,"#fH"); fh.focus(); fh.value="181"; fh.dispatchEvent(new Event("input",{bubbles:true}));
    await sleep(1700); /* 让这次本地改动先推送，确保稍后云端值才是「更新」的一方 */
    await sleep(200);
    var cur2=w.__mk.getUd()||{};
    if(cur2&&cur2.fit){
      cur2.at=cur2.at||{};
      cur2.at.fit=Date.now()+9000;
      cur2.fit.h="179";
      w.__mk.setUd(cur2);
    }
    w.__sync.cloudPull(true);
    var fitStored=await waitCond(function(){return w.__sync.D.d.fit.h==="179";},20000);
    T("体测输入聚焦时：远端 fit 只存数据不写 DOM", fitStored && q(f,"#fH").value==="181", w.__sync.D.d.fit.h+"/"+q(f,"#fH").value);
    try{fh.blur();}catch(e){}

    /* ============ E. 通知「标记已处理」：iframe 点击 → postMessage → 持久化/同步 ============ */
    tab(f,"nt");
    await waitCond(function(){return !!frame(f);},20000);
    await pumpN(3);
    idoc=frameDoc(f); iw=frame(f).contentWindow;
    var postsBeforeMarks=udPosts(f).length;
    var btnB=idoc?idoc.querySelector('[data-act="done"][data-gid="auto_g_testB"]'):null;
    T("iframe 内存在 testB「标记已处理」按钮", !!btnB, "");
    if(btnB)btnB.click();
    var gotTrue=await waitCond(function(){return markRows(f).some(function(r){return r&&r.kind==="ntdone"&&r.ref==="auto_g_testB"&&r.val===true;});},20000);
    var rowT=null;markRows(f).forEach(function(r){if(r&&r.ref==="auto_g_testB"&&r.val===true)rowT=r;});
    T("iframe 点击后写入 marks(kind=ntdone,val=true)", gotTrue, JSON.stringify(markRows(f).map(function(r){return r?r.ref+":"+r.kind+":"+r.val:null;})));
    T("marks 行结构符合契约（id/seat/kind/ref/val）", !!(rowT&&rowT.id===SID+"|ntdone|auto_g_testB"&&rowT.seat===SID&&rowT.kind==="ntdone"&&rowT.ref==="auto_g_testB"), rowT?JSON.stringify(rowT):"");
    T("父页 NT.done 已更新", !!(w.__sync.NT.done&&w.__sync.NT.done.auto_g_testB===true), JSON.stringify(w.__sync.NT.done));
    T("旧 AN_DONE 镜像已更新", !!(w.__sync.AN_DONE()&&w.__sync.AN_DONE().auto_g_testB===true), "");
    T("本地兜底 zq_auto_nt_done 已写入", (function(){try{var a=JSON.parse(lsGet("zq_auto_nt_done")||"{}");return !!a.auto_g_testB;}catch(e){return false;}})());
    T("iframe 内状态与父页一致（不重复 render 后仍为 true）", !!(iw.state&&iw.state.done&&iw.state.done.auto_g_testB===true), "");
    T("iframe 点击不会额外触发 userdata 推送", udPosts(f).length===postsBeforeMarks, udPosts(f).length+"/"+postsBeforeMarks);
    /* 模板已自行 render 并替换 DOM：第二次点击必须重新取按钮 */
    btnB=idoc?idoc.querySelector('[data-act="done"][data-gid="auto_g_testB"]'):null;
    if(btnB)btnB.click();
    var gotFalse=await waitCond(function(){return markRows(f).some(function(r){return r&&r.kind==="ntdone"&&r.ref==="auto_g_testB"&&r.val===false;});},20000);
    T("再次点击写入 marks(kind=ntdone,val=false)（不 DELETE）", gotFalse, "");
    T("取消后父页 NT.done 移除该组", !(w.__sync.NT.done&&w.__sync.NT.done.auto_g_testB===true), JSON.stringify(w.__sync.NT.done));
    T("取消后 iframe 状态同步为 false", !!(iw.state&&iw.state.done&&!iw.state.done.auto_g_testB), "");

    collect(f);

    /* ============ F. 坏 JSON 云端：不覆盖本机、不崩，本地改动写出合法 v6 ============ */
    clearUd(); lsSet("_sync_phase","bad");
    var f2=await mount(SRC,430,940), w2=f2.contentWindow;
    await waitCond(function(){return w2.__sync&&w2.__sync.D&&w2.__sync.D.d&&w2.__sync.D.d.seat;},20000);
    w2.__sync.cloudPull(true);
    await pumpN(30);
    T("云端坏 JSON：页面不崩、回到班级", w2.__sync.D.d.seat===SID, String(w2.__sync.D.d.seat));
    T("云端坏 JSON：不覆盖本机数据（保留本机 homeTools 顺序）", w2.__sync.D.d.homeTools[0]==="roll", JSON.stringify(w2.__sync.D.d.homeTools));
    T("云端坏 JSON：0 JS 报错", errsOf(f2).length===0, errsOf(f2).join(" | "));
    setV(f2,"#fH","190");
    await sleep(300);
    await waitPost(f2,1);
    var badPosts=udPosts(f2);
    T("云端坏 JSON 后本地改动仍写出 POST", badPosts.length>=1, badPosts.length);
    var bb=null;try{bb=JSON.parse(JSON.parse(badPosts[0].body)[0].blob);}catch(e){bb=null;}
    T("坏 JSON 后写出的 blob 为合法 v6（11 section/14 键/at 全量）", !!bb && bb.v===6 && Object.keys(bb).length===14 && typeof bb.at.fit==="number", bb?Object.keys(bb).join(","):"");
    T("坏 JSON 后写出的 blob 带上本机既有 section", !!bb && bb.fit.h==="190" && bb.homeTools[0]==="roll", bb?JSON.stringify(bb.fit.h):"");
    collect(f2);

    /* ============ G. 断网/推失败：保留待补发，恢复后自动重试 ============ */
    lsSet("_sync_phase","off"); clearUd();
    var f3=await mount(SRC,430,940), w3=f3.contentWindow;
    await waitCond(function(){return w3.__sync&&w3.__sync.D&&w3.__sync.D.d&&w3.__sync.D.d.seat;},20000);
    w3.__sync.cloudPull(true);
    var pulled3=await waitCond(function(){return w3.__sync.D.d.homeTools.join(",")==="hw,nt,ft,draw";},20000);
    T("离线场景：远端 mp blob 已应用（基准）", pulled3);
    w3.__mk.failUdPost=true;
    setV(f3,"#fH","195");
    await sleep(300);
    w3.__sync.cloudPull(true); /* 拉取→补推送：触发一次会失败的 POST */
    var pend=await waitCond(function(){return lsGet("zq_udpend_"+SID)==="1";},20000);
    T("推送失败：保留待补发标记 zq_udpend", pend, lsGet("zq_udpend_"+SID));
    T("推送失败：不产生成功的 POST", udPosts(f3).length===0, udPosts(f3).length);
    w3.__mk.failUdPost=false;
    w3.__sync.cloudPull(true);
    var retried=await waitCond(function(){return udPosts(f3).length>=1 && lsGet("zq_udpend_"+SID)===null;},25000);
    T("恢复后自动重试：POST 成功且清除 pending", retried, udPosts(f3).length+"/"+lsGet("zq_udpend_"+SID));
    var rb=null;try{rb=JSON.parse(JSON.parse(udPosts(f3)[0].body)[0].blob);}catch(e){rb=null;}
    T("重试 blob 带最新 fit 值", !!rb && rb.fit.h==="195", rb?rb.fit.h:"");
    T("断网重试：0 JS 报错", errsOf(f3).length===0, errsOf(f3).join(" | "));
    collect(f3);

    /* ============ I. 管理员「自动采用教务课表」不算用户改动：不得产生 tt 推送 ============ */
    clearUd(); lsSet("_sync_admin","1"); lsSet("_sync_phase","boot");
    var f4=await mount(SRC,430,940), w4=f4.contentWindow;
    await waitCond(function(){return w4.__sync&&w4.__sync.D&&w4.__sync.D.d&&w4.__sync.D.d.seat;},20000);
    w4.__sync.cloudPull(true);
    var ttPulled=await waitCond(function(){return lsGet("zq_udcache_"+SID)!==null&&w4.__sync.D.d.ttUseMine===true&&w4.__sync.D.d.termStart==="2026-09-07";},20000);
    T("管理员场景：远端 tt 偏好已应用（ttUseMine/termStart）", ttPulled, w4.__sync.D.d.ttUseMine+"/"+w4.__sync.D.d.termStart);
    T("管理员场景：身份识别为管理员（自动采用逻辑可达）", w4.__sync.AUTH.is_admin===true, String(w4.__sync.AUTH.is_admin));
    /* 先抑制后续自动拉取（避免后台拉取把自动采用值冲回云端旧值），再验证 adopt 不推送 */
    lsSet("zq_udat_"+SID,String(Date.now()+3600000));
    /* 模拟管理员首次进入（本机还没有课表）→ 后台自动采用教务课表 */
    w4.__sync.D.d.course=[];w4.__sync.D.d.ttAdopt="";
    try{await w4.__sync.ttSyncPull({force:true});}catch(e){}
    var adopted=await waitCond(function(){return (w4.__sync.D.d.course||[]).length>0&&!!w4.__sync.D.d.ttAdopt;},20000);
    T("管理员自动采用教务课表：已写入本机 course/ttAdopt", adopted, (w4.__sync.D.d.course||[]).length+"/"+!!w4.__sync.D.d.ttAdopt);
    T("自动采用后本机 ttUseMine/termStart 为本机值", w4.__sync.D.d.ttUseMine===false&&w4.__sync.D.d.termStart==="2026-08-31", w4.__sync.D.d.ttUseMine+"/"+w4.__sync.D.d.termStart);
    await sleep(2000); /* 超过 1200ms 防抖窗口 */
    T("自动采用教务课表：1.5s+ 内不产生 userdata 推送", udPosts(f4).length===0, udPosts(f4).length);
    T("自动采用后 UD 基线与本机 tt 一致（rebaseline，不排推送）", (function(){
      try{var c=JSON.parse(lsGet("zq_udcache_"+SID)||"null");return !!c&&JSON.stringify(c.tt)===JSON.stringify(w4.__sync.UD.sections().tt);}catch(e){return false;}
    })(), "");
    /* 用户显式切换周/日视图：仍要正常同步 */
    w4.__sync.gotoTab("tt");
    await pumpN(6);
    var btnW=q(f4,'[data-ttview="week"]');
    T("课表存在周视图按钮", !!btnW, "");
    if(btnW)btnW.click();
    await sleep(300);
    await waitPost(f4,1);
    T("用户显式改 ttView → 正常推送", udPosts(f4).length>=1, udPosts(f4).length);
    var tb=null;try{tb=JSON.parse(JSON.parse(udPosts(f4)[0].body)[0].blob);}catch(e){tb=null;}
    T("推送 blob.tt 仅含契约 4 字段且 ttView=week", !!tb&&tb.tt.ttView==="week"&&Object.keys(tb.tt).join(",")==="ttView,ttUseMine,ttLocal,termStart", tb?JSON.stringify(tb.tt):"");
    T("ttAdopt/ttSyncAt/course 不进 blob", !!tb&&!("ttAdopt" in tb)&&!("ttSyncAt" in tb)&&!("course" in tb), "");
    collect(f4);
    lsDel("_sync_admin");

    /* ============ J. 远端 v5：pull 后必须写回 v6（契约 §3.3），且幂等 ============ */
    clearUd(); lsSet("_sync_phase","v5");
    var f5=await mount(SRC,430,940), w5=f5.contentWindow;
    await waitCond(function(){return w5.__sync&&w5.__sync.D&&w5.__sync.D.d&&w5.__sync.D.d.seat;},20000);
    w5.__sync.cloudPull(true);
    var wrote5=await waitCond(function(){return udPosts(f5).length>=1;},25000);
    T("远端 v5：pull 后自动写回 v6（1 次 POST）", wrote5&&udPosts(f5).length===1, udPosts(f5).length);
    var vb5=null;try{vb5=JSON.parse(JSON.parse(udPosts(f5)[0].body)[0].blob);}catch(e){vb5=null;}
    T("v5 写回 blob.v===6（不再写 v5）", !!vb5&&vb5.v===6, vb5?String(vb5.v):"");
    T("v5 写回保留 homeTools/fit 的 v5 值", !!vb5&&JSON.stringify(vb5.homeTools)===JSON.stringify(FX.v5.homeTools)&&JSON.stringify(vb5.fit)===JSON.stringify(FX.v5.fit), vb5?JSON.stringify(vb5.homeTools)+"/"+JSON.stringify(vb5.fit).slice(0,80):"");
    T("v5 写回：homeToolsAt 镜像 + at.homeTools=v5 homeToolsAt + at.fit=0", !!vb5&&vb5.homeToolsAt===vb5.at.homeTools&&vb5.at.homeTools===1762200000000&&vb5.at.fit===0, vb5?vb5.at.homeTools+"/"+vb5.homeToolsAt+"/"+vb5.at.fit:"");
    T("v5 写回：其余 section 齐备（11 键/at 全量）", !!vb5&&["draw","group","roster","hide","tt","prefs","nick","power","water"].every(function(k){return vb5[k]!==undefined&&typeof vb5.at[k]==="number";}), vb5?Object.keys(vb5).join(","):"");
    var n5=udPosts(f5).length;
    w5.__sync.cloudPull(true); /* 云端已是 v6：不应再写 */
    await pumpN(40);
    await sleep(400);
    T("v5 写回幂等：再次 pull 不再 POST", udPosts(f5).length===n5, udPosts(f5).length+"/"+n5);
    collect(f5);

    /* ============ K. 旧数据无 water（v6 但第 11 section 缺失）：默认 {rooms:{}}，不报错 ============ */
    /* 先卸掉旧 iframe 并等其卸载时的 D.save 落定，再清本机数据（否则旧实例会把 water 写回 zq_tools_v2） */
    try{var oldFr=document.getElementById("fr");if(oldFr&&oldFr.parentNode)oldFr.parentNode.removeChild(oldFr);}catch(e){}
    await sleep(150);
    clearUd(); lsDel("zq_tools_v2"); lsDel("zq_tools_v2_"+SID); lsSet("_sync_phase","oldwo");   /* 清 D 本机数据 = 新设备场景（登录后键为 zq_tools_v2_<sid>） */
    var f6=await mount(SRC,430,940), w6=f6.contentWindow;
    await waitCond(function(){return w6.__sync&&w6.__sync.D&&w6.__sync.D.d&&w6.__sync.D.d.seat;},20000);
    w6.__sync.cloudPull(true);
    var pulled6=await waitCond(function(){return w6.__sync.D.d.homeTools.join(",")==="hw,nt,ft,draw";},20000);
    await pumpN(20);
    var dw6=w6.__sync.D.d.water;
    T("旧数据无 water：拉取后 D.d.water 默认 {rooms:{}}", !!(dw6&&dw6.rooms&&typeof dw6.rooms==="object"&&Object.keys(dw6.rooms).length===0), JSON.stringify(dw6));
    T("旧数据无 water：其余 section 正常应用（不覆盖）", !!pulled6&&w6.__sync.D.d.draw.count===10&&w6.__sync.D.d.fit.h==="178", w6.__sync.D.d.homeTools.join(",")+"/"+w6.__sync.D.d.draw.count);
    T("旧数据无 water：本机视图 water={rooms:{}}（14 键契约仍成立）", (function(){try{var s=w6.__sync.UD.sections();return !!(s.water&&s.water.rooms&&Object.keys(s.water.rooms).length===0);}catch(e){return false;}})(), "");
    T("旧数据无 water：0 JS 报错", errsOf(f6).length===0, errsOf(f6).join(" | "));
    collect(f6);
    lsDel("_sync_phase");

    /* ============ H. 汇总 ============ */
    R.diag.getUd=count(f,"userdata");R.diag.postUd=count(f,"userdata_post");
    R.diag.marksGet=count(f,"marks");R.diag.marksPost=count(f,"marks_post");
    R.diag.fixtures=JSON.stringify(w.__sync.fixtures).length;
    T("全程 0 console.error", ALLCERR.length===0, ALLCERR.slice(0,5).join(" | "));
    T("全程 0 JS 报错", ALLERR.length===0, ALLERR.slice(0,5).join(" | "));
    T("全程无外部请求", ALLEXT.length===0, ALLEXT.slice(0,5).join(" | "));
  }catch(e){
    R.steps.push({k:"脚本执行异常",ok:false,note:String(e&&e.stack||e)});
  }
  report("func",R);
}
run();
"""

def build_harness(name):
    body = COMMON_JS.replace("__SRC__", PREVIEW).replace("__SID__", SID) + "\n" + FUNC_JS
    html = ("<!doctype html><html><head><meta charset=\"utf-8\"><title>sync check</title>"
            "<style>html,body{margin:0;background:#DDD6C8;overflow:hidden}iframe{background:#fff}</style></head><body>"
            "<script>" + body.replace("</script", "<\\/script") + "</script></body></html>")
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as fh:
        fh.write(html)


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        qs = urllib.parse.urlparse(self.path).query
        m = re.search(r"slot=([A-Za-z0-9_\-]+)", qs)
        slot = m.group(1) if m else "default"
        os.makedirs(REPORT_DIR, exist_ok=True)
        open(os.path.join(REPORT_DIR, slot + ".json"), "wb").write(body)
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


class Q(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_edge(url, budget=220000, window="492,940", timeout=300):
    prof = tempfile.mkdtemp(prefix="edgeprof_", dir=REPORT_DIR)
    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--force-device-scale-factor=1", "--window-size=" + window,
            "--virtual-time-budget=%d" % budget, "--user-data-dir=" + prof, url]
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def wait_report(slot, secs=120):
    p = os.path.join(REPORT_DIR, slot + ".json")
    t0 = time.time()
    while time.time() - t0 < secs:
        if os.path.exists(p):
            time.sleep(0.15)
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                time.sleep(0.2)
        time.sleep(0.2)
    return None


STATIC_CHECKS = []


def static_checks(html):
    main = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    slim = re.sub(r'var NOTICE_TPL_B64="[^"]*"', 'var NOTICE_TPL_B64="";', main)

    def no(pat, label):
        STATIC_CHECKS.append((label, not re.search(pat, slim), ""))

    no(r"=\s*>\s*|\barrow\b|=>", "主脚本无箭头函数（ES5 兼容）")
    no(r"\bconst\s+[A-Za-z_$]", "主脚本无 const（ES5 兼容）")
    no(r"\blet\s+[A-Za-z_$]", "主脚本无 let（ES5 兼容）")
    no(r"\basync\s+function\b|\bawait\s+", "主脚本无 async/await（ES5 兼容）")
    no(r"\?\.", "主脚本无可选链（ES5 兼容）")
    no(r"\?\?", "主脚本无 ??（ES5 兼容）")
    no(r'type\s*=\s*"module"', "无 ES module / 构建链")
    ext = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    STATIC_CHECKS.append(("零外部资源引用（src/href 无 http/https）", len(ext) == 0, str(ext[:3])))
    STATIC_CHECKS.append(("UD v6 模块存在（merge/pull/push/touch/apply/off）",
                          ("var UD={" in main) and ("merge:function" in main) and ("off:function" in main), ""))
    STATIC_CHECKS.append(("UD 本机缓存键 zq_udcache_/zq_udpend_/zq_udat_",
                          all(k in main for k in ("zq_udcache_", "zq_udpend_", "zq_udat_")), ""))
    STATIC_CHECKS.append(("合并结果含 11 section + homeToolsAt 顶层镜像",
                          all(('"%s"' % k) in main for k in ("homeTools", "fit", "draw", "group", "roster", "hide", "tt", "prefs", "nick", "power", "water"))
                          and "out.homeToolsAt=out.at.homeTools" in main, ""))
    STATIC_CHECKS.append(("power section 进 v6（UD_KEYS/UD_DEF/sections/apply 均接入；sections 前 bootRestore 兜底）",
                          ('"power","water"]' in main) and ('power:{sel:"",at:0,low:30}' in main)
                          and ('out.power=(function()' in main) and ('P&&P.bootRestore' in main)
                          and ('POWER.applyRemote' in main), ""))
    STATIC_CHECKS.append(("water section 进 v6（UD_KEYS/UD_DEF/sections 归一/apply 接入、值内不镜像 at）",
                          ('"power","water"]' in main) and ('water:{rooms:{}}' in main)
                          and ('WATER.normWater(d.water)' in main) and ('WATER.applyRemote' in main)
                          and ('out.water=(typeof WATER' in main), ""))
    STATIC_CHECKS.append(("marks 支持 kind=ntdone", 'x.kind==="ntdone"' in main and 'NT.done=nd' in main, ""))
    STATIC_CHECKS.append(("通知 iframe done 注入 + 点击捕获 postMessage",
                          "__zqApplyDone" in main and "class-notice-done" in main, ""))
    STATIC_CHECKS.append(("旧 zq_auto_nt_done 一次性迁移（migratedMark ntdone）",
                          'migratedMark("ntdone")' in main and 'localStorage.removeItem("zq_auto_nt_done")' in main, ""))
    STATIC_CHECKS.append(("D.save 脏检测 → UD.touch", "UD.touch" in main, ""))
    STATIC_CHECKS.append(("推送防抖 1200ms", "UD.pushSoon" in main and "},1200);" in main, ""))
    STATIC_CHECKS.append(("拉取前记录脏 section（拉取后补推送）", "var wasDirty=base?UD.dirtySections():[];" in main, ""))
    STATIC_CHECKS.append(("后台自动采用教务课表后重设 tt 基线（不跨端污染同步偏好）",
                          "UD.rebaseline" in main and 'UD.rebaseline("tt")' in main, ""))
    STATIC_CHECKS.append(("tt section 仅 4 个契约字段（ttAdopt/ttSyncAt 不同步）",
                          'out.tt={ttView:String(d.ttView||""),ttUseMine:!!d.ttUseMine,ttLocal:d.ttLocal?UD.clone(d.ttLocal):null,termStart:String(d.termStart||"")};' in main, ""))
    STATIC_CHECKS.append(("远端 v5 拉取后写回 v6（wasV5 → push）",
                          "var wasV5=!!(remote&&Number(remote.v)===5);" in main and "if(wasV5||" in main, ""))
    STATIC_CHECKS.append(("userdata POST 走 upsert（merge-duplicates）",
                          '"return=representation,resolution=merge-duplicates"' in main and 'CB+"userdata"' in main, ""))
    STATIC_CHECKS.append(("cloudPull/bootRefresh 接入 UD.pull",
                          "UD.pull(force)" in main and "UD.bootPull()" in main, ""))
    STATIC_CHECKS.append(("文案已更新（无「抽签/点名等只存本机、不会上传、仅本机备份」旧口径）",
                          all(s not in html for s in ("抽签、分组、点名等数据只存本机", "名单与记录只存本机",
                                                       "不会上传", "仅本机备份")), ""))


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    for fn in os.listdir(REPORT_DIR):
        try:
            os.remove(os.path.join(REPORT_DIR, fn))
        except Exception:
            pass
    html = open(SRC, encoding="utf-8").read()
    static_checks(html)
    build_preview()
    build_harness(H_FUNC)
    httpd = Q(("127.0.0.1", PORT), functools.partial(Handler, directory=HERE))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    results = []
    try:
        data = None
        for attempt in range(2):
            rep = os.path.join(REPORT_DIR, "func.json")
            if os.path.exists(rep):
                os.remove(rep)
            last = run_edge(BASE + H_FUNC)
            data = wait_report("func")
            if data:
                break
            time.sleep(0.3)
        if not data:
            results.append(("功能 未返回结果", False, "report 缺失（浏览器未上报，可能脚本异常/超时）"))
            if last is not None and os.environ.get("SYNC_DEBUG"):
                print("[DEBUG] rc=%s stderr=%s" % (last.returncode, (last.stderr or b"").decode("utf-8", "replace")[-1500:]))
        else:
            for s in data.get("steps", []):
                results.append((s.get("k", "?"), bool(s.get("ok")), str(s.get("note", ""))))
            diag = data.get("diag") or {}
            if diag:
                print("[diag] " + json.dumps(diag, ensure_ascii=False)[:6000])
    finally:
        httpd.shutdown()
    for name, ok, note in STATIC_CHECKS:
        results.insert(0, ("[静态] " + name, bool(ok), note))
    fails = [r for r in results if not r[1]]
    for name, ok, note in results:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  -- " + note[:240]) if (note and not ok) else ""))
    print("")
    print("=" * 60)
    print("sync_check: %d 项，PASS %d，FAIL %d" % (len(results), len(results) - len(fails), len(fails)))
    print("=" * 60)
    return 0 if not fails else 1


def cleanup():
    for f in (PREVIEW, H_FUNC):
        try:
            os.remove(os.path.join(HERE, f))
        except Exception:
            pass


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    sys.exit(code)
