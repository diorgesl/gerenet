import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import AuditEvents from "@/pages/AuditEvents";
import BgpSessionDetail from "@/pages/BgpSessionDetail";
import BgpSessions from "@/pages/BgpSessions";
import CircuitDetail from "@/pages/CircuitDetail";
import Circuits from "@/pages/Circuits";
import Communities from "@/pages/Communities";
import Contacts from "@/pages/Contacts";
import Dashboard from "@/pages/Dashboard";
import DesiredConfig from "@/pages/DesiredConfig";
import Devices from "@/pages/Devices";
import JobDetail from "@/pages/JobDetail";
import Jobs from "@/pages/Jobs";
import Organizations from "@/pages/Organizations";
import PolicyProfiles from "@/pages/PolicyProfiles";
import PrefixAuthorizations from "@/pages/PrefixAuthorizations";
import Reconcile from "@/pages/Reconcile";
import Sites from "@/pages/Sites";
import Snapshots from "@/pages/Snapshots";
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
      <Route path="/policy-profiles" element={<RequireAuth><PolicyProfiles /></RequireAuth>} />
      <Route path="/communities" element={<RequireAuth><Communities /></RequireAuth>} />
      <Route path="/prefix-authorizations" element={<RequireAuth><PrefixAuthorizations /></RequireAuth>} />
      <Route path="/audit-events" element={<RequireAuth><AuditEvents /></RequireAuth>} />
      <Route path="/snapshots" element={<RequireAuth><Snapshots /></RequireAuth>} />
      <Route path="/desired-config" element={<RequireAuth><DesiredConfig /></RequireAuth>} />
      <Route path="/reconcile" element={<RequireAuth><Reconcile /></RequireAuth>} />
      <Route path="/jobs" element={<RequireAuth><Jobs /></RequireAuth>} />
      <Route path="/jobs/:id" element={<RequireAuth><JobDetail /></RequireAuth>} />
    </Routes>
  );
}
