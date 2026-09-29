import axios from 'axios';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { createBooking, fetchBookingOptions } from '../api/booking';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';

export default function BookingPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [train, setTrain] = useState<null | {
    arrivalTime: string;
    departureDate: string;
    departureStation: string;
    departureTime: string;
    destinationStation: string;
    trainNo: string;
  }>(null);
  const [form, setForm] = useState({
    passengerName: '',
    passengerIdNumber: '',
    seatType: 'Second Class',
  });
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'error' | 'success'>('error');
  const [submitting, setSubmitting] = useState(false);

  const trainId = searchParams.get('trainId') || '';
  const date = searchParams.get('date') || '';

  function updateField(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit() {
    if (!trainId) {
      setMessageType('error');
      setMessage('Missing selected train.');
      return;
    }

    setSubmitting(true);
    setMessage('');
    try {
      const response = await createBooking({
        trainId: Number(trainId),
        travelDate: train?.departureDate || date,
        passengerName: form.passengerName,
        passengerIdNumber: form.passengerIdNumber,
        seatType: form.seatType,
      });
      setMessageType('success');
      setMessage('Booking created successfully. Redirecting to the booking result...');
      navigate(`/booking/success/${response.data.booking.id}`);
    } catch (error) {
      setMessageType('error');
      setMessage(
        axios.isAxiosError(error)
          ? error.response?.data?.message || 'Failed to submit the booking.'
          : 'Failed to submit the booking.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    if (!trainId) {
      setMessage('Missing selected train.');
      setTrain(null);
      return;
    }

    fetchBookingOptions({ trainId, date })
      .then((response) => {
        setTrain(response.data.train);
        setForm({
          passengerName: response.data.passengerDefaults?.passengerName || '',
          passengerIdNumber: response.data.passengerDefaults?.passengerIdNumber || '',
          seatType: response.data.passengerDefaults?.seatType || 'Second Class',
        });
        setMessage('');
      })
      .catch((error) => {
        setTrain(null);
        setMessage(
          axios.isAxiosError(error)
            ? error.response?.data?.message || 'Failed to load the selected train.'
            : 'Failed to load the selected train.',
        );
      });
  }, [date, trainId]);

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <div className="breadcrumb">Current location: HOME &gt; Booking</div>
          <FlashMessage message={message} type={messageType} />
          <section className="content-panel booking-shell">
            <h1 className="page-title">Booking page</h1>
            <section className="booking-section">
              <div className="booking-section-header">
                <h2>Selected train</h2>
                <span>Protected booking flow shell</span>
              </div>
              {train ? (
                <>
                  <div className="booking-train-card">
                    <div>
                      <strong>{train.trainNo}</strong>
                      <p>{train.departureDate || date}</p>
                    </div>
                    <div>
                      <strong>{train.departureStation}</strong>
                      <p>{train.departureTime}</p>
                    </div>
                    <div>
                      <strong>{train.destinationStation}</strong>
                      <p>{train.arrivalTime}</p>
                    </div>
                  </div>
                  <div className="booking-seat-list">
                    <div className="booking-seat-item">Travel date: {train.departureDate || date}</div>
                    <div className="booking-seat-item">Suggested seat: {form.seatType}</div>
                    <div className="booking-seat-item">Passenger record: current user</div>
                    <div className="booking-seat-item">Order status: pending submission</div>
                  </div>
                </>
              ) : (
                <p className="muted">The selected train context will be loaded here for the downstream booking flow.</p>
              )}
            </section>
            <section className="booking-section">
              <div className="booking-section-header">
                <h2>Passenger information</h2>
                <span>Passenger form shell is ready for booking submission.</span>
              </div>
              <div className="form-grid" style={{ padding: '16px 14px 12px' }}>
                <label>
                  Passenger name
                  <input
                    name="passengerName"
                    onChange={(event) => updateField('passengerName', event.target.value)}
                    placeholder="Enter passenger name"
                    type="text"
                    value={form.passengerName}
                  />
                </label>
                <label>
                  ID number
                  <input
                    name="passengerIdNumber"
                    onChange={(event) => updateField('passengerIdNumber', event.target.value)}
                    placeholder="Enter certificate number"
                    type="text"
                    value={form.passengerIdNumber}
                  />
                </label>
                <label>
                  Seat type
                  <select
                    name="seatType"
                    onChange={(event) => updateField('seatType', event.target.value)}
                    value={form.seatType}
                  >
                    <option value="Second Class">Second Class</option>
                    <option value="First Class">First Class</option>
                    <option value="Business Class">Business Class</option>
                  </select>
                </label>
              </div>
              <div className="booking-actions">
                <button className="primary-button wide" onClick={handleSubmit} type="button">
                  {submitting ? 'Submitting...' : 'Submit booking'}
                </button>
              </div>
              <div className="booking-tips-card">
                <h3>Submission reminder</h3>
                <p>The booking submit flow now creates a record and redirects to the dedicated success result page.</p>
              </div>
            </section>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
