const DISABLED_KEY = 'one-auto-update-disabled';

export function isAutoUpdateDisabled(): boolean {
  return true;
}

export function setAutoUpdateDisabled(_disabled: boolean): void {
  try {
    localStorage.setItem(DISABLED_KEY, '1');
  } catch {}
}

export function UpdateChecker() {
  return null;
}
