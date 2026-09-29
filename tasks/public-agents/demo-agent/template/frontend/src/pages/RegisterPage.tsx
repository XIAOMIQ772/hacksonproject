import axios from 'axios';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { FlashMessage, SiteFooter, SiteHeader } from '../components/SiteLayout';
import { useAuth } from '../context/AuthContext';

export default function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [form, setForm] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
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
      await register(form);
      setMessageType('success');
      setMessage('Registration successful. Redirecting to the homepage...');
      navigate('/', { state: { message: 'Registration successful.', type: 'success' } });
    } catch (error) {
      setMessageType('error');
      setMessage(axios.isAxiosError(error) ? error.response?.data?.message || 'Registration failed.' : 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <SiteHeader />
      <main className="page-main">
        <div className="container">
          <div className="breadcrumb">Current location: HOME &gt; Register</div>
          <FlashMessage message={message} type={messageType} />
          <section className="content-panel form-panel">
            <h1 className="page-title">Create your account</h1>
            <div className="form-grid">
              <label>
                Username
                <input
                  name="username"
                  onChange={(event) => updateField('username', event.target.value)}
                  placeholder="Choose a username"
                  type="text"
                  value={form.username}
                />
              </label>
              <label>
                Email
                <input
                  name="email"
                  onChange={(event) => updateField('email', event.target.value)}
                  placeholder="Enter your email address"
                  type="email"
                  value={form.email}
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  onChange={(event) => updateField('password', event.target.value)}
                  placeholder="Create a password"
                  type="password"
                  value={form.password}
                />
              </label>
              <label>
                Confirm password
                <input
                  name="confirmPassword"
                  onChange={(event) => updateField('confirmPassword', event.target.value)}
                  placeholder="Confirm the password"
                  type="password"
                  value={form.confirmPassword}
                />
              </label>
            </div>
            <div className="form-actions">
              <button className="primary-button" disabled={submitting} onClick={handleSubmit} type="button">
                {submitting ? 'Registering...' : 'Register'}
              </button>
              <Link className="secondary-button" to="/login">
                Already have an account
              </Link>
            </div>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
