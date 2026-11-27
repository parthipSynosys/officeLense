import { Route, Routes } from "react-router-dom";
import { Logo } from "@/components/Logo";
import { EmptyState } from "@/components/States";
import { RequireAdmin } from "@/features/admin/AdminLayout";
import { AuthProvider } from "@/features/admin/AuthContext";
import { DashboardPage } from "@/features/admin/DashboardPage";
import { EventDetailPage } from "@/features/admin/EventDetailPage";
import { EventsPage } from "@/features/admin/EventsPage";
import { LoginPage } from "@/features/admin/LoginPage";
import { GuestFlowProvider } from "@/features/guest/GuestFlowContext";
import { GuestLayout } from "@/features/guest/GuestLayout";
import { HomePage } from "@/features/guest/HomePage";
import { ResultsPage } from "@/features/guest/ResultsPage";
import { SelfiePage } from "@/features/guest/SelfiePage";

export default function App() {
  return (
    <Routes>
      <Route
        path="/admin/*"
        element={
          <AuthProvider>
            <Routes>
              <Route path="login" element={<LoginPage />} />
              <Route element={<RequireAdmin />}>
                <Route index element={<DashboardPage />} />
                <Route path="events" element={<EventsPage />} />
                <Route path="events/:id" element={<EventDetailPage />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </AuthProvider>
        }
      />
      <Route
        element={
          <GuestFlowProvider>
            <GuestLayout />
          </GuestFlowProvider>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="selfie" element={<SelfiePage />} />
        <Route path="results" element={<ResultsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function NotFound() {
  return (
    <div className="card mx-auto max-w-md">
      <EmptyState title="Page not found" description="The page you're looking for doesn't exist." action={<Logo />} />
    </div>
  );
}
