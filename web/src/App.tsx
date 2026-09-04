import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import BgpSessionDetail from "@/pages/BgpSessionDetail";
import BgpSessions from "@/pages/BgpSessions";
import CircuitDetail from "@/pages/CircuitDetail";
import Circuits from "@/pages/Circuits";
import Contacts from "@/pages/Contacts";
import Dashboard from "@/pages/Dashboard";
import Devices from "@/pages/Devices";
import Organizations from "@/pages/Organizations";
import Sites from "@/pages/Sites";
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
      <Route
        path="/devices"
        element={
          <RequireAuth>
            <Devices />
          </RequireAuth>
        }
      />
      <Route
        path="/circuits"
        element={
          <RequireAuth>
            <Circuits />
          </RequireAuth>
        }
      />
      <Route
        path="/circuits/:id"
        element={
          <RequireAuth>
            <CircuitDetail />
          </RequireAuth>
        }
      />
      <Route
        path="/bgp-sessions"
        element={
          <RequireAuth>
            <BgpSessions />
          </RequireAuth>
        }
      />
      <Route
        path="/bgp-sessions/:id"
        element={
          <RequireAuth>
            <BgpSessionDetail />
          </RequireAuth>
        }
      />
      <Route
        path="/sites"
        element={
          <RequireAuth>
            <Sites />
          </RequireAuth>
        }
      />
      <Route
        path="/organizations"
        element={
          <RequireAuth>
            <Organizations />
          </RequireAuth>
        }
      />
      <Route
        path="/contacts"
        element={
          <RequireAuth>
            <Contacts />
          </RequireAuth>
        }
      />
    </Routes>
  );
}
