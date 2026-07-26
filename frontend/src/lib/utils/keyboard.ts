/**
 * Keyboard-shortcut helpers.
 *
 * The rule is: never trigger a shortcut while the user is editing text or a
 * Radix modal owns focus. This module owns that predicate so shortcuts on
 * TakeTest, Review, and (future) command palette all agree.
 */

/** True when a text-input, textarea, contenteditable, or select is focused. */
export function isEditingText(): boolean {
  if (typeof document === 'undefined') return false;
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (el.isContentEditable) return true;
  return false;
}

/** True when any Radix modal is open (looks for `[data-state="open"][role="dialog"]`). */
export function isModalOpen(): boolean {
  if (typeof document === 'undefined') return false;
  return Boolean(
    document.querySelector(
      '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]',
    ),
  );
}

/** True when neither text-editing nor modal is holding keyboard input. */
export function shortcutsEnabled(): boolean {
  return !isEditingText() && !isModalOpen();
}
