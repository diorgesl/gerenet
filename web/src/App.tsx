import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import Dashboard from "@/pages/Dashboard";
import Users from "@/pages/Users";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Dashboard />
          </RequireAuth>
        }
      />
      <Route
        path="/users"
        element={
          <RequireAuth>
            <RequireAdmin>
              <Users />
            </RequireAdmin>
          </RequireAuth>
        }
      />
    </Routes>
  );
}
