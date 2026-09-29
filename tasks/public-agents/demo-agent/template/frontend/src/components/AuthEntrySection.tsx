import { Link } from 'react-router-dom';

function EntryCard({
  title,
  description,
  actionLabel,
  to,
}: {
  actionLabel: string;
  description: string;
  title: string;
  to: string;
}) {
  return (
    <article className="content-card auth-entry-card">
      <h2>{title}</h2>
      <p>{description}</p>
      <Link className="primary-button" to={to}>
        {actionLabel}
      </Link>
    </article>
  );
}

export default function AuthEntrySection() {
  return (
    <section className="auth-entry-section">
      <EntryCard
        actionLabel="Create account"
        description="Open the registration flow to create an account and move into the authenticated state."
        title="New to the system?"
        to="/register"
      />
      <EntryCard
        actionLabel="Sign in"
        description="Use an existing username or email plus password to load a persisted account session."
        title="Already registered?"
        to="/login"
      />
    </section>
  );
}
