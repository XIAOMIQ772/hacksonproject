import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, enc } from '../api';
import { useSession } from '../session';
import { Combobox, Field, FieldError, errorsOf } from '../components/ui';
import { SignInRequired } from './Settings';

export default function NewRepo() {
  const { user, orgs } = useSession();
  const nav = useNavigate();
  const [owner, setOwner] = useState(user?.username || '');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState('public');
  const [readme, setReadme] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});
  if (!user) return <SignInRequired />;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api('POST', '/repos', { owner, name, description, visibility, readme });
      nav(`/${enc(r.owner)}/${enc(r.name)}`);
    } catch (ex) {
      setErrs(errorsOf(ex));
    }
  };
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl mb-4">Create a new repository</h1>
      <form onSubmit={submit} noValidate>
        <Combobox label="Owner" value={owner} onChange={setOwner}
          options={[user.username, ...orgs.map((o) => o.login)].map((o) => ({ value: o, label: o }))} />
        <FieldError id="owner-err" msg={errs.owner} />
        <Field label="Repository name" value={name} onChange={setName} error={errs.name} />
        <Field label="Description" value={description} onChange={setDescription} />
        <fieldset className="mb-3">
          <legend className="font-semibold text-sm mb-1">Visibility</legend>
          <label className="block"><input type="radio" name="visibility" checked={visibility === 'public'} onChange={() => setVisibility('public')} /> Public</label>
          <label className="block"><input type="radio" name="visibility" checked={visibility === 'private'} onChange={() => setVisibility('private')} /> Private</label>
        </fieldset>
        <label className="block mb-3"><input type="checkbox" checked={readme} onChange={(e) => setReadme(e.target.checked)} /> Add a README file</label>
        <FieldError id="repo-err" msg={errs._} />
        <button type="submit" className="bg-green-700 text-white rounded px-3 py-1 font-semibold">Create repository</button>
      </form>
    </div>
  );
}
