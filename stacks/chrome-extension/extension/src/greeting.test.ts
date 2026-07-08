import { describe, expect, it } from 'vitest';

import { greeting } from './greeting';

describe('greeting', () => {
  it('greets the project by default', () => {
    expect(greeting()).toContain('{{ project_name }}');
  });

  it('greets a given name', () => {
    expect(greeting('world')).toBe('hello from world');
  });
});
