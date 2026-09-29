import axios from 'axios';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { fetchBookingResult } from '../api/booking';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';

export default function BookingSuccessPage() {
  const { bookingId = '' } = useParams();
  const [booking, setBooking] = useState<null | {
    bookingNumber: string;
    passengerIdNumber: string;
    passengerName: string;
    seatType: string;
    status: string;
    train: {
      arrivalTime: string;
      departureStation: string;
      departureTime: string;
      destinationStation: string;
      trainNo: string;
    };
    travelDate: string;
  }>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!bookingId) {
      setBooking(null);
      setMessage('Missing booking record.');
      return;
    }

    fetchBookingResult(bookingId)
      .then((response) => {
        setBooking(response.data.booking);
        setMessage('');
      })
      .catch((error) => {
        setBooking(null);
        setMessage(
          axios.isAxiosError(error)
            ? error.response?.data?.message || 'Failed to load the booking result.'
            : 'Failed to load the booking result.',
        );
      });
  }, [bookingId]);

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <div className="breadcrumb">Current location: HOME &gt; Booking &gt; Success</div>
          <FlashMessage message={message} type="error" />
          <section className="content-panel booking-shell">
            <h1 className="page-title">Booking success</h1>
            <div className="booking-section">
              <div className="booking-section-header">
                <h2>Booking result</h2>
                <span>The stored booking record has been loaded successfully.</span>
              </div>
              {booking ? (
                <>
                  <div className="booking-train-card">
                    <div>
                      <strong>{booking.train.trainNo}</strong>
                      <p>{booking.travelDate}</p>
                    </div>
                    <div>
                      <strong>{booking.train.departureStation}</strong>
                      <p>{booking.train.departureTime}</p>
                    </div>
                    <div>
                      <strong>{booking.train.destinationStation}</strong>
                      <p>{booking.train.arrivalTime}</p>
                    </div>
                  </div>
                  <table className="booking-confirm-table">
                    <thead>
                      <tr>
                        <th>Booking number</th>
                        <th>Passenger</th>
                        <th>ID number</th>
                        <th>Seat type</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>{booking.bookingNumber}</td>
                        <td>{booking.passengerName}</td>
                        <td>{booking.passengerIdNumber}</td>
                        <td>{booking.seatType}</td>
                        <td>{booking.status}</td>
                      </tr>
                    </tbody>
                  </table>
                </>
              ) : (
                <div className="booking-tips-card">
                  <h3>Pending result load</h3>
                  <p>Booking record {bookingId || 'unknown'} will be loaded here when it becomes available.</p>
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
