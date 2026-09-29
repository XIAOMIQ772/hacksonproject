import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import SearchResultsPage from '../../pages/SearchResultsPage';

vi.mock('../../api/search', () => ({
  searchTickets: vi.fn().mockResolvedValue({
    data: {
      search: { from: 'Beijing', to: 'Kunming', date: '2026-07-07' },
      resultCount: 0,
      trains: [],
      empty: true,
      emptyMessage: 'No trains matched the submitted search criteria.',
    },
  }),
}));

describe('REQ-2.2 empty search results page', () => {
  it('renders an explicit empty-result message', async () => {
    render(
      <MemoryRouter initialEntries={['/tickets?from=Beijing&to=Kunming&date=2026-07-07']}>
        <SearchResultsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('No trains matched the submitted search criteria.')).toBeInTheDocument();
  });
});
