import { lazy, Suspense, useEffect } from "react";
import { Route, Routes, useNavigate } from "react-router-dom";
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
const GymPage = lazy(() => import("./pages/Gym").then((m) => ({ default: m.GymPage })));
const MuscleReadinessPage = lazy(() => import("./pages/MuscleReadiness").then((m) => ({ default: m.MuscleReadinessPage })));
const TestCenterPage = lazy(() => import("./pages/TestCenter").then((m) => ({ default: m.TestCenterPage })));
const TestDetailPage = lazy(() => import("./pages/TestDetail").then((m) => ({ default: m.TestDetailPage })));
const PieceTestDetailPage = lazy(() => import("./pages/PieceTestDetail").then((m) => ({ default: m.PieceTestDetailPage })));
const TrendsPage = lazy(() => import("./pages/Trends").then((m) => ({ default: m.TrendsPage })));
const TrainingIntelligencePage = lazy(() => import("./pages/TrainingIntelligence").then((m) => ({ default: m.TrainingIntelligencePage })));
const BodyPage = lazy(() => import("./pages/Body").then((m) => ({ default: m.BodyPage })));
const CoachPage = lazy(() => import("./pages/Coach").then((m) => ({ default: m.CoachPage })));
const NutritionPage = lazy(() => import("./pages/Nutrition").then((m) => ({ default: m.NutritionPage })));
const AiProvidersPage = lazy(() => import("./pages/AiProviders").then((m) => ({ default: m.AiProvidersPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));
const MemoryPage = lazy(() => import("./pages/Memory").then((m) => ({ default: m.MemoryPage })));
const RoutesPage = lazy(() => import("./pages/Routes").then((m) => ({ default: m.RoutesPage })));
const RouteDetailPage = lazy(() => import("./pages/RouteDetail").then((m) => ({ default: m.RouteDetailPage })));
const CalendarPage = lazy(() => import("./pages/Calendar").then((m) => ({ default: m.CalendarPage })));
const EventDetailPage = lazy(() => import("./pages/EventDetail").then((m) => ({ default: m.EventDetailPage })));
const PlanPage = lazy(() => import("./pages/Plan").then((m) => ({ default: m.PlanPage })));
const LibraryPage = lazy(() => import("./pages/Library").then((m) => ({ default: m.LibraryPage })));
const LibraryTemplatePage = lazy(() => import("./pages/LibraryTemplate").then((m) => ({ default: m.LibraryTemplatePage })));
const LibraryEditorPage = lazy(() => import("./pages/LibraryEditor").then((m) => ({ default: m.LibraryEditorPage })));
const FeedbackPage = lazy(() => import("./pages/Feedback").then((m) => ({ default: m.FeedbackPage })));
const StatusPage = lazy(() => import("./pages/Status").then((m) => ({ default: m.StatusPage })));

function RouteFallback() {
  return (
    <div className="flex flex-col gap-4">
      <CardSkeleton lines={2} />
      <CardSkeleton lines={2} />
    </div>
  );
}

// A notification tap's deep link (sw.js's notificationclick handler) arrives as a
// postMessage, not a URL change — client.navigate() has real gaps on iOS standalone WebKit,
// but every open client already runs this router, which can navigate itself reliably.
function useServiceWorkerNavigate() {
  const navigate = useNavigate();
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "catch:navigate" && typeof event.data.url === "string") {
        navigate(event.data.url);
      }
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [navigate]);
}

export function App() {
  const { status } = useAuth();
  useServiceWorkerNavigate();

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
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/calendar/plan" element={<PlanPage />} />
          <Route path="/calendar/events/:id" element={<EventDetailPage />} />
          <Route path="/workouts" element={<WorkoutsPage />} />
          <Route path="/workouts/duplicates" element={<DuplicatesPage />} />
          <Route path="/workouts/:id" element={<WorkoutDetailPage />} />
          <Route path="/gym" element={<GymPage />} />
          <Route path="/gym/readiness" element={<MuscleReadinessPage />} />
          <Route path="/tests" element={<TestCenterPage />} />
          {/* Registered before /tests/:id — react-router v6 scores static segments higher
              than dynamic ones regardless of order, but matching the backend's own
              "more specific first" convention here too (see routes_tests.py's comment on
              GET /api/pieces/{piece_id}/test-detail) keeps the two trees easy to compare. */}
          <Route path="/tests/piece/:id" element={<PieceTestDetailPage />} />
          <Route path="/tests/:id" element={<TestDetailPage />} />
          <Route path="/routes" element={<RoutesPage />} />
          <Route path="/routes/:id" element={<RouteDetailPage />} />
          <Route path="/trends" element={<TrendsPage />} />
          <Route path="/trends/intelligence" element={<TrainingIntelligencePage />} />
          <Route path="/body" element={<BodyPage />} />
          <Route path="/nutrition" element={<NutritionPage />} />
          <Route path="/coach" element={<CoachPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/library/new" element={<LibraryEditorPage />} />
          <Route path="/library/:id/edit" element={<LibraryEditorPage />} />
          <Route path="/library/:id" element={<LibraryTemplatePage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/ai" element={<AiProvidersPage />} />
          <Route path="/settings/memory" element={<MemoryPage />} />
          <Route path="/settings/status" element={<StatusPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
