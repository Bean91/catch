import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/shell/AppShell";
import { CardSkeleton } from "./components/ui/Skeleton";
import { useAuth } from "./lib/auth";
import { LoginPage } from "./pages/Login";
import { TodayPage } from "./pages/Today";

// Only Today (the landing screen, and the one page the offline shell needs) is eager —
// every other route (and its chart code) is its own chunk, fetched on first visit, to keep
// the initial bundle under the 250KB-gzip budget as more screens are added.
const WorkoutsPage = lazy(() => import("./pages/Workouts").then((m) => ({ default: m.WorkoutsPage })));
const WorkoutDetailPage = lazy(() => import("./pages/WorkoutDetail").then((m) => ({ default: m.WorkoutDetailPage })));
const DuplicatesPage = lazy(() => import("./pages/Duplicates").then((m) => ({ default: m.DuplicatesPage })));
const TrendsPage = lazy(() => import("./pages/Trends").then((m) => ({ default: m.TrendsPage })));
const BodyPage = lazy(() => import("./pages/Body").then((m) => ({ default: m.BodyPage })));
const CoachPage = lazy(() => import("./pages/Coach").then((m) => ({ default: m.CoachPage })));
const NutritionPage = lazy(() => import("./pages/Nutrition").then((m) => ({ default: m.NutritionPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
const MemoryPage = lazy(() => import("./pages/Memory").then((m) => ({ default: m.MemoryPage })));

function RouteFallback() {
  return (
    <div className="flex flex-col gap-4">
      <CardSkeleton lines={2} />
      <CardSkeleton lines={2} />
    </div>
  );
}

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
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/workouts" element={<WorkoutsPage />} />
          <Route path="/workouts/duplicates" element={<DuplicatesPage />} />
          <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
          <Route path="/trends" element={<TrendsPage />} />
          <Route path="/body" element={<BodyPage />} />
          <Route path="/nutrition" element={<NutritionPage />} />
          <Route path="/coach" element={<CoachPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/memory" element={<MemoryPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
