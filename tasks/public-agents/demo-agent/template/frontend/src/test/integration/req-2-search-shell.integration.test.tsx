import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import SearchResultsPage from '../../pages/SearchResultsPage';

describe('REQ-2 search shell', () => {
  it('renders the search panel and result page heading', () => {
    render(
      <MemoryRouter>
        <SearchResultsPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Search results' })).toBeInTheDocument();
    expect(screen.getByLabelText('From')).toBeInTheDocument();
    expect(screen.getByLabelText('To')).toBeInTheDocument();
    expect(screen.getByLabelText('Date')).toBeInTheDocument();
  });
});
