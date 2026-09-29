import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import SearchResultsPage from '../../pages/SearchResultsPage';

describe('REQ-2.1 search result page contract', () => {
  it('keeps the result heading and placeholder summary region', () => {
    render(
      <MemoryRouter>
        <SearchResultsPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: 'Search results' })).toBeInTheDocument();
    expect(screen.getByText('Search criteria, result count, and train list will be rendered here.')).toBeInTheDocument();
  });
});
