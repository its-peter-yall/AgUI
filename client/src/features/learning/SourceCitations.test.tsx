/**
 * ============================================================================
 * FILE: SourceCitations.test.tsx
 * LOCATION: client/src/features/learning/SourceCitations.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests validated citation footer rendering and link safety.
 *
 * ROLE IN PROJECT:
 *    Guards numbering, external link attributes, and empty state.
 *
 * KEY COMPONENTS:
 *    - SourceCitations tests
 *
 * DEPENDENCIES:
 *    - External: Testing Library, Vitest
 *    - Internal: SourceCitations
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/SourceCitations.test.tsx
 * ============================================================================
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SourceCitations } from './SourceCitations';

describe('SourceCitations', () => {
  it('numbers validated sources and opens safe external links', () => {
    render(
      <SourceCitations
        citations={[
          {
            source_id: 'source-1',
            citation_number: 1,
            title: 'Current documentation',
            url: 'https://example.com/docs',
            publisher: 'Example',
            published_at: null,
            retrieved_at: '2026-08-01T00:00:00Z',
          },
        ]}
      />,
    );
    const link = screen.getByRole('link', { name: /1.? current documentation/i });
    expect(link).toHaveAttribute('href', 'https://example.com/docs');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noreferrer noopener');
  });

  it('renders nothing for empty validated citations', () => {
    const { container } = render(<SourceCitations citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
