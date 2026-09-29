import axios from 'axios';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [form, setForm] = useState({
    account: '',
    password: '',
  });
  const [message, setMessage] = useState('');
  const [messageType, setMessageType] = useState<'error' | 'success'>('success');
  const [submitting, setSubmitting] = useState(false);

  function updateField(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit() {
    setSubmitting(true);
    setMessage('');

    try {
      await login(form);
      setMessageType('success');
      setMessage('Login successful. Redirecting to the homepage...');
      navigate('/', { state: { message: 'Login successful.', type: 'success' } });
    } catch (error) {
      setMessageType('error');
      setMessage(axios.isAxiosError(error) ? error.response?.data?.message || 'Login failed.' : 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <div className="breadcrumb">Current location: HOME &gt; Login</div>
          <FlashMessage message={message} type={messageType} />
          <section className="content-panel form-panel">
            <h1 className="page-title">Sign in to your account</h1>
            <div className="form-grid">
              <label>
                Username or email
                <input
                  name="account"
                  onChange={(event) => updateField('account', event.target.value)}
                  placeholder="Enter your username or email"
                  type="text"
                  value={form.account}
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  onChange={(event) => updateField('password', event.target.value)}
                  placeholder="Enter your password"
                  type="password"
                  value={form.password}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary-button" disabled={submitting} onClick={handleSubmit} type="button">
                {submitting ? 'Signing in...' : 'Login'}
              </button>
              <Link className="secondary-button" to="/register">
                Need an account
              </Link>
            </div>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
