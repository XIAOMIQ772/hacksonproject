import { Route, Routes } from 'react-router-dom';
import HomePage from './pages/HomePage';
import CreatePage from './pages/CreatePage';
import EditorPage from './pages/EditorPage';

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/new" element={<CreatePage />} />
      <Route path="/workbooks/:id" element={<EditorPage />} />
      <Route path="*" element={<HomePage />} />
    </Routes>
  );
}

export default App;
