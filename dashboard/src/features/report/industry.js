export function countIndustries(hits) {
  const counts = new Map()

  for (const hit of hits) {
    for (const name of hit.industry ?? []) {
      counts.set(name, (counts.get(name) ?? 0) + 1)
    }
  }

  return [...counts]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
}
