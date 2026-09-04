import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAuth } from "@/auth/auth-context";
import Dashboard from "@/pages/Dashboard";

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
    </Routes>
  );
}
