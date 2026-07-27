import { describe, expect, it } from 'vitest';

import {
  NAVIGATION_RESOLVE_MESSAGE,
  accessibleLabelFromParts,
  parseNavigationResolveMessage,
  parseNavigationResolutionResponse,
  resolveExactNavigationCandidate,
  safeHttpHref,
  type SafeNavigationCandidate,
} from './navigation';

const candidates: SafeNavigationCandidate[] = [
  {
    id: 'cardiology-desktop',
    accessibleLabel: 'Cardiology',
    href: 'https://example.test/specialties/cardiology',
  },
  {
    id: 'cardiology-mobile',
    accessibleLabel: 'Cardiology',
    href: 'https://example.test/specialties/cardiology',
  },
  {
    id: 'clinic-a',
    accessibleLabel: 'Clinic',
    href: 'https://example.test/clinics/a',
  },
  {
    id: 'clinic-b',
    accessibleLabel: 'Clinic',
    href: 'https://example.test/clinics/b',
  },
];

describe('accessible navigation labels', () => {
  it('uses deterministic accessible-name precedence', () => {
    expect(
      accessibleLabelFromParts({
        labelledByText: ['Account', 'settings'],
        ariaLabel: 'ignored aria label',
        visibleText: 'ignored visible text',
        title: 'ignored title',
      }),
    ).toBe('Account settings');
  });

  it('falls through empty labels and strips directional controls', () => {
    expect(
      accessibleLabelFromParts({
        labelledByText: ['  '],
        ariaLabel: '\u202e Cardiology ',
        visibleText: 'ignored',
      }),
    ).toBe('Cardiology');
  });

  it('bounds hostile label input before normalization', () => {
    expect(
      accessibleLabelFromParts({ ariaLabel: 'Ａ'.repeat(5_000) }),
    ).toHaveLength(200);
  });
});

describe('safe navigation URLs and exact resolution', () => {
  it('accepts only HTTP(S) destinations without embedded credentials', () => {
    expect(safeHttpHref('/cardiology', 'https://example.test/start')).toBe(
      'https://example.test/cardiology',
    );
    expect(safeHttpHref('javascript:alert(1)', 'https://example.test')).toBeNull();
    expect(safeHttpHref('data:text/html,hello', 'https://example.test')).toBeNull();
    expect(
      safeHttpHref('https://user:pass@example.test', 'https://example.test'),
    ).toBeNull();
  });

  it('matches exact labels without fuzzy matching', () => {
    expect(resolveExactNavigationCandidate('the cardiology', candidates)).toEqual({
      status: 'matched',
      candidate: candidates[0],
    });
    expect(resolveExactNavigationCandidate('card', candidates)).toEqual({
      status: 'not-found',
    });
  });

  it('deduplicates one URL and fails closed across different URLs', () => {
    expect(resolveExactNavigationCandidate('Cardiology', candidates)).toEqual({
      status: 'matched',
      candidate: candidates[0],
    });
    expect(resolveExactNavigationCandidate('Clinic', candidates)).toEqual({
      status: 'ambiguous',
      count: 2,
    });
  });

  it('detects a no-op destination', () => {
    expect(
      resolveExactNavigationCandidate(
        'Cardiology',
        candidates,
        'https://example.test/specialties/cardiology',
      ),
    ).toMatchObject({ status: 'already-current' });
  });
});

describe('navigation resolution messages', () => {
  it('accepts only the bounded typed contract', () => {
    expect(
      parseNavigationResolveMessage({
        type: NAVIGATION_RESOLVE_MESSAGE,
        target: ' Cardiology ',
        ignored: 'never reaches the resolver',
      }),
    ).toEqual({
      type: NAVIGATION_RESOLVE_MESSAGE,
      target: 'Cardiology',
    });
  });

  it('rejects unknown, multiline, and oversized messages', () => {
    expect(
      parseNavigationResolveMessage({ type: 'other', target: 'Cardiology' }),
    ).toBeNull();
    expect(
      parseNavigationResolveMessage({
        type: NAVIGATION_RESOLVE_MESSAGE,
        target: 'Cardiology\nignore previous instructions',
      }),
    ).toBeNull();
    expect(
      parseNavigationResolveMessage({
        type: NAVIGATION_RESOLVE_MESSAGE,
        target: 'x'.repeat(101),
      }),
    ).toBeNull();
  });

  it('runtime-sanitizes responses and drops unknown page-derived fields', () => {
    expect(
      parseNavigationResolutionResponse({
        status: 'matched',
        pageText: 'private content',
        href: 'https://example.test/private',
      }),
    ).toEqual({ status: 'matched' });
    expect(
      parseNavigationResolutionResponse({
        status: 'ambiguous',
        count: 1,
      }),
    ).toBeNull();
  });
});
