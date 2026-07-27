/** Metadata-only audit contract for browser-assistant actions. */
export const AUDIT_EVENTS = [
  'plan.created',
  'action.proposed',
  'action.confirmed',
  'action.denied',
  'action.completed',
  'action.failed',
] as const;

export const AUDIT_STATUSES = [
  'pending',
  'confirmed',
  'denied',
  'succeeded',
  'failed',
] as const;

export const AUDIT_RISKS = ['read', 'navigate', 'write', 'external'] as const;

export const AUDIT_FIELD_CLASSES = [
  'none',
  'ordinary',
  'sensitive',
  'secret',
] as const;

export interface AuditEvent {
  event: (typeof AUDIT_EVENTS)[number];
  timestamp: string;
  actionId?: string;
  planId?: string;
  status?: (typeof AUDIT_STATUSES)[number];
  risk?: (typeof AUDIT_RISKS)[number];
  fieldClass?: (typeof AUDIT_FIELD_CLASSES)[number];
  extensionVersion?: string;
  origin?: string;
}

const SAFE_IDENTIFIER = /^[A-Za-z0-9_-]{1,64}$/;
const SAFE_VERSION = /^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$/;

function memberOf<Value extends string>(
  values: readonly Value[],
  value: unknown,
): value is Value {
  return typeof value === 'string' && values.includes(value as Value);
}

function safeOrigin(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.origin : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Converts arbitrary input into a strict metadata-only event.
 *
 * Page text, prompts, selectors, field values, paths, query strings, fragments,
 * tokens, and unknown keys cannot cross this boundary.
 */
export function redactAuditEvent(input: unknown): Readonly<AuditEvent> | null {
  if (!input || typeof input !== 'object') return null;
  const record = input as Record<string, unknown>;
  if (!memberOf(AUDIT_EVENTS, record.event)) return null;

  const parsedTimestamp = new Date(
    typeof record.timestamp === 'string' ? record.timestamp : Number.NaN,
  );
  if (Number.isNaN(parsedTimestamp.valueOf())) return null;

  const event: AuditEvent = {
    event: record.event,
    timestamp: parsedTimestamp.toISOString(),
  };

  if (typeof record.actionId === 'string' && SAFE_IDENTIFIER.test(record.actionId)) {
    event.actionId = record.actionId;
  }
  if (typeof record.planId === 'string' && SAFE_IDENTIFIER.test(record.planId)) {
    event.planId = record.planId;
  }
  if (memberOf(AUDIT_STATUSES, record.status)) event.status = record.status;
  if (memberOf(AUDIT_RISKS, record.risk)) event.risk = record.risk;
  if (memberOf(AUDIT_FIELD_CLASSES, record.fieldClass)) {
    event.fieldClass = record.fieldClass;
  }
  if (
    typeof record.extensionVersion === 'string' &&
    SAFE_VERSION.test(record.extensionVersion)
  ) {
    event.extensionVersion = record.extensionVersion;
  }

  const origin = safeOrigin(record.origin);
  if (origin) event.origin = origin;

  return Object.freeze(event);
}

export function appendBoundedAudit(
  events: readonly Readonly<AuditEvent>[],
  event: Readonly<AuditEvent>,
  maximum = 100,
): readonly Readonly<AuditEvent>[] {
  const requestedLimit = Number.isFinite(maximum) ? Math.floor(maximum) : 100;
  const limit = Math.max(1, Math.min(500, requestedLimit));
  const retained = events.slice(
    Math.max(0, events.length - Math.max(0, limit - 1)),
  );
  return Object.freeze([...retained, event]);
}
