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

export function markTerms(text, terms) {
  if (!text) return "";
  if (!terms || terms.length === 0) return text;

  const pattern = terms
    .filter(Boolean)
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join("|");
  if (!pattern) return text;

  return text.replace(new RegExp(pattern, "gi"), (word) => `<em>${word}</em>`);
}

export function matchesTerm(text, terms) {
  if (!text || !terms || terms.length === 0) return false;
  const lower = text.toLowerCase();
  return terms.some((term) => term && lower.includes(term.toLowerCase()));
}
