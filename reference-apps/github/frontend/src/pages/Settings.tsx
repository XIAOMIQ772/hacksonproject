import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { useSession } from '../session';
import { Field, errorsOf, FieldError } from '../components/ui';

function SettingsNav() {
  return (
    <nav className="w-56 shrink-0">
      <ul>
        <li><Link className="block py-1 text-blue-700" to="/settings/security">Password and authentication</Link></li>
      </ul>
    </nav>
  );
}

export function SignInRequired() {
  return <p className="py-6 text-lg">Sign in required. <Link className="text-blue-700" to="/login">Sign in to continue</Link></p>;
}

export function SettingsIndex() {
  const { user } = useSession();
  if (!user) return <SignInRequired />;
  return (
    <div className="flex gap-6">
      <SettingsNav />
      <section>
        <h1 className="text-2xl mb-2">Settings</h1>
        <p>Account: {user.email}</p>
      </section>
    </div>
  );
}

export function SecuritySettings() {
  const { user } = useSession();
  const [f, setF] = useState({ current: '', password: '', confirm: '' });
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [ok, setOk] = useState(false);
  if (!user) return <SignInRequired />;
  const set = (k: keyof typeof f) => (v: string) => setF((x) => ({ ...x, [k]: v }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api('POST', '/settings/password', f);
      setErrs({});
      setOk(true);
    } catch (ex) {
      setOk(false);
      setErrs(errorsOf(ex));
    }
    setF({ current: '', password: '', confirm: '' });
  };
  return (
    <div className="flex gap-6">
      <SettingsNav />
      <section className="max-w-md w-full">
        <h1 className="text-2xl mb-4">Password and authentication</h1>
        <h2 className="text-lg font-semibold mb-2">Change password</h2>
        <form onSubmit={submit} noValidate>
          <Field label="Current password" type="password" value={f.current} onChange={set('current')} error={errs.current} autoComplete="current-password" />
          <Field label="New password" type="password" value={f.password} onChange={set('password')} error={errs.password} autoComplete="new-password" />
          <Field label="Confirm password" type="password" value={f.confirm} onChange={set('confirm')} error={errs.confirm} autoComplete="new-password" />
          <FieldError id="password-form-err" msg={errs._} />
          <button type="submit" className="border rounded px-3 py-1 font-semibold">Update password</button>
          {ok && <p role="status" className="mt-3 text-green-800">Password updated</p>}
        </form>
      </section>
    </div>
  );
}
