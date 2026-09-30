import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import { useSession } from '../session';
import { Field, FieldError, errorsOf } from '../components/ui';

const btn = 'bg-green-700 text-white rounded px-3 py-1 font-semibold';

export function Login() {
  const { refresh } = useSession();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState('');
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', '/login', { login, password });
      await refresh();
      nav(params.get('return_to') || '/', { replace: true });
    } catch {
      setErr('Invalid credentials');
      setPassword('');
    }
  };
  return (
    <div className="max-w-sm mx-auto">
      <h1 className="text-2xl mb-4">Sign in to GitHub</h1>
      {params.get('registered') && <p role="status" className="mb-3 text-green-800">Account created. Sign in to continue.</p>}
      {params.get('reset') && <p role="status" className="mb-3 text-green-800">Password updated. Sign in with your new password.</p>}
      <form onSubmit={submit} noValidate>
        <Field label="Username or email" value={login} onChange={setLogin} autoComplete="username" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        <FieldError id="login-error" msg={err} />
        <button type="submit" className={`${btn} w-full mt-2`}>Sign in</button>
      </form>
      <p className="mt-4"><Link className="text-blue-700" to="/password_reset">Forgot password</Link></p>
      <p className="mt-2">New to GitHub? <Link className="text-blue-700" to="/signup">Create an account</Link></p>
    </div>
  );
}

export function Signup() {
  const nav = useNavigate();
  const [f, setF] = useState({ username: '', email: '', password: '', confirm: '' });
  const [agree, setAgree] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', '/signup', { ...f, agree });
      nav('/login?registered=1');
    } catch (ex) {
      setErrs(errorsOf(ex));
      setF((x) => ({ ...x, password: '', confirm: '' }));
    }
  };
  return (
    <div className="max-w-sm mx-auto">
      <h1 className="text-2xl mb-4">Create your account</h1>
      <form onSubmit={submit} noValidate>
        <Field label="Username" value={f.username} onChange={set('username')} error={errs.username} autoComplete="username" />
        <Field label="Email" type="email" value={f.email} onChange={set('email')} error={errs.email} autoComplete="email" />
        <Field label="Password" type="password" value={f.password} onChange={set('password')} error={errs.password} autoComplete="new-password" />
        <Field label="Confirm password" type="password" value={f.confirm} onChange={set('confirm')} error={errs.confirm} autoComplete="new-password" />
        <div className="mb-3">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)}
              aria-invalid={errs.agree ? true : undefined} aria-describedby={errs.agree ? 'agree-err' : undefined} />
            Agree to the terms
          </label>
          <FieldError id="agree-err" msg={errs.agree} />
        </div>
        <FieldError id="signup-err" msg={errs._} />
        <button type="submit" className={`${btn} w-full`}>Create account</button>
      </form>
    </div>
  );
}

export function PasswordReset() {
  const [email, setEmail] = useState('');
  const [step, setStep] = useState(1);
  const [f, setF] = useState({ code: '', password: '', confirm: '' });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [done, setDone] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const send = (e: React.FormEvent) => {
    e.preventDefault();
    setErrs({});
    setDone(false);
    setStep(2);
  };
  const reset = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', '/password-reset', { email, ...f });
      setErrs({});
      setDone(true);
      setF({ code: '', password: '', confirm: '' });
    } catch (ex) {
      setDone(false);
      setErrs(errorsOf(ex));
      setF((x) => ({ ...x, password: '', confirm: '' }));
    }
  };
  return (
    <div className="max-w-sm mx-auto">
      <h1 className="text-2xl mb-4">Reset your password</h1>
      <form onSubmit={send} noValidate>
        <Field label="Email" type="email" value={email} onChange={(v) => { setEmail(v); }} error={errs.email} autoComplete="email" />
        {step === 1 && <button type="submit" className={`${btn} w-full`}>Send reset link</button>}
      </form>
      {step === 2 && (
        <form onSubmit={reset} noValidate className="mt-4">
          <p className="mb-3">Enter the verification code shown below. No email is sent in this local product.</p>
          <p className="mb-3">Verification code: <strong className="font-mono text-lg">123456</strong></p>
          <Field label="Verification code" value={f.code} onChange={set('code')} error={errs.code} autoComplete="one-time-code" />
          <Field label="New password" type="password" value={f.password} onChange={set('password')} error={errs.password} autoComplete="new-password" />
          <Field label="Confirm password" type="password" value={f.confirm} onChange={set('confirm')} error={errs.confirm} autoComplete="new-password" />
          <button type="submit" className={`${btn} w-full`}>Reset password</button>
          {done && <p role="status" className="mt-3 text-green-800">Password updated</p>}
          {done && <p className="mt-2"><Link className="text-blue-700" to="/login">Return to sign in</Link></p>}
        </form>
      )}
    </div>
  );
}
