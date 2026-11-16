#!/usr/bin/env node
/*
 * 通知时间显示契约单测（2026-11-05 契约 §2/§3）
 *
 * 做法：从 build_notice_board.py 里提取模板 JS（r""" ... """），用 vm + 假 DOM 加载，
 * 注入固定 GROUPS fixture，并把 Date.now 固定为北京时间 2026-11-05 23:00（周四）。
 *
 * 运行： node C:\Users\Ko_Li\.openclaw\workspace\briefdesk-plan\tests\notice_display_test.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const PY = path.resolve(__dirname, '..', 'build_notice_board.py');
const src = fs.readFileSync(PY, 'utf8');

const tag = 'JS = r"""';
const start = src.indexOf(tag);
if (start < 0) throw new Error('build_notice_board.py 里找不到 JS 字符串');
const jsStart = start + tag.length;
const jsEnd = src.indexOf('"""', jsStart);
if (jsEnd < 0) throw new Error('JS 字符串没有结束');
let js = src.slice(jsStart, jsEnd);

/* ---------------- 固定 now = 2026-11-05T23:00+08:00 ---------------- */
const FIXED = Date.parse('2026-11-05T23:00:00+08:00');
const RealDate = Date;
class FakeDate extends RealDate {
  constructor(...args) {
    if (args.length === 0) super(FIXED);
    else super(...args);
  }
  static now() { return FIXED; }
  static parse(s) { return RealDate.parse(s); }
  static UTC(...a) { return RealDate.UTC(...a); }
}

