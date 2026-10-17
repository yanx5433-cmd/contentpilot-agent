/* ContentPilot 在线演示引擎 —— Python 版（app/agent + app/tools/domain.py）的忠实 JS 移植。
 * 与仓库版同一套：规划模板 → 拓扑执行 → 五道护栏 → 综合答复 → 输出复检。
 * 演示差异只有两处（页脚有声明）：写操作台账落浏览器 localStorage；不接 LLM。
 */
const CP = (function () {
  'use strict';

  // ---------------- 配置（与 app/config.py 同源） ----------------
  const BLOCKED_WORDS = ["国家级", "最高级", "最佳", "第一品牌", "绝对", "100%", "根治", "全网最低", "史上最低", "祖传", "包治", "立刻见效", "永久"];
  const REVIEW_INTENT = ["审查", "体检", "合规", "违禁", "检测", "检查文案", "审一下"];
  const DANGEROUS = ["rm -rf", "drop database", "drop table", "format c:", "删除所有", "删库", "绕过审批", "跳过护栏", "关掉护栏", "把密钥给我", "输出密码"];
  const P1_WORDS = ["秒杀", "限时", "抢购", "仅此一次"];
  const MASK_PATTERNS = [/sk-[A-Za-z0-9]{6}[A-Za-z0-9\-_]+/g, /(password|passwd|pwd)\s*[=:]\s*\S+/gi];

  // ---------------- 演示数据（与 data/demo/*.json 同源） ----------------
  const KB = [
    { source: "kb/hooks.md", title: "前3秒钩子六式", text: "爆款视频前3秒钩子六式：反常识开场、身份点名、利益前置、悬念缺口、冲突场景、结果前置。完播率数据显示结果前置式平均完播高出基线18%。选题时先写钩子再写脚本。" },
    { source: "kb/topics.md", title: "秋冬女装选题四象限", text: "秋冬女装选题四象限：实测对比类（打底裤/开衫多件横评）完播最稳；场景穿搭类（通勤/约会/通勤变身）涨粉最快；价格攻略类（百元搞定全身）转化最高；避坑科普类（起球/掉色）互动率最高。选题先选象限再定钩子。" },
    { source: "kb/compliance.md", title: "电商文案合规红线", text: "电商文案合规红线：禁用绝对化用语（最佳、第一品牌、国家级）；禁用虚假承诺（根治、立刻见效、100%）；促销表述需真实时限。最佳写法是用可验证数据替代形容词，例如本月退货率最低的3款之一。" },
    { source: "kb/comments.md", title: "评论运营三步法", text: "评论运营三步法：先分类（购买咨询/质量询问/售后/内容反馈），再定优先级（售后2小时内、购买咨询当天），最后模板化草稿人工定稿。高频购买咨询应反哺选题做集中答疑视频。" },
    { source: "kb/publish.md", title: "发布时段与频次", text: "发布时段历史数据：19点档平均完播最高（0.42），12点档次之（0.36），凌晨档慎用。每周4-5更保持权重，连续断更超过3天流量衰减明显。发布后1小时是互动黄金窗，评论区先自评一条引导。" },
  ];
  const VIDEOS = [
    { id: "V001", title: "秋冬打底裤实测：3款横评", category: "女装", views: 52000, finish_rate: 0.46 },
    { id: "V002", title: "针织开衫穿搭：通勤变身", category: "女装", views: 41000, finish_rate: 0.39 },
    { id: "V003", title: "百元搞定秋冬全身穿搭", category: "女装", views: 68000, finish_rate: 0.41 },
    { id: "V004", title: "打底裤起球怎么办？避坑科普", category: "女装", views: 33000, finish_rate: 0.44 },
    { id: "V005", title: "开衫的5种穿法", category: "女装", views: 29000, finish_rate: 0.35 },
    { id: "V006", title: "秋冬面料科普：不起球的3种材质", category: "女装", views: 47000, finish_rate: 0.43 },
    { id: "V007", title: "厨房收纳好物分享", category: "家居", views: 21000, finish_rate: 0.30 },
    { id: "V008", title: "双十一清单攻略", category: "攻略", views: 39000, finish_rate: 0.37 },
  ];
  const ACCOUNT = { followers: 35200, views_7d: 158000, avg_finish: 0.41, gmv_30d: 12600, orders_30d: 214 };
  const COMMENTS = [
    "打底裤链接多少钱？怎么买", "亲测会起球吗，面料怎么样", "尺码偏大吗，160能穿吗",
    "上次买的掉色了想退货退款", "链接打不开，怎么下单", "好看！支持主播",
    "多少钱一条，有货吗", "穿了一次就起球了，质量不行想退款", "加油，内容很喜欢",
    "开衫会缩水吗", "售后电话多少，要投诉", "求双十一攻略选题",
    "这个价格太划算，已下单", "发货慢，一周了还没到，退货", "爱了爱了，天天蹲更新",
  ];
  const PRODUCTS = [
    { external_id: "P101", title: "加绒打底裤", category: "女装", price: 39.9, commission_rate: 0.20, return_rate: 0.06 },
    { external_id: "P102", title: "针织开衫", category: "女装", price: 79.0, commission_rate: 0.15, return_rate: 0.09 },
    { external_id: "P103", title: "秋冬打底衫", category: "女装", price: 29.9, commission_rate: 0.25, return_rate: 0.05 },
    { external_id: "P104", title: "毛呢外套", category: "女装", price: 199.0, commission_rate: 0.10, return_rate: 0.18 },
    { external_id: "P105", title: "雪地靴", category: "鞋靴", price: 89.0, commission_rate: 0.18, return_rate: 0.12 },
  ];
  const CALENDAR = [
    { hour: 7, score: 0.22, note: "早通勤，泛流量" }, { hour: 12, score: 0.36, note: "午休档，次优" },
    { hour: 18, score: 0.33, note: "晚饭档" }, { hour: 19, score: 0.42, note: "黄金档，女装完播最高" },
    { hour: 21, score: 0.38, note: "睡前档" }, { hour: 23, score: 0.18, note: "凌晨慎用" },
  ];
  const COMMENT_RULES = [
    ["售后诉求", ["退货", "退款", "换货", "坏了", "投诉"]],
    ["购买咨询", ["怎么买", "链接", "多少钱", "价格", "下单", "尺码", "有货"]],
    ["质量询问", ["质量", "起球", "掉色", "面料", "会不会", "耐用"]],
    ["内容反馈", ["喜欢", "好看", "支持", "加油", "爱了"]],
  ];

  // ---------------- 工具（与 app/tools/domain.py 一致） ----------------
  const pct = (x, d = 0) => (x * 100).toFixed(d) + "%";
  const num = (x) => Math.round(x).toLocaleString("en-US");

  function kbSearch(query) {
    const terms = query.replace(/，/g, " ").replace(/？/g, " ").split(/\s+/).filter(Boolean);
    const use = terms.length ? terms : [query];
    const scored = [];
    for (const doc of KB) {
      const text = doc.title + " " + doc.text;
      let score = 0;
      for (const t of use) score += text.split(t).length - 1;
      if (score > 0) {
        let snippet = doc.text.slice(0, 120);
        for (const t of use) {
          const i = doc.text.indexOf(t);
          if (i >= 0) { snippet = doc.text.slice(Math.max(0, i - 20), i + 100); break; }
        }
        scored.push({ source: doc.source, title: doc.title, score, snippet });
      }
    }
    scored.sort((a, b) => b.score - a.score);
    return { refs: scored.slice(0, 3), query };
  }

  function videoStats(keyword) {
    const kw = keyword.slice(0, 4);
    let hits = VIDEOS.filter((v) => kw && (v.title.includes(kw) || v.category.includes(kw)));
    if (!hits.length) hits = VIDEOS;
    const n = hits.length;
    const avg = (f) => hits.reduce((s, v) => s + f(v), 0) / n;
    return {
      count: n,
      avg_views: Math.round(avg((v) => v.views)),
      avg_finish: Math.round(avg((v) => v.finish_rate) * 1000) / 1000,
      top_title: hits.reduce((m, v) => (v.views > m.views ? v : m)).title,
    };
  }

  function accountMetrics() { return { ...ACCOUNT }; }

  function commentSummary() {
    const dist = {};
    for (const text of COMMENTS) {
      let label = "其他";
      for (const [name, kws] of COMMENT_RULES) {
        if (kws.some((k) => text.includes(k))) { label = name; break; }
      }
      dist[label] = (dist[label] || 0) + 1;
    }
    const total = COMMENTS.length;
    const topName = Object.keys(dist).reduce((a, b) => (dist[b] > dist[a] ? b : a));
    const risk = (dist["售后诉求"] || 0) >= 3 ? "发现售后诉求，建议优先处理" : "无显著风险";
    return { total, dist, top_intent: { name: topName, ratio: Math.round((dist[topName] / total) * 100) / 100 }, risk_note: risk };
  }

  function productPool(category) {
    let list = PRODUCTS.slice();
    if (category) list = list.filter((p) => p.category.includes(category));
    const ranked = list.slice().sort((a, b) => a.return_rate - b.return_rate || b.commission_rate - a.commission_rate);
    const picks = ranked.slice(0, 3).map((p) => ({ title: p.title, price: p.price, return_rate: p.return_rate, commission_rate: p.commission_rate }));
    const risky = list.filter((p) => p.return_rate > 0.15).map((p) => p.title);
    return { picks, risky, total: list.length };
  }

  function complianceCheck(text) {
    const p0 = BLOCKED_WORDS.filter((w) => text.includes(w));
    if (p0.length) return {
      level: "P0", hits: p0, verdict: "拦截",
      rewrite_hint: "把绝对化表述改成可验证的具体描述：用真实数据替代形容词（如「本月退货率最低的 3 款之一」，需有数据支撑）",
    };
    const p1 = P1_WORDS.filter((w) => text.includes(w));
    if (p1.length) return { level: "P1", hits: p1, verdict: "人工复核", rewrite_hint: "促销紧迫感表述需真实时限，写明具体截止时间" };
    return { level: "PASS", hits: [], verdict: "通过", rewrite_hint: "" };
  }

  function calendarSlot(hour) {
    if (hour === null || hour === undefined) {
      const best = CALENDAR.reduce((a, b) => (b.score > a.score ? b : a));
      return { best_hour: best.hour, score: best.score, note: best.note, all: CALENDAR };
    }
    const hit = CALENDAR.find((x) => x.hour === hour);
    if (!hit) return { best_hour: null, note: `${hour} 点无历史数据，建议避开`, all: CALENDAR };
    return { best_hour: hit.hour, score: hit.score, note: hit.note, all: CALENDAR };
  }

  function registerPublish(title) {
    const id = "pub_" + Math.random().toString(16).slice(2, 12);
    const rec = { publish_id: id, ts: new Date().toISOString(), title, operator: "contentpilot-demo" };
    try {
      const log = JSON.parse(localStorage.getItem("cp_publish_log") || "[]");
      log.push(rec);
      localStorage.setItem("cp_publish_log", JSON.stringify(log));
    } catch (e) { /* 无痕模式忽略 */ }
    return { registered: true, publish_id: id, title };
  }

  // ---------------- 护栏（与 app/agent/guardrails.py 一致） ----------------
  function filterOutput(text) {
    let out = text;
    for (const re of MASK_PATTERNS) out = out.replace(re, (m) => m.slice(0, 6) + "****");
    for (const w of BLOCKED_WORDS) out = out.split(w).join("□".repeat(w.length));
    return out;
  }

  function checkInput(goal) {
    const low = goal.toLowerCase();
    for (const p of DANGEROUS) if (low.includes(p)) return { ok: false, reason: `目标含危险操作「${p}」，已拦截（P0）` };
    const isReview = REVIEW_INTENT.some((k) => goal.includes(k));
    if (!isReview) for (const w of BLOCKED_WORDS) if (low.includes(w)) return { ok: false, reason: `目标含违禁词「${w}」，已拦截（P0 合规）` };
    if (goal.trim().length < 2) return { ok: false, reason: "目标过短，无法规划" };
    if (goal.length > 500) return { ok: false, reason: "目标过长（>500 字），请拆分任务" };
    return { ok: true, reason: "" };
  }

  // ---------------- 规划器（与 app/agent/planner.py 一致） ----------------
  function extractQuoted(goal) {
    const m = goal.match(/[「『"“'](.+?)[」』"”']/);
    return m ? m[1].trim() : null;
  }

  function planReview(goal) {
    const text = extractQuoted(goal) || goal;
    return [{ tool: "compliance_check", args: { text }, reason: "对文案做 P0/P1/P2 三级合规审查" }];
  }
  function planTopic(goal) {
    const topic = extractQuoted(goal) || goal;
    return [
      { tool: "kb_search", args: { query: `${topic} 爆款结构 选题` }, reason: "检索知识库里的同类爆款结构与方法论" },
      { tool: "video_stats", args: { keyword: topic }, reason: "拉同类目视频指标，看垂类热度与完播基线" },
      { tool: "synthesize", args: {}, reason: "综合知识库与数据，给出可执行的选题建议" },
    ];
  }
  function planWeekly() {
    return [
      { tool: "account_metrics", args: {}, reason: "拉账号核心指标（播放/粉丝/完播/转化）" },
      { tool: "comment_summary", args: {}, reason: "分析评论意图分布，找高频诉求与风险" },
      { tool: "synthesize", args: { format: "weekly_report" }, reason: "综合数据与评论，输出周报（结论→数据→行动项）" },
    ];
  }
  function planProduct() {
    return [
      { tool: "product_pool", args: {}, reason: "拉商品池（价格带/佣金/退货率）" },
      { tool: "synthesize", args: { format: "product_recommend" }, reason: "按退货风险与佣金给挂车推荐" },
    ];
  }
  function planPublish(goal) {
    const text = extractQuoted(goal) || goal;
    return [
      { tool: "compliance_check", args: { text }, reason: "发布前合规门禁：先审查文案" },
      { tool: "register_publish", args: { title: text }, reason: "合规通过后登记发布记录（写操作，需授权）" },
    ];
  }
  function planExplore(goal) {
    return [
      { tool: "kb_search", args: { query: goal.slice(0, 60) }, reason: "检索知识库寻找相关方法与素材" },
      { tool: "synthesize", args: {}, reason: "基于检索结果综合回答" },
    ];
  }

  function makePlan(goal) {
    const templates = [
      [["违禁", "合规", "体检", "审查文案", "审查", "文案", "check"], planReview],
      [["选题", "爆款", "拍什么", "topic", "研究"], planTopic],
      [["周报", "复盘", "总结", "上周", "report"], planWeekly],
      [["挂车", "选品", "卖什么", "商品", "product"], planProduct],
      [["发布", "登记", "上线", "publish"], planPublish],
    ];
    for (const [keywords, builder] of templates) {
      if (keywords.some((k) => goal.includes(k))) return builder(goal);
    }
    return planExplore(goal);
  }

  // ---------------- 综合器（与 app/agent/executor.py 文案一致） ----------------
  function synthesize(steps, goal) {
    let fmt = "";
    for (const s of steps) if (s.tool === "synthesize" && s.args && s.args.format) fmt = s.args.format;
    const lines = [`结论（目标：${goal}）`];

    for (const s of steps) {
      const r = s.result;
      if (s.tool === "compliance_check" && r) {
        if (r.level === "P0") {
          lines.push(`- 文案合规：P0 拦截（命中 ${r.hits.length} 处违禁词），不能发布`);
          if (r.rewrite_hint) lines.push(`- 改写建议：${r.rewrite_hint}`);
        } else if (r.level === "P1") {
          lines.push(`- 文案合规：P1 人工复核（${r.hits.slice(0, 5).join("、")}），可改写后发`);
        } else {
          lines.push("- 文案合规：通过，无 P0/P1 风险");
        }
      }
      if (s.tool === "kb_search" && r && r.refs.length) {
        lines.push(`- 方法论：命中 ${r.refs.length} 条素材，重点参考「${r.refs[0].title}」（${r.refs[0].source}）`);
        if (r.refs[0].snippet && r.refs[0].snippet.trim()) lines.push(`  · 要点：${r.refs[0].snippet.trim().slice(0, 80)}`);
      }
      if (s.tool === "video_stats" && r) {
        lines.push(`- 数据侧：同类视频 ${r.count} 条，平均完播 ${pct(r.avg_finish)}，平均播放 ${num(r.avg_views)}；历史最高播放：「${r.top_title}」`);
      }
      if (s.tool === "account_metrics" && r) {
        lines.push(`- 账号：粉丝 ${num(r.followers)}，近 7 日播放 ${num(r.views_7d)}，平均完播 ${pct(r.avg_finish)}，30 天 GMV ${num(r.gmv_30d)}`);
      }
      if (s.tool === "comment_summary" && r) {
        lines.push(`- 评论：共 ${r.total} 条，最高频意图「${r.top_intent.name}」占 ${pct(r.top_intent.ratio)}；${r.risk_note}`);
      }
      if (s.tool === "product_pool" && r) {
        if (r.picks.length) {
          const names = r.picks.slice(0, 2).map((p) => `${p.title}（退货 ${pct(p.return_rate)}/佣金 ${pct(p.commission_rate)}）`).join("、");
          lines.push(`- 选品：推荐优先挂车 ${names}`);
        }
        if (r.risky.length) lines.push(`- 风险品：${r.risky.join("、")} 退货率超 15%，暂不挂车`);
      }
      if (s.tool === "calendar_slot" && r) {
        lines.push(`- 时段：建议 ${r.best_hour !== null && r.best_hour !== undefined ? r.best_hour : "?"} 点档发布（${r.note}）`);
      }
      if (s.status === "blocked") lines.push(`- ⚠ 步骤「${s.tool}」被护栏拦截：${s.error}`);
    }

    if (fmt === "weekly_report") lines.push("行动项：① 处理评论高风险项 ② 按 19 点档排期 ③ 沿用命中象限的选题结构。");
    else if (fmt === "product_recommend") lines.push("行动项：把推荐商品挂到下一个选题的带货位，上架后回流销售数据做复盘。");
    else lines.push("下一步建议：把本结论带回工作台执行；写操作已按最小权限处理。");
    return lines.join("\n");
  }

  // ---------------- 执行器（与 app/agent/executor.py 流程一致） ----------------
  const TOOL_READ = new Set(["kb_search", "video_stats", "account_metrics", "comment_summary", "product_pool", "compliance_check", "calendar_slot"]);
  const TOOL_WRITE = new Set(["register_publish"]);

  function run(goal, opts) {
    const approvedWrite = !!(opts && opts.approveWrite);
    const events = [];
    const emit = (type, payload) => events.push({ seq: events.length + 1, ts: Date.now(), type, payload });

    const gate = checkInput(goal);
    if (!gate.ok) {
      emit("guard", { gate: "input", allowed: false, reason: gate.reason });
      const answer = filterOutput(`任务被输入护栏拦截：${gate.reason}`);
      emit("answer", { text: answer });
      return { status: "blocked", answer, steps: [], events, blockers: [gate.reason] };
    }
    emit("guard", { gate: "input", allowed: true });

    const steps = makePlan(goal).map((s) => ({ ...s, status: "pending", result: null, error: null }));
    emit("plan", { steps: steps.map((s) => ({ tool: s.tool, reason: s.reason })) });

    for (const step of steps) {
      if (step.tool === "synthesize") { step.status = "done"; continue; }

      if (TOOL_WRITE.has(step.tool) && !approvedWrite) {
        step.status = "blocked";
        step.error = `写操作「${step.tool}」未获授权（最小权限护栏），已挂起等待人工确认`;
        emit("guard", { gate: "write_auth", tool: step.tool, allowed: false, reason: step.error });
        continue;
      }

      emit("tool_call", { tool: step.tool, args: step.args });
      try {
        switch (step.tool) {
          case "kb_search": step.result = kbSearch(step.args.query); break;
          case "video_stats": step.result = videoStats(step.args.keyword); break;
          case "account_metrics": step.result = accountMetrics(); break;
          case "comment_summary": step.result = commentSummary(); break;
          case "product_pool": step.result = productPool(step.args.category); break;
          case "compliance_check": step.result = complianceCheck(step.args.text); break;
          case "calendar_slot": step.result = calendarSlot(step.args.hour ?? null); break;
          case "register_publish": step.result = registerPublish(step.args.title); break;
          default: throw new Error("未知工具：" + step.tool);
        }
        step.status = "done";
        emit("observation", { tool: step.tool, result: step.result });
      } catch (e) {
        step.status = "failed";
        step.error = String(e && e.message || e);
        emit("observation", { tool: step.tool, error: step.error });
      }
    }

    let status = "done";
    if (steps.some((s) => s.status === "blocked")) status = "blocked";
    else if (steps.length && steps.every((s) => s.status === "skipped")) status = "failed";

    const answer = filterOutput(synthesize(steps, goal));
    emit("answer", { text: answer });
    return { status, answer, steps, events, blockers: steps.filter((s) => s.status === "blocked").map((s) => s.error) };
  }

  return { run, filterOutput };
})();
if (typeof module !== "undefined" && module.exports) module.exports = CP;
