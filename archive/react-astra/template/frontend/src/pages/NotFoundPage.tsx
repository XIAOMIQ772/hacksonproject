import { Link } from 'react-router-dom';

function NotFoundPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-16">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="mt-4">
        <Link to="/" className="text-blue-700 underline">
          Go to home page
        </Link>
      </p>
    </main>
  );
}

export default NotFoundPage;
