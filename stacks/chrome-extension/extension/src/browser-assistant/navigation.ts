import { normalizeUserLabel } from './intent';

const MAX_ACCESSIBLE_LABEL_LENGTH = 200;
const MAX_RAW_ACCESSIBLE_LABEL_LENGTH = 1_024;
const MAX_LABELLED_BY_IDS = 8;
const MAX_NAVIGATION_LINKS_SCANNED = 2_000;
const MAX_NAVIGATION_CANDIDATES = 500;
export const NAVIGATION_RESOLVE_MESSAGE =
  'firestarter:navigation:resolve' as const;

export interface AccessibleLabelParts {
  labelledByText?: readonly (string | null | undefined)[];
  ariaLabel?: string | null;
  visibleText?: string | null;
  title?: string | null;
}

export interface SafeNavigationCandidate {
  id: string;
  href: string;
  accessibleLabel: string;
}

export type ExactNavigationResolution =
  | { status: 'matched'; candidate: SafeNavigationCandidate }
  | { status: 'already-current'; candidate: SafeNavigationCandidate }
  | { status: 'ambiguous'; count: number }
  | { status: 'not-found' };

export interface NavigationResolveMessage {
  type: typeof NAVIGATION_RESOLVE_MESSAGE;
  target: string;
}

export type NavigationResolutionResponse =
  | { status: 'matched' | 'already-current' | 'not-found' }
  | { status: 'ambiguous'; count: number };

function boundedLabel(value: string | null | undefined): string {
  return (value ?? '')
    .slice(0, MAX_RAW_ACCESSIBLE_LABEL_LENGTH)
    .normalize('NFKC')
    .replace(
      /[\u0000-\u001f\u007f-\u009f\u200e\u200f\u202a-\u202e\u2066-\u2069]/g,
      ' ',
    )
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, MAX_ACCESSIBLE_LABEL_LENGTH);
}

/**
 * Deterministic accessible-name approximation for anchors. The browser
 * accessibility tree remains authoritative.
 */
export function accessibleLabelFromParts(
  parts: AccessibleLabelParts,
): string {
  const labelledBy = boundedLabel(
    parts.labelledByText
      ?.map((part) => boundedLabel(part))
      .filter(Boolean)
      .join(' '),
  );
  if (labelledBy) return labelledBy;

  for (const value of [parts.ariaLabel, parts.visibleText, parts.title]) {
    const label = boundedLabel(value);
    if (label) return label;
  }
  return '';
}

export function safeHttpHref(
  rawHref: string,
  baseHref: string,
): string | null {
  try {
    const url = new URL(rawHref, baseHref);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    if (url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function resolveExactNavigationCandidate(
  requestedLabel: string,
  candidates: readonly SafeNavigationCandidate[],
  currentHref?: string,
): ExactNavigationResolution {
  const target = normalizeUserLabel(requestedLabel);
  if (!target) return { status: 'not-found' };

  const uniqueByHref = new Map<string, SafeNavigationCandidate>();
  for (const candidate of candidates) {
    if (
      normalizeUserLabel(candidate.accessibleLabel) === target &&
      !uniqueByHref.has(candidate.href)
    ) {
      uniqueByHref.set(candidate.href, candidate);
    }
  }

  const matches = [...uniqueByHref.values()];
  if (matches.length === 0) return { status: 'not-found' };
  if (matches.length > 1) {
    return { status: 'ambiguous', count: matches.length };
  }

  const [candidate] = matches;
  return currentHref && candidate.href === currentHref
    ? { status: 'already-current', candidate }
    : { status: 'matched', candidate };
}

export function parseNavigationResolveMessage(
  value: unknown,
): NavigationResolveMessage | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (
    record.type !== NAVIGATION_RESOLVE_MESSAGE ||
    typeof record.target !== 'string'
  ) {
    return null;
  }

  const target = record.target.trim();
  if (
    !target ||
    target.length > 100 ||
    /[\r\n\u0000-\u001f\u007f-\u009f]/.test(target)
  ) {
    return null;
  }
  return { type: NAVIGATION_RESOLVE_MESSAGE, target };
}

export function parseNavigationResolutionResponse(
  value: unknown,
): NavigationResolutionResponse | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (
    record.status === 'matched' ||
    record.status === 'already-current' ||
    record.status === 'not-found'
  ) {
    return { status: record.status };
  }
  if (
    record.status === 'ambiguous' &&
    typeof record.count === 'number' &&
    Number.isInteger(record.count) &&
    record.count >= 2 &&
    record.count <= MAX_NAVIGATION_CANDIDATES
  ) {
    return { status: 'ambiguous', count: record.count };
  }
  return null;
}

function labelledByText(link: HTMLAnchorElement): string[] {
  return (link.getAttribute('aria-labelledby') ?? '')
    .slice(0, 1024)
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, MAX_LABELLED_BY_IDS)
    .map((id) => link.ownerDocument.getElementById(id)?.textContent ?? '');
}

export function accessibleNavigationLabel(link: HTMLAnchorElement): string {
  return accessibleLabelFromParts({
    labelledByText: labelledByText(link),
    ariaLabel: link.getAttribute('aria-label'),
    visibleText: link.innerText || link.textContent,
    title: link.getAttribute('title'),
  });
}

export function isVisibleNavigationLink(link: HTMLAnchorElement): boolean {
  if (
    link.hidden ||
    link.matches('[aria-hidden="true"], [inert]') ||
    link.closest('[hidden], [aria-hidden="true"], [inert]')
  ) {
    return false;
  }

  const view = link.ownerDocument.defaultView;
  if (!view) return false;
  const style = view.getComputedStyle(link);
  return (
    style.display !== 'none' &&
    style.visibility !== 'hidden' &&
    style.visibility !== 'collapse' &&
    link.getClientRects().length > 0
  );
}

export function visiblePageNavigationCandidates(
  root: ParentNode = document,
  baseHref: string = location.href,
): SafeNavigationCandidate[] {
  const candidates: SafeNavigationCandidate[] = [];
  const links = root.querySelectorAll<HTMLAnchorElement>('a[href]');
  const linksToScan = Math.min(links.length, MAX_NAVIGATION_LINKS_SCANNED);
  for (let index = 0; index < linksToScan; index += 1) {
    if (candidates.length >= MAX_NAVIGATION_CANDIDATES) break;
    const link = links[index];
    if (!isVisibleNavigationLink(link) || link.hasAttribute('download')) continue;
    const accessibleLabel = accessibleNavigationLabel(link);
    const href = safeHttpHref(link.getAttribute('href') ?? '', baseHref);
    if (!accessibleLabel || !href) continue;
    candidates.push({
      id: link.id || `visible-link-${index}`,
      accessibleLabel,
      href,
    });
  }
  return candidates;
}

export function resolveVisiblePageNavigation(
  requestedLabel: string,
): ExactNavigationResolution {
  return resolveExactNavigationCandidate(
    requestedLabel,
    visiblePageNavigationCandidates(),
    location.href,
  );
}
