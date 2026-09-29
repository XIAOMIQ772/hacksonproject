import { useEffect, useState } from 'react';

type SearchValues = {
  date: string;
  from: string;
  to: string;
};

export default function SearchPanel({
  onSubmit,
  values,
}: {
  onSubmit?: (values: SearchValues) => void | Promise<void>;
  values: SearchValues;
}) {
  const [form, setForm] = useState<SearchValues>(values);

  useEffect(() => {
    setForm(values);
  }, [values]);

  function updateField(field: keyof SearchValues, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <section className="ticket-search-panel">
      <div className="ticket-search-row">
        <div className="ticket-search-box">
          <label htmlFor="search-from">From</label>
          <input
            id="search-from"
            onChange={(event) => updateField('from', event.target.value)}
            placeholder="From"
            type="text"
            value={form.from}
          />
        </div>
        <div className="ticket-search-box">
          <label htmlFor="search-to">To</label>
          <input
            id="search-to"
            onChange={(event) => updateField('to', event.target.value)}
            placeholder="To"
            type="text"
            value={form.to}
          />
        </div>
        <div className="ticket-search-box">
          <label htmlFor="search-date">Date</label>
          <input
            id="search-date"
            onChange={(event) => updateField('date', event.target.value)}
            type="date"
            value={form.date}
          />
        </div>
        <button
          className="primary-button ticket-search-submit"
          onClick={() => onSubmit?.(form)}
          type="button"
        >
          Search
        </button>
      </div>
    </section>
  );
}