/* ---------------- 期望值用本机时区动态计算，避免测试依赖机器 TZ ---------------- */
function pad(n) { return n < 10 ? '0' + n : '' + n; }
function abs(epoch) {
  const d = new RealDate(epoch);
  return (d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}
const ANCHOR = new RealDate(2026, 10, 5, 20, 47, 0); // 11-05 20:47（item.time 锚点）
function anchorMd(offsetDays) {
  const d = new RealDate(ANCHOR.getFullYear(), ANCHOR.getMonth(), ANCHOR.getDate() + offsetDays, 12, 0, 0);
  return (d.getMonth() + 1) + '-' + pad(d.getDate());
}
function md(ts) {
  const d = new RealDate(ts);
  return (d.getMonth() + 1) + '-' + pad(d.getDate());
}
function daysFromNow(ts) { return Math.max(1, Math.ceil((ts - FIXED) / 86400000)); }
function hoursFromNow(ts) { return Math.max(1, Math.ceil((ts - FIXED) / 3600000)); }
function minsFromNow(ts) { return Math.max(1, Math.ceil((ts - FIXED) / 60000)); }

/* ---------------- 固定稿件 ---------------- */
const GROUPS = [
  {
    id: 'g_deadline', cat: '班级事务', title: '申报材料报送提醒',
    deadline: '2026-11-06T12:00:00+08:00', deadlineAction: '报送姓名截止',
    items: [{ kind: 'text', label: '原始消息', time: '11-05 20:47', from: '陈玉霞',
      text: '请申报的同学明天中午前报送姓名，周日晚点名时需要提交材料！' }],
    aiSummary: '请申报的同学明天中午前报送姓名，周日晚点名时需要提交材料！',
    aiPoints: ['明天中午前报送姓名'],
  },
  {
    id: 'g_signup_future', cat: '活动', title: '药膳答题打卡活动报名',
    deadline: '2026-11-07T18:00:00+08:00', deadlineAction: '报名截止',
    signupStart: '2026-11-07T12:00:00+08:00', signupEnd: '2026-11-07T18:00:00+08:00',
    items: [{ kind: 'text', time: '11-05 12:37', text: '报名时间：2026年11月7日12:00—18:00' }],
  },
  {
    id: 'g_signup_open', cat: '活动', title: '药膳报名进行中',
    deadline: '2026-11-09T18:00:00+08:00', deadlineAction: '报名截止',
    signupStart: '2026-11-05T12:00:00+08:00', signupEnd: '2026-11-07T18:00:00+08:00',
    items: [{ kind: 'text', time: '11-05 10:00', text: '报名时间：2026年11月5日12:00—18:00' }],
  },
  {
    id: 'g_signup_expired', cat: '活动', title: '惜粮手抄报活动通知',
    deadline: '2026-11-12T20:00:00+08:00', deadlineAction: '投稿截止',
    signupStart: '2026-11-03T12:00:00+08:00', signupEnd: '2026-11-03T20:30:00+08:00',
    items: [{ kind: 'text', time: '11-02 10:46', text: '收集表报名时间：11月3日12:00-20:30' }],
  },
  {
    id: 'g_signup_start_only', cat: '活动', title: '骨伤学院运动会作品征集',
    deadline: '2026-11-08T00:00:00+08:00', deadlineAction: '提交截止',
    signupStart: '2026-11-05T12:00:00+08:00', signupEnd: null,
    items: [{ kind: 'text', time: '11-04 10:00', text: '11 月 5 日 12:00 开放QQ群聊，进群后填写收集表' }],
  },
  {
    id: 'g_deadline_past', cat: '活动', title: '校运动会观众征集',
    deadline: '2026-11-03T18:30:00+08:00', deadlineAction: '报名截止',
    items: [{ kind: 'text', time: '11-03 14:03', text: '截止今天六点半' }],
  },
  {
    id: 'g_alert', cat: '活动', title: '校运动会志愿者补招通知',
    deadline: '2026-11-02T18:00:00+08:00', deadlineAction: '报名截止',
    signupEnd: '2026-11-02T18:00:00+08:00',
    alert: '报名已于 11-02 18:00 截止；19:25 群内发布了补录结果名单',
    items: [{ kind: 'text', time: '10-31 10:12', text: '补录结果名单已发布' }],
  },
  {
    id: 'g_recur', cat: '班级事务', title: '宿舍卫生检查',
    recurrence: { freq: 'monthly_weeks', weekday: 3, weeks: [1, 2, 3], time: '17:30', label: '每月前三周 周三 17:30' },
    items: [{ kind: 'text', time: '11-03 09:13', text: '每月前三周的周三下午 5:30 检查' }],
  },
  {
    id: 'g_event', cat: '活动', title: '运动会观众明早集合点名',
    eventAt: '2026-11-06T08:50:00+08:00', eventAction: '集合点名',
    items: [{ kind: 'text', time: '11-05 18:41', text: '明天上午 8:50 到院大本营点名' }],
  },
  {
    id: 'g_none', cat: '教务', title: '运动会期间晚自习正常',
    items: [{ kind: 'text', time: '11-04 14:03', text: '运动会期间晚自习正常' }],
  },
  {
    id: 'g_ai_merged', cat: '班级事务', title: '申报材料报送提醒',
    deadline: '2026-11-06T12:00:00+08:00', deadlineAction: '报送姓名截止',
    eventAt: '2026-11-08T19:00:00+08:00', eventAction: '集合点名',
    aiSummary: '申报同学11-06 中午前报送姓名，11-08 晚点名时提交材料。',
    aiMerged: true, supplement: true, updatedAt: '2026-11-05T21:07:00+08:00',
    items: [
      { kind: 'text', label: '通知', time: '11-05 20:47', from: '陈玉霞',
        text: '请申报的同学明天中午前报送姓名，周日晚点名时需要提交材料！' },
      { kind: 'text', label: '通知', time: '11-05 21:07', from: '陈玉霞',
        text: '电子版材料需要在周日下午十四点发给我' },
      { kind: 'text', label: '通知', time: '11-05 21:07', from: '陈玉霞', text: '纸质版晚点名交' },
    ],
  },
  {
    id: 'g_single_summary', cat: '班级事务', title: '单条消息卡',
    deadline: '2026-11-06T12:00:00+08:00', deadlineAction: '报送姓名截止',
    aiSummary: '摘要：请明天中午前报送姓名。',
    items: [{ kind: 'text', label: '通知', time: '11-05 20:47', from: '陈玉霞',
      text: '原始正文：请申报的同学明天中午前报送姓名。' }],
  },
  {
    id: 'g_reltext', cat: '班级事务', title: '相对日期用例',
    items: [{ kind: 'text', time: '11-05 20:47',
      text: '本周日晚上点名，下周一交材料；今晚之前提交；后天体检；大后天放假；周三开会；课表以今日校园为准；每月前三周的周三 17:30 检查。' }],
  },
  {
    id: 'g_title_bare', cat: '活动', title: '下午招聘会请准时到场',
    eventAt: '2026-11-05T14:00:00+08:00', eventAction: '活动开始',
    aiSummary: '下午招聘会请各班同学准时到场。',
    aiPoints: ['下午', '招聘会'],
    items: [{ kind: 'text', time: '11-05 13:00', text: '下午的招聘会请各班同学准时到场' }],
  },
  {
    id: 'g_dayno', cat: '活动', title: '运动会5号比赛项目及名单',
    items: [{ kind: 'text', time: '11-05 09:00', text: '5号上午9:10 比赛项目名单' }],
  },
  {
    id: 'g_bracket', cat: '活动', title: '11月14日（下周六）献血活动',
    deadline: '2026-11-14T09:00:00+08:00', deadlineAction: '报名截止',
    aiSummary: '11月14日（11-14）献血活动，本周六（明天）报名截止。',
    items: [{ kind: 'text', time: '11-05 10:18', text: '献血活动 11月14日（11-14）' }],
  },
  {
    id: 'g_link_rel', cat: '活动', title: '献血活动通知',
    aiSummary: '11月14日献血活动，欢迎参加。',
    items: [{ kind: 'link', label: '链接', name: '11月14日（下周六）献血活动', url: 'https://example.com/x',
      time: '11-05 10:18' }],
  },
  {
    id: 'g_groupname', cat: '班级事务', title: '太极拳体测补测通知',
    group: '26级周一89节太极拳', source: 'QQ 群 · 26级周一89节太极拳',
    items: [{ kind: 'text', time: '10-30 11:33', text: '本周六（明天）上午 10 点 40 分到篮球场集合。' }],
  },
];

/* ---------------- 假 DOM ---------------- */
function fakeEl() {
  const el = {
    textContent: '', innerHTML: '', className: '', value: '',
    style: {}, scrollHeight: 0, offsetHeight: 0,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    appendChild() {}, removeChild() {}, setAttribute() {}, getAttribute() { return null; },
    hasAttribute() { return false; }, closest() { return null; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; },
    scrollIntoView() {}, focus() {}, select() {},
  };
  return el;
}
const domCache = new Map();
function elFor(key) {
  if (!domCache.has(key)) domCache.set(key, fakeEl());
  return domCache.get(key);
}
const documentStub = {
  querySelector(sel) { return elFor('q:' + sel); },
  querySelectorAll() { return []; },
  getElementById(id) { return elFor('id:' + id); },
  createElement() { return fakeEl(); },
  addEventListener() {},
  body: { appendChild() {}, removeChild() {} },
};
const windowStub = {
  innerWidth: 1280,
  addEventListener() {},
  scrollTo() {},
  parent: undefined,
};
const sandbox = {
  console,
  Date: FakeDate,
  JSON, Math, Object, Array, String, Number, Boolean, RegExp, Error, isNaN,
  parseInt, parseFloat, encodeURIComponent, decodeURIComponent, setTimeout, clearTimeout,
  setInterval: () => 0, clearInterval: () => {},
  document: documentStub,
  window: windowStub,
  location: { search: '', hash: '' },
  navigator: {},
  confirm: () => false,
};

/* 注入 fixture */
js = js.replace('__DATA__', JSON.stringify(GROUPS))
       .replace('__FORMS__', '{}')
       .replace('__HOMEWORK__', '[]')
       .replace('__SCHEDULE__', '[]');

const ctx = vm.createContext(sandbox);
vm.runInContext(js, ctx, { filename: 'notice-board-template.js' });

/* ---------------- 断言工具 ---------------- */
let pass = 0, fail = 0;
const failures = [];
function eq(name, actual, expected) {
  if (actual === expected) { pass++; console.log('PASS ' + name); }
  else { fail++; failures.push(name); console.log('FAIL ' + name + '\n  expected: ' + JSON.stringify(expected) + '\n  actual  : ' + JSON.stringify(actual)); }
}
function ok(name, cond) { eq(name, !!cond, true); }
function contains(name, hay, needle) {
  const good = typeof hay === 'string' && hay.indexOf(needle) >= 0;
  if (good) { pass++; console.log('PASS ' + name); }
  else { fail++; failures.push(name); console.log('FAIL ' + name + '\n  expected to contain: ' + JSON.stringify(needle) + '\n  actual: ' + JSON.stringify(String(hay).slice(0, 600))); }
}
function notContains(name, hay, needle) {
  const good = typeof hay === 'string' && hay.indexOf(needle) < 0;
  if (good) { pass++; console.log('PASS ' + name); }
  else { fail++; failures.push(name); console.log('FAIL ' + name + '\n  should NOT contain: ' + JSON.stringify(needle)); }
}
function groupById(id) { return GROUPS.filter(g => g.id === id)[0]; }
function st(id) { return ctx.statusOf(groupById(id)); }

console.log('---- §2.1 fmtWhen 阈值（now = 2026-11-05 23:00 +08:00）----');
eq('fmtWhen 30 分钟后', ctx.fmtWhen(FIXED + 30 * 60000), '30 分钟后');
eq('fmtWhen 恰好 1 小时后', ctx.fmtWhen(FIXED + 3600 * 1000), '1 小时后');
eq('fmtWhen 13 小时后', ctx.fmtWhen(Date.parse('2026-11-06T12:00:00+08:00')), '13 小时后');
eq('fmtWhen 2 天后（24h<=x<7d，ceil）', ctx.fmtWhen(Date.parse('2026-11-07T12:00:00+08:00')), daysFromNow(Date.parse('2026-11-07T12:00:00+08:00')) + ' 天后');
eq('fmtWhen ≥7 天用绝对时间', ctx.fmtWhen(Date.parse('2026-11-15T23:59:00+08:00')), abs(Date.parse('2026-11-15T23:59:00+08:00')));
eq('fmtWhen 已过用绝对时间', ctx.fmtWhen(Date.parse('2026-11-04T08:10:00+08:00')), '11-04 08:10');

console.log('---- §2.2 statusOf：「时间 + 动作」+ 报名优先 ----');
const sDeadline = st('g_deadline');
eq('申报材料 chip 相对化（§0.2 短动作）', sDeadline.label, '13 小时后 报送截止');
eq('申报材料 key 不变（13h<24h → today）', sDeadline.key, 'today');
notContains('明天 12:00 不再显示「今天」', sDeadline.label, '今天');
const sFuture = st('g_signup_future');
eq('报名未开始：报名开始', sFuture.label, daysFromNow(Date.parse('2026-11-07T12:00:00+08:00')) + ' 天后 报名开始');
eq('报名未开始 key=soon', sFuture.key, 'soon');
eq('报名进行中：报名截止', st('g_signup_open').label, daysFromNow(Date.parse('2026-11-07T18:00:00+08:00')) + ' 天后 报名截止');
const sFood = st('g_signup_expired');
eq('报名已过：报名截止（§0.2 不带「已」）', sFood.label, '11-03 20:30 报名截止');
eq('报名已过 key=expired', sFood.key, 'expired');
const sStartOnly = st('g_signup_start_only');
eq('只有 signupStart 且已过 → 回落 deadline', sStartOnly.label, daysFromNow(Date.parse('2026-11-08T00:00:00+08:00')) + ' 天后 提交截止');
eq('只有 signupStart 且已过 → key 走截止', sStartOnly.key, 'soon');
eq('已过 deadline：绝对时间+动作', st('g_deadline_past').label, '11-03 18:30 报名截止');
eq('已过 deadline key=expired', st('g_deadline_past').key, 'expired');
eq('alert 例外保留', st('g_alert').label, '已截止 · 有新名单');
contains('长期安排', st('g_recur').label, '长期安排 · 每月前三周');
eq('eventAt：时间+动作（§0.2 点名）', st('g_event').label, hoursFromNow(Date.parse('2026-11-06T08:50:00+08:00')) + ' 小时后 点名');
eq('eventAction 活动开始→开始', st('g_title_bare').label, '11-05 14:00 开始');
eq('无时间', st('g_none').label, '无时间');
eq('无时间 key', st('g_none').key, 'none');
/* A7 格式断言：所有有时间的未处理卡 chip 匹配 `^(N 分钟后|N 小时后|N 天后|MM-DD HH:MM) .+$` */
const A7 = /^(?:\d+ 分钟后|\d+ 小时后|\d+ 天后|\d{1,2}-\d{2} \d{2}:\d{2}) .+$/;
['g_deadline', 'g_signup_future', 'g_signup_open', 'g_signup_start_only', 'g_event', 'g_title_bare'].forEach(id => {
  ok('A7 格式 ' + id + ' → ' + st(id).label, A7.test(st(id).label));
});
ok('A7 报名已过格式', A7.test(st('g_signup_expired').label));
/* §0.2：所有 fixture chip 的动作部分 ≤6 字 */
GROUPS.forEach(g => {
  const stt = ctx.statusOf(g);
  if (stt.key === 'recur' || stt.key === 'none' || stt.key === 'alert' || stt.key === 'done') return;
  const m = /^(?:\d+ 分钟后|\d+ 小时后|\d+ 天后|\d{1,2}-\d{2} \d{2}:\d{2}) (.+)$/.exec(stt.label);
  ok('§0.2 动作≤6字 ' + g.id + ' → ' + (m ? m[1] : stt.label), !!m && m[1].length <= 6);
});

console.log('---- §3 absRelDates 相对日期替换（锚点 11-05 20:47）----');
const REL = ctx.absRelDates;
eq('明天中午前 → MM-DD 中午前',
  REL('请申报的同学明天中午前报送姓名，周日晚点名时需要提交材料！', '11-05 20:47'),
  '请申报的同学' + anchorMd(1) + ' 中午前报送姓名，' + anchorMd(3) + ' 晚点名时需要提交材料！');
eq('本周日/下周一',
  REL('本周日晚上点名，下周一交材料', '11-05 20:47'),
  anchorMd(3) + ' 晚上点名，' + anchorMd(4) + ' 交材料');
eq('今晚/后天/大后天',
  REL('今晚必须交，后天体检，大后天放假', '11-05 20:47'),
  anchorMd(0) + ' 晚必须交，' + anchorMd(2) + ' 体检，' + anchorMd(3) + ' 放假');
eq('无前缀周三 → 最近未来周三',
  REL('周三开会', '11-05 20:47'),
  md(new RealDate(2026, 10, 11, 12)) + ' 开会');
eq('明日 + 明早 + 明晚',
  REL('明日集合，明早交表，明晚点名', '11-05 20:47'),
  anchorMd(1) + ' 集合，' + anchorMd(1) + ' 早交表，' + anchorMd(1) + ' 晚点名');
eq('今日校园（专有名词）不替换', REL('课表一律以今日校园为准', '11-05 20:47'), '课表一律以今日校园为准');
eq('每月前三周的周三 不替换', REL('每月前三周的周三 17:30 检查', '11-05 20:47'), '每月前三周的周三 17:30 检查');
eq('无锚点原样返回', REL('明天中午前交', ''), '明天中午前交');
eq('解析失败原样返回', REL('明天中午前交', '不是时间'), '明天中午前交');
eq('已有绝对日期不动', REL('11月6日12:00前提交', '11-05 20:47'), '11月6日12:00前提交');

console.log('---- §0.1 absRelDates 增强：裸日号 / 裸时段 / 括号去重 / 今早 ----');
eq('裸日号 5号 + 比赛语境', REL('5号比赛项目及名单', '11-05 09:00'), '11-05 比赛项目及名单');
eq('裸日号 4号 + 上午语境', REL('4号上午集合', '11-05 09:00'), '11-04 上午集合');
eq('序号 42号同学 不替换', REL('更正42号同学姓名后发布新版花名册', '10-29 15:27'), '更正42号同学姓名后发布新版花名册');
eq('完整日期 11月5日 不重复替换', REL('11月5日14:00 招聘会', '11-05 09:00'), '11月5日14:00 招聘会');
eq('裸时段 下午 → 前缀锚点日期', REL('下午招聘会请各班同学准时到场', '11-05 13:00'), '11-05 下午招聘会请各班同学准时到场');
eq('裸时段 上午+钟点', REL('上午9:10 比赛', '11-05 08:00'), '11-05 上午9:10 比赛');
eq('每天下午 不替换', REL('每天下午 5:30 检查', '11-05 09:00'), '每天下午 5:30 检查');
eq('今早 → MM-DD 早', REL('今早交材料', '11-05 09:00'), anchorMd(0) + ' 早交材料');
eq('绝对日期+相对星期去重', REL('11月14日（下周六）献血活动', '11-05 20:47'), '11月14日献血活动');
eq('绝对日期+同日 MM-DD 去重', REL('11月14日（11-14）献血活动', '11-05 20:47'), '11月14日献血活动');
eq('相对星期替换后再去重', REL('本周六（明天）报名截止', '11-05 20:47'),
  md(new RealDate(2026, 10, 7, 12)) + ' 报名截止');
eq('今日校园仍保留', REL('课表一律以今日校园为准', '11-05 20:47'), '课表一律以今日校园为准');
eq('上游误替换「10-29校园」→ 还原今日校园', REL('课表以10-29校园为准', '11-05 20:47'), '课表以今日校园为准');
eq('裸周 本周起 → 本周一（R7）', REL('自本周起，每月前三周 周三 17:30 例行检查', '11-03 09:13'),
  '自' + md(new RealDate(2026, 10, 2, 12)) + ' 起，每月前三周 周三 17:30 例行检查');
eq('裸周 本周（11.4）→ 11-04（对齐 notice_time）', REL('自本周（11.4）起检查', '11-03 09:13'),
  '自11-04 起检查');
eq('裸周 下周 → 下周一', REL('下周末前交材料', '11-05 20:47'), '下周末前交材料');
eq('裸周 下周开始', REL('下周开始报名', '11-05 20:47'),
  md(new RealDate(2026, 10, 9, 12)) + ' 开始报名');
eq('42号 在摘要里不替换', REL('更正42号同学姓名后发布新版花名册，今后以此为准', '10-29 15:27'),
  '更正42号同学姓名后发布新版花名册，今后以此为准');

console.log('---- 渲染层：卡片/简报统一口径 ----');
const listHtml = elFor('q:#list').innerHTML || '';
const expiredHtml = elFor('q:#expiredList').innerHTML || '';
const briefHtml = elFor('q:#briefNext').innerHTML || '';
contains('卡片 chip = 13 小时后 报送截止', listHtml, '13 小时后 报送截止');
contains('卡片正文 = 11-06 中午前', listHtml, anchorMd(1) + ' 中午前');
contains('卡片正文 = 11-08 晚点名', listHtml, anchorMd(3) + ' 晚点名');
notContains('卡片正文无裸「明天」', listHtml, '明天中午前');
notContains('无「今天 12:00」旧 bug', listHtml, '今天 12:00');
notContains('无「已截止 · 自动完成」旧样式', listHtml + expiredHtml, '已截止 · 自动完成');
notContains('无「已延长 ·」旧样式', listHtml + expiredHtml, '已延长 ·');
notContains('无「报名已截止」（§0.2）', listHtml + expiredHtml, '报名已截止');
contains('briefNext meta 同口径（短动作）', briefHtml, '13 小时后 报送截止');
contains('报名卡 chip 报名开始', listHtml, daysFromNow(Date.parse('2026-11-07T12:00:00+08:00')) + ' 天后 报名开始');
contains('手抄报 chip 报名截止（已过期区）', expiredHtml, '11-03 20:30 报名截止');
contains('长期安排 chip', listHtml, '长期安排 · 每月前三周');
contains('相对文本卡：11-08 晚点名', listHtml, anchorMd(3) + ' 晚点名');
contains('相对文本卡：11-09 交材料', listHtml, anchorMd(4) + ' 交材料');
contains('标题日期化：下午招聘会 → 11-05 下午', listHtml + expiredHtml, '11-05 下午招聘会请准时到场');
contains('标题日期化：5号 → 11-05', listHtml + expiredHtml, '运动会11-05');
contains('标题括号去重：11月14日（下周六）→ 11月14日', listHtml + expiredHtml, '11月14日献血活动');
notContains('标题无裸括号相对词', listHtml + expiredHtml, '（下周六）');
contains('链接名日期化+括号去重', ctx.groupHTML(groupById('g_link_rel')), '11月14日献血活动');
notContains('链接名无括号相对词', ctx.groupHTML(groupById('g_link_rel')), '（下周六）');
const groupNameHtml = ctx.groupHTML(groupById('g_groupname'));
contains('群名「26级周一89节太极拳」不被误替换', groupNameHtml, '26级周一89节太极拳');
notContains('群名不被替换成日期', groupNameHtml, '11-02 89节');
eq('周X+数字节 不替换', REL('26级周一89节太极拳', '10-31 10:12'), '26级周一89节太极拳');

console.log('---- §0.3：有 AI 摘要的卡正文不内联原始消息，全部进「原始消息」按钮 ----');
const mergedHtml = ctx.groupHTML(groupById('g_ai_merged'));
eq('合并卡正文不渲染 text item', (mergedHtml.match(/class="gitem"/g) || []).length, 0);
notContains('合并卡正文无「电子版」原文', mergedHtml, '电子版材料需要在');
notContains('合并卡正文无「纸质版」原文', mergedHtml, '纸质版晚点名交');
notContains('合并卡正文无内联补充通知 label', mergedHtml, 'gi-type supp');
contains('合并卡「原始消息」按钮存在', mergedHtml, 'class="origbtn"');
contains('合并卡「已更新」徽标', mergedHtml, '已更新');
ctx.openOriginal('g_ai_merged');
const mcardHtml = elFor('q:#mcard').innerHTML || '';
eq('原始消息弹层含 3 条（按时间顺序）', (mcardHtml.match(/class="orig-item"/g) || []).length, 3);
contains('弹层含电子版原文（按消息自身时间日期化）', mcardHtml,
  ctx.absRelDates('电子版材料需要在周日下午十四点发给我', '11-05 21:07'));
contains('弹层含纸质版原文', mcardHtml, '纸质版晚点名交');
contains('弹层含报送姓名原文（日期化）', mcardHtml, anchorMd(1) + ' 中午前报送姓名');
contains('弹层含时间', mcardHtml, '11-05 20:47');
const singleHtml = ctx.groupHTML(groupById('g_single_summary'));
contains('单条卡显示 AI 摘要', singleHtml, '摘要：请' + anchorMd(1) + ' 中午前报送姓名');
notContains('单条卡有摘要时不显示原文', singleHtml, '原始正文');
eq('单条卡不渲染 text item', (singleHtml.match(/class="gitem"/g) || []).length, 0);

console.log('\n================ 结果 ================');
console.log('PASS ' + pass + ' / FAIL ' + fail);
if (fail) {
  console.log('失败用例：');
  failures.forEach(f => console.log(' - ' + f));
  process.exit(1);
}
console.log('全部通过 ✅');
