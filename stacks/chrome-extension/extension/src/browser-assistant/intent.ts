/**
 * Deterministic intent parsing for a deliberately small navigation grammar.
 *
 * This module turns trusted user text into typed candidate intent. It never
 * evaluates page text, selectors, JavaScript, or extension API names. Keep the
 * catalog product-owned and explicit; page content is never allowed to extend
 * it at runtime.
 */

export interface NavigationDestination<Destination extends string = string> {
  id: Destination;
  aliases: readonly string[];
}

export interface NavigationIntentOptions {
  /**
   * Unknown destinations fail closed by default. A product may opt into page
   * resolution, but execution must still require one exact safe page match.
   */
  unknownDestination?: 'reject' | 'page';
}

export type NavigationIntent<Destination extends string = string> =
  | {
      scope: 'extension';
      destination: Destination;
      requestedLabel: string;
    }
  | {
      scope: 'page';
      target: string;
    };

const COMMAND_PREFIX =
  /^(?:please\s+)?(?:go\s+to|goto|navigate\s+to|switch\s+to|take\s+me\s+to)\b/i;

const PAGE_QUALIFIER =
  /\s+(?:on|in|inside)\s+(?:the\s+)?(?:current\s+)?(?:web\s*page|page|website|site)(?:\s+(?:currently\s+)?open)?$/i;

const EXTENSION_QUALIFIER =
  /\s+(?:on|in|inside|within)\s+(?:the\s+)?(?:plugin|extension|side\s*panel|sidebar)$/i;

const CONTROL_OR_DIRECTIONAL_FORMATTING =
  /[\u0000-\u001f\u007f-\u009f\u200e\u200f\u202a-\u202e\u2066-\u2069]/g;

export function normalizeUserLabel(value: string): string {
  return value
    .normalize('NFKC')
    .replace(CONTROL_OR_DIRECTIONAL_FORMATTING, ' ')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/['’]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^the\s+/, '');
}

export function looksLikeNavigationCommand(value: string): boolean {
  const trimmed = value.trim();
  return (
    trimmed.length <= 160 &&
    !/[\r\n]/.test(trimmed) &&
    COMMAND_PREFIX.test(trimmed)
  );
}

function destinationForLabel<Destination extends string>(
  value: string,
  destinations: readonly NavigationDestination<Destination>[],
): Destination | null {
  const normalized = normalizeUserLabel(value);
  for (const destination of destinations) {
    if (
      destination.aliases.some(
        (alias) => normalizeUserLabel(alias) === normalized,
      )
    ) {
      return destination.id;
    }
  }
  return null;
}

export function parseNavigationIntent<Destination extends string>(
  value: string,
  destinations: readonly NavigationDestination<Destination>[],
  options: NavigationIntentOptions = {},
): NavigationIntent<Destination> | null {
  const trimmed = value.trim();
  if (!looksLikeNavigationCommand(trimmed)) return null;

  const prefix = trimmed.match(COMMAND_PREFIX);
  if (!prefix) return null;

  let requested = trimmed
    .slice(prefix[0].length)
    .replace(/^[\s,:-]+/, '')
    .replace(/[.!?]+$/, '')
    .replace(/\s+please$/i, '')
    .trim();
  if (!requested || requested.length > 100) return null;

  const pageQualified = PAGE_QUALIFIER.test(requested);
  if (pageQualified) {
    requested = requested.replace(PAGE_QUALIFIER, '').trim();
  }

  const extensionQualified = EXTENSION_QUALIFIER.test(requested);
  if (extensionQualified) {
    requested = requested.replace(EXTENSION_QUALIFIER, '').trim();
  }

  if (!requested || (pageQualified && extensionQualified)) return null;

  const destination = destinationForLabel(requested, destinations);
  if (pageQualified) return { scope: 'page', target: requested };
  if (destination) {
    return {
      scope: 'extension',
      destination,
      requestedLabel: requested,
    };
  }
  if (extensionQualified) return null;
  return options.unknownDestination === 'page'
    ? { scope: 'page', target: requested }
    : null;
}
