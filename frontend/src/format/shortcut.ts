// Ported from app/static/option-key.js — shows the real Mac/iPad/iPhone
// modifier key symbol (⌥) in place of the literal "Alt+" text every
// keyboard-shortcut hint in the app is written with (button labels like
// "Reverse (Alt+R)"). BACKLOG.md's own ask: "When device is iPad or Mac
// show option key instead of ALT."
//
// The underlying shortcuts themselves never change — every keydown
// listener in this app checks e.code (KeyR, KeyE, ...), which is what the
// real Option key on a Mac keyboard (and the on-screen/hardware-keyboard
// equivalent on iPad) actually sets; nothing here touches that wiring.
// legacy swept rendered text nodes client-side once on load, since its
// ~15 hint spots were server-rendered strings baked into static HTML; a
// React component just calls this at render time instead — same
// detection, same output, no DOM text-walking needed since JSX already
// re-renders from source data.
//
// Detection: navigator.userAgentData (the modern replacement for
// navigator.platform, Chromium-only for now) when available, falling back
// to the classic UA-string sniff otherwise — both are fine here since the
// cost of guessing wrong is a label reading "Alt+" on an Apple device or
// "⌥" on a non-Apple one, not a broken shortcut. iPadOS Safari's own UA
// string says "Macintosh" (has done since iPadOS 13's default
// desktop-class UA), indistinguishable here from a real Mac —
// deliberately not disambiguated further, since both should show the
// same ⌥ symbol regardless of which of the two it actually is.
function isApplePlatform(): boolean {
  const uaData = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData
  if (uaData?.platform) return uaData.platform === 'macOS'
  return /Mac|iPhone|iPad|iPod/.test(navigator.userAgent || navigator.platform || '')
}

// altLabel('R') -> "⌥R" on an Apple platform, "Alt+R" everywhere else —
// matching macOS's own menus, which show a modifier symbol directly
// against the key rather than spelling out the join.
export function altLabel(letter: string): string {
  return isApplePlatform() ? `⌥${letter}` : `Alt+${letter}`
}
