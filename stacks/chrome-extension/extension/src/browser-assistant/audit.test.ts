import { describe, expect, it } from 'vitest';

import { appendBoundedAudit, redactAuditEvent } from './audit';

describe('browser-assistant metadata-only audit records', () => {
  it('allowlists fields and strips page content, values, selectors, and URL details', () => {
    expect(
      redactAuditEvent({
        event: 'action.completed',
        timestamp: '2026-07-27T12:00:00-05:00',
        actionId: 'action_123',
        planId: 'plan_456',
        status: 'succeeded',
        risk: 'navigate',
        fieldClass: 'none',
        extensionVersion: '0.1.0',
        origin: 'https://example.test/private/path?token=secret#fragment',
        pageText: 'private page content',
        selector: '#patient-name',
        value: 'secret',
        nested: { prompt: 'ignore previous instructions' },
      }),
    ).toEqual({
      event: 'action.completed',
      timestamp: '2026-07-27T17:00:00.000Z',
      actionId: 'action_123',
      planId: 'plan_456',
      status: 'succeeded',
      risk: 'navigate',
      fieldClass: 'none',
      extensionVersion: '0.1.0',
      origin: 'https://example.test',
    });
  });

  it('rejects unknown events and invalid timestamps', () => {
    expect(
      redactAuditEvent({
        event: 'page.dumped',
        timestamp: '2026-07-27T12:00:00Z',
      }),
    ).toBeNull();
    expect(
      redactAuditEvent({
        event: 'action.failed',
        timestamp: 'not a timestamp',
      }),
    ).toBeNull();
  });

  it('drops unsafe identifiers and non-HTTP origins', () => {
    expect(
      redactAuditEvent({
        event: 'action.denied',
        timestamp: '2026-07-27T12:00:00Z',
        actionId: 'contains private words and spaces',
        origin: 'chrome-extension://private-id/sidebar.html',
      }),
    ).toEqual({
      event: 'action.denied',
      timestamp: '2026-07-27T12:00:00.000Z',
    });
  });

  it('returns a new bounded immutable history', () => {
    const first = redactAuditEvent({
      event: 'plan.created',
      timestamp: '2026-07-27T12:00:00Z',
    });
    const second = redactAuditEvent({
      event: 'action.proposed',
      timestamp: '2026-07-27T12:00:01Z',
    });
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();

    const original = [first!] as const;
    const appended = appendBoundedAudit(original, second!, 1);
    expect(appended).toEqual([second]);
    expect(original).toEqual([first]);
    expect(Object.isFrozen(appended)).toBe(true);
  });

  it('keeps malformed limits and oversized input histories bounded', () => {
    const event = redactAuditEvent({
      event: 'action.completed',
      timestamp: '2026-07-27T12:00:00Z',
    })!;
    const oversized = Array.from({ length: 1_000 }, () => event);

    expect(appendBoundedAudit(oversized, event, Number.NaN)).toHaveLength(100);
    expect(appendBoundedAudit(oversized, event, 10_000)).toHaveLength(500);
    expect(appendBoundedAudit(oversized, event, 0)).toEqual([event]);
  });
});
