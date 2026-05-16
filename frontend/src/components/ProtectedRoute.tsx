import { Navigate } from "react-router-dom";
import { getToken } from "@/lib/api";

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
