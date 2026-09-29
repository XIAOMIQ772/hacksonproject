import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import SearchResultsPage from '../../pages/SearchResultsPage';

vi.mock('../../api/search', () => ({
  searchTickets: vi.fn().mockResolvedValue({
    data: {
      search: { from: 'Beijing', to: 'Shanghai', date: '2026-07-07' },
      resultCount: 1,
      trains: [
        {
          id: 1,
          trainNo: 'G101',
          departureCity: 'Beijing',
          destinationCity: 'Shanghai',
          departureStation: 'Beijing(北京)',
          destinationStation: 'Shanghai(上海)',
          departureTime: '07:00',
          arrivalTime: '12:38',
        },
      ],
      empty: false,
      emptyMessage: '',
    },
  }),
  fetchTrainDetail: vi.fn(),
}));

describe('REQ-2.3 booking entry from result list', () => {
  it('renders a booking action for each result row', async () => {
    render(
      <MemoryRouter initialEntries={['/tickets?from=Beijing&to=Shanghai&date=2026-07-07']}>
        <SearchResultsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: 'Book this train' })).toBeInTheDocument();
  });
});
