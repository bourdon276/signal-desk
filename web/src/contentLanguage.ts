// Local script heuristic for title/excerpt UI; no model request or external service.
function isMostlyForeign(text: string): boolean {
  const letters = text.match(/\p{L}/gu) ?? []
  const chinese = letters.filter(letter => /\p{Script=Han}/u.test(letter)).length
  const foreign = letters.length - chinese
  // Names, abbreviations and stock codes inside Chinese prose should not show a button.
  return foreign >= 8 && foreign / Math.max(1, letters.length) >= 0.6
}

export function needsChineseTranslation(title: string, excerpt: string): boolean {
  return isMostlyForeign(title) || isMostlyForeign(excerpt)
}
