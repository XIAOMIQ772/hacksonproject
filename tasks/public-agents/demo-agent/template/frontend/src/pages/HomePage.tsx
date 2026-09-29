import { Link, useLocation, useNavigate } from 'react-router-dom';
import AuthEntrySection from '../components/AuthEntrySection';
import SearchPanel from '../components/SearchPanel';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';

function HomePage() {
  const navigate = useNavigate();
  const location = useLocation();
  const flashMessage = location.state && typeof location.state === 'object'
    ? (location.state as { message?: string; type?: string })
    : {};

  return (
    <div className="page-shell home-page">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <FlashMessage message={flashMessage.message} type={flashMessage.type || 'success'} />
          <section className="hero-panel">
            <div className="hero-copy">
              <h1>Small Train Ticket Booking System</h1>
              <p>Search trains, sign in, and complete a booking flow in the old-style 12306-inspired shell.</p>
              <div className="hero-actions">
                <Link className="primary-button" to="/register">
                  Register
                </Link>
                <Link className="secondary-button" to="/login">
                  Login
                </Link>
              </div>
            </div>
            <div className="hero-banner-grid">
              <img alt="Train travel banner" src="/assets/banner1.jpg" />
              <img alt="Rail booking banner" src="/assets/banner2.jpg" />
            </div>
          </section>
          <section className="content-panel">
            <h2 className="page-title">Search trains</h2>
            <p className="muted">Start from the homepage, submit your route, and continue into the result list.</p>
            <SearchPanel
              onSubmit={(values) => {
                navigate(
                  `/tickets?from=${encodeURIComponent(values.from)}&to=${encodeURIComponent(values.to)}&date=${encodeURIComponent(values.date)}`,
                );
              }}
              values={{
                from: 'Beijing',
                to: 'Shanghai',
                date: new Date().toISOString().slice(0, 10),
              }}
            />
          </section>
          <AuthEntrySection />
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}

export default HomePage;
