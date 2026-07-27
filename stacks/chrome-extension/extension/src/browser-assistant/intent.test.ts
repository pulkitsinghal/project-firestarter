import { describe, expect, it } from 'vitest';

import {
  looksLikeNavigationCommand,
  normalizeUserLabel,
  parseNavigationIntent,
} from './intent';

const DESTINATIONS = [
  { id: 'home', aliases: ['home', 'start'] },
  { id: 'settings', aliases: ['settings', 'preferences'] },
] as const;

describe('browser intent parsing', () => {
  it('maps an explicit command through a product-owned alias catalog', () => {
    expect(parseNavigationIntent('Please go to Preferences.', DESTINATIONS)).toEqual({
      scope: 'extension',
      destination: 'settings',
      requestedLabel: 'Preferences',
    });
  });

  it('normalizes compatibility characters and strips invisible controls', () => {
    expect(normalizeUserLabel('Ｔｈｅ\u202e Settings')).toBe('settings');
  });

  it('rejects ordinary prose, multiline input, and incomplete commands', () => {
    expect(parseNavigationIntent('Settings are useful', DESTINATIONS)).toBeNull();
    expect(parseNavigationIntent('go to\nsettings', DESTINATIONS)).toBeNull();
    expect(parseNavigationIntent('go to', DESTINATIONS)).toBeNull();
  });

  it('fails closed for unknown destinations by default', () => {
    expect(parseNavigationIntent('go to billing', DESTINATIONS)).toBeNull();
  });

  it('allows an explicit page qualifier without treating it as an extension alias', () => {
    expect(
      parseNavigationIntent('go to Settings on the current page', DESTINATIONS),
    ).toEqual({ scope: 'page', target: 'Settings' });
  });

  it('requires a known destination when explicitly scoped to the extension', () => {
    expect(
      parseNavigationIntent('go to billing in the extension', DESTINATIONS, {
        unknownDestination: 'page',
      }),
    ).toBeNull();
  });

  it('can opt unknown commands into the separate exact-page resolver', () => {
    expect(
      parseNavigationIntent('go to Cardiology', DESTINATIONS, {
        unknownDestination: 'page',
      }),
    ).toEqual({ scope: 'page', target: 'Cardiology' });
  });

  it('bounds command length before parsing', () => {
    expect(looksLikeNavigationCommand(`go to ${'x'.repeat(160)}`)).toBe(false);
  });
});
