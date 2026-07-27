import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

interface Manifest {
  permissions?: string[];
  optional_permissions?: string[];
  host_permissions?: string[];
  optional_host_permissions?: string[];
  content_scripts?: Array<{ matches?: string[] }>;
}

const manifest = JSON.parse(
  readFileSync(new URL('../../public/manifest.json', import.meta.url), 'utf8'),
) as Manifest;

describe('manifest permission budget', () => {
  it('keeps the required API permissions exact', () => {
    expect(manifest.permissions).toEqual(['storage', 'sidePanel']);
    expect(manifest.optional_permissions ?? []).toEqual([]);
  });

  it('does not request broad host access', () => {
    expect(manifest.host_permissions ?? []).toEqual([]);
    expect(manifest.optional_host_permissions ?? []).toEqual([]);
    expect(
      JSON.stringify(manifest),
    ).not.toMatch(/<all_urls>|\*:\/\/\*\/\*/);
  });

  it('limits content scripts to the local synthetic-test origins', () => {
    expect(manifest.content_scripts).toEqual([
      expect.objectContaining({
        matches: ['http://localhost/*', 'http://127.0.0.1/*'],
      }),
    ]);
  });
});
