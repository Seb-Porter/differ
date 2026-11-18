// The modifier a shortcut holds down: Cmd on a Mac, Ctrl elsewhere, as each system's own apps have it. `primary` says
// whether a key event holds that modifier and not the other one, `label` names a chord as the system writes it, and
// `relabel` turns the Mac's key names in the <kbd>s under an element into this system's.
const Keys = (() => {
  const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
  const primary = (e) => MAC ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  const label = (key, shift = false) => MAC ? `${shift ? '⇧' : ''}⌘${key}` : `Ctrl+${shift ? 'Shift+' : ''}${key}`;
  const NAMES = { Cmd: 'Ctrl', Option: 'Alt' };
  function relabel(root) {
    if (MAC) return;
    for (const kbd of root.querySelectorAll('kbd')) if (NAMES[kbd.textContent]) kbd.textContent = NAMES[kbd.textContent];
    for (const el of root.querySelectorAll('[title*="⌘"]')) el.title = el.title.replace(/⇧?⌘(\S)/g, (m, key) => label(key, m.startsWith('⇧')));
  }
  document.addEventListener('DOMContentLoaded', () => relabel(document));
  return { MAC, primary, label, relabel };
})();
