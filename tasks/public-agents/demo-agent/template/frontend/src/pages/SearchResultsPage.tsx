import axios from 'axios';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { searchTickets } from '../api/search';
import SearchPanel from '../components/SearchPanel';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';

type SearchPayload = {
  empty: boolean;
  emptyMessage?: string;
  resultCount: number;
  search: {
    date: string;
    from: string;
    to: string;
  };
  trains: Array<{
    arrivalTime: string;
    departureStation: string;
    departureTime: string;
    destinationStation: string;
    id: number;
    trainNo: string;
  }>;
};

export default function SearchResultsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<SearchPayload | null>(null);
  const [message, setMessage] = useState('');

  const values = useMemo(
    () => ({
      from: searchParams.get('from') || 'Beijing',
      to: searchParams.get('to') || 'Shanghai',
      date: searchParams.get('date') || new Date().toISOString().slice(0, 10),
    }),
    [searchParams],
  );

  useEffect(() => {
    searchTickets(values)
      .then((response) => {
        setData(response.data);
        setMessage('');
      })
      .catch((error) => {
        setData(null);
        setMessage(
          axios.isAxiosError(error)
            ? error.response?.data?.message || 'Failed to load search results.'
            : 'Failed to load search results.',
        );
      });
  }, [values]);

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <div className="breadcrumb">Current location: HOME &gt; Tickets</div>
          <SearchPanel
            onSubmit={(nextValues) => {
              navigate(
                `/tickets?from=${encodeURIComponent(nextValues.from)}&to=${encodeURIComponent(nextValues.to)}&date=${encodeURIComponent(nextValues.date)}`,
              );
            }}
            values={values}
          />
          <FlashMessage message={message} type="error" />
          <section className="content-panel">
            <h1 className="page-title">Search results</h1>
            {data ? (
              <>
                <p className="muted">
                  {data.search.from} to {data.search.to} on {data.search.date}
                </p>
                <p className="muted">{data.resultCount} matching train(s).</p>
                {data.empty ? (
                  <div className="empty-results">
                    <img alt="No result" src="/assets/empty.png" />
                    <strong>No direct result found</strong>
                    <p>
                      Submitted route: {data.search.from} to {data.search.to} on {data.search.date}
                    </p>
                    <p>{data.emptyMessage}</p>
                  </div>
                ) : (
                  <div className="results-table-wrap">
                    <table className="results-table">
                      <thead>
                        <tr>
                          <th>Train No.</th>
                          <th>Departure</th>
                          <th>Arrival</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.trains.map((train) => (
                          <tr key={train.id}>
                            <td>
                              <strong>{train.trainNo}</strong>
                              <div>
                                <button
                                  className="mini-book-button"
                                  onClick={() => navigate(`/booking?trainId=${encodeURIComponent(String(train.id))}&date=${encodeURIComponent(data.search.date)}`)}
                                  type="button"
                                >
                                  Book this train
                                </button>
                              </div>
                            </td>
                            <td>
                              {train.departureStation}
                              <div>{train.departureTime}</div>
                            </td>
                            <td>
                              {train.destinationStation}
                              <div>{train.arrivalTime}</div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            ) : (
              <p className="muted">Search criteria, result count, and train list will be rendered here.</p>
            )}
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
