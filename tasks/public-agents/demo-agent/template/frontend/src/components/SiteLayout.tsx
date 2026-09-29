import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function FlashMessage({ message, type = 'info' }: { message?: string; type?: string }) {
  if (!message) {
    return null;
  }

  return <div className={`flash-message ${type}`}>{message}</div>;
}

export function SiteHeader() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();

  async function handleLogout() {
    await logout();
    navigate('/');
  }

  return (
    <header className="site-header">
      <div className="top-bar container">
        <Link className="brand" to="/">
          <img alt="12306 logo" className="brand-logo" src="/assets/logo.png" />
        </Link>
        <div className="utility-links">
          {user ? (
            <button className="utility-link button-link" onClick={() => navigate('/')}>
              {user.username}
            </button>
          ) : (
            <Link className="utility-link" to="/login">
              Login
            </Link>
          )}
          {user ? (
            <button className="utility-link button-link" onClick={handleLogout}>
              Sign Out
            </button>
          ) : (
            <Link className="utility-link" to="/register">
              Register
            </Link>
          )}
          <span className="utility-link muted">English</span>
          <span className="utility-link muted">Contact us</span>
        </div>
      </div>
      <nav className="main-nav">
        <div className="nav-inner">
          <NavLink className="nav-item" to="/">
            Home
          </NavLink>
          <NavLink className="nav-item" to="/tickets">
            Tickets
          </NavLink>
        </div>
      </nav>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="container footer-content">
        <p>COPYRIGHT©2008-2026 CHINA RAILWAY DEMO, ALL RIGHTS RESERVED</p>
        <p>京公网安备 11010802038392号 | 京ICP备05020493号-4</p>
      </div>
    </footer>
  );
}
