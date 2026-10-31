import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { useAuth } from "./lib/auth";
import { LoginPage } from "./pages/Login";
import { PlaceholderPage } from "./pages/Placeholder";
import { TodayPage } from "./pages/Today";

export function App() {
  const { status } = useAuth();

  if (status === "checking") {
    return <div className="min-h-screen bg-bg" />;
  }

  if (status === "anon") {
    return <LoginPage />;
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/workouts" element={<PlaceholderPage title="Workouts" />} />
        <Route path="/trends" element={<PlaceholderPage title="Trends" />} />
        <Route path="/coach" element={<PlaceholderPage title="Coach" />} />
        <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
      </Routes>
    </AppShell>
  );
}
