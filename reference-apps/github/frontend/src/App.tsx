import { Route, Routes } from 'react-router-dom';
import Header from './components/Header';
import { useSession } from './session';
import Home from './pages/Home';
import { Login, Signup, PasswordReset } from './pages/Auth';
import { SettingsIndex, SecuritySettings } from './pages/Settings';
import { YourOrgs, NewOrg, OwnerPage, Teams, NewTeam, TeamPage, People } from './pages/Orgs';
import GlobalSearch from './pages/GlobalSearch';
import NewRepo from './pages/NewRepo';
import RepoRoutes from './pages/Repo';

export default function App() {
  const { loaded } = useSession();
  return (
    <>
      <Header />
      <main className="max-w-6xl mx-auto px-4 py-4">
        {loaded && (
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/password_reset" element={<PasswordReset />} />
            <Route path="/settings" element={<SettingsIndex />} />
            <Route path="/settings/security" element={<SecuritySettings />} />
            <Route path="/organizations" element={<YourOrgs />} />
            <Route path="/organizations/new" element={<NewOrg />} />
            <Route path="/search" element={<GlobalSearch />} />
            <Route path="/new" element={<NewRepo />} />
            <Route path="/orgs/:org/repositories" element={<OwnerPage />} />
            <Route path="/orgs/:org/teams" element={<Teams />} />
            <Route path="/orgs/:org/new-team" element={<NewTeam />} />
            <Route path="/orgs/:org/teams/:team" element={<TeamPage tab="overview" />} />
            <Route path="/orgs/:org/teams/:team/members" element={<TeamPage tab="members" />} />
            <Route path="/orgs/:org/teams/:team/settings" element={<TeamPage tab="settings" />} />
            <Route path="/orgs/:org/people" element={<People />} />
            <Route path="/:owner" element={<OwnerPage />} />
            <Route path="/:owner/:repo/*" element={<RepoRoutes />} />
          </Routes>
        )}
      </main>
    </>
  );
}
