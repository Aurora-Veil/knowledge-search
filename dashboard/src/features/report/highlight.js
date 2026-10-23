export function highlightSegments(html) {
  if (!html) return [];

  const re = /<em>(.*?)<\/em>/g;
  let lastIndex = 0;
  let match;
  const segments = [];

  while ((match = re.exec(html)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: html.substring(lastIndex, match.index), hit: false });
    }
    segments.push({ text: match[1], hit: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < html.length) {
    segments.push({ text: html.substring(lastIndex), hit: false });
  }
  return segments;
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// 前端自己打标：后端只给 title / summary 的 <em>，
// 行业标签（industry.text 是把所有行业拼成一句标的，拆不回单个标签）
// 和详情摘要（详情接口压根不返回 highlight）都没有。
//
// 这里故意也拼成 <em> 串再交给 highlightSegments，
// 这样“解析 - 渲染”仍然只有一条路，不用维护两套。
export function markTerms(text, terms) {
  if (!text) return "";
  if (!terms || terms.length === 0) return text;

  // 长的排前面，并且一次 replace 匹配完：
  // 既让“工业机器人”盖住“机器人”，也不会出现标好的 <em> 被后一个词二次拆开
  const pattern = terms
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  if (!pattern) return text;

  return text.replace(new RegExp(pattern, "gi"), (word) => `<em>${word}</em>`);
}

// 标签（chip）用这一个：只判断“这个标签里有没有检索词”，不返回标记。
// 标签只有 11px 高，行内底色会比标签本身高 2px，从圆角上方顶出去，
// 所以标签干脆整块点亮，不在里面画小块。
export function matchesTerm(text, terms) {
  if (!text || !terms || terms.length === 0) return false;
  const lower = text.toLowerCase();
  return terms.some((term) => term && lower.includes(term.toLowerCase()));
}
