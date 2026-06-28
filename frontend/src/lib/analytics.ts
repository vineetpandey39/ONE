export async function initAnalytics(): Promise<void> {
  return;
}

export function track(
  _event: string,
  _properties: Record<string, unknown> = {},
): void {
  return;
}

export function flush(): void {
  return;
}

export function isAnalyticsEnabled(): boolean {
  return false;
}

export function getAnonId(): string {
  return '';
}

export async function hashId(s: string): Promise<string> {
  if (!s) return '';
  try {
    const data = new TextEncoder().encode(s);
    const buf = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(buf))
      .slice(0, 8)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  } catch {
    return '';
  }
}

export function detectPlatform(): string {
  const ua =
    typeof navigator !== 'undefined' ? navigator.userAgent.toLowerCase() : '';
  const isTauri =
    typeof window !== 'undefined' &&
    !!(window as unknown as { __TAURI_INTERNALS__?: unknown })
      .__TAURI_INTERNALS__;
  if (isTauri) {
    if (ua.includes('mac')) return 'tauri-macos';
    if (ua.includes('windows')) return 'tauri-windows';
    return 'tauri-linux';
  }
  return 'web';
}
