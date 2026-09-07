import { Route, Routes } from "react-router-dom";
import Login from "@/auth/Login";
import { RequireAdmin, RequireAuth } from "@/auth/auth-context";
import { Layout } from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Users from "@/pages/Users";
import Devices from "@/pages/Devices";
import DeviceDetail from "@/pages/DeviceDetail";
import Sites from "@/pages/Sites";
import Organizations from "@/pages/Organizations";
import Contacts from "@/pages/Contacts";
import Circuits from "@/pages/Circuits";
import CircuitDetail from "@/pages/CircuitDetail";
import BgpSessions from "@/pages/BgpSessions";
import BgpSessionDetail from "@/pages/BgpSessionDetail";
import ChangeRequests from "@/pages/ChangeRequests";
import ChangeRequestDetail from "@/pages/ChangeRequestDetail";
import PolicyProfiles from "@/pages/PolicyProfiles";
import Communities from "@/pages/Communities";
import PrefixAuthorizations from "@/pages/PrefixAuthorizations";
import AuditEvents from "@/pages/AuditEvents";
import Snapshots from "@/pages/Snapshots";
import DesiredConfig from "@/pages/DesiredConfig";
import Reconcile from "@/pages/Reconcile";
import Jobs from "@/pages/Jobs";
import JobDetail from "@/pages/JobDetail";
import Wiki from "@/pages/Wiki";
import MplsDomains from "@/pages/MplsDomains";
import MplsL2vc from "@/pages/MplsL2vc";
import MplsL2vcDetail from "@/pages/MplsL2vcDetail";
import MplsVsi from "@/pages/MplsVsi";
import MplsVsiDetail from "@/pages/MplsVsiDetail";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/devices/:id" element={<DeviceDetail />} />
        <Route path="/sites" element={<Sites />} />
        <Route path="/organizations" element={<Organizations />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/circuits" element={<Circuits />} />
        <Route path="/circuits/:id" element={<CircuitDetail />} />
        <Route path="/bgp-sessions" element={<BgpSessions />} />
        <Route path="/bgp-sessions/:id" element={<BgpSessionDetail />} />
        <Route path="/change-requests" element={<ChangeRequests />} />
        <Route path="/change-requests/:id" element={<ChangeRequestDetail />} />
        <Route path="/mpls/domains" element={<MplsDomains />} />
        <Route path="/mpls/domains/:id" element={<MplsDomains />} />
        <Route path="/mpls/l2vc" element={<MplsL2vc />} />
        <Route path="/mpls/l2vc/:id" element={<MplsL2vcDetail />} />
        <Route path="/mpls/vsi" element={<MplsVsi />} />
        <Route path="/mpls/vsi/:id" element={<MplsVsiDetail />} />
        <Route path="/policy-profiles" element={<PolicyProfiles />} />
        <Route path="/communities" element={<Communities />} />
        <Route path="/prefix-authorizations" element={<PrefixAuthorizations />} />
        <Route path="/audit-events" element={<AuditEvents />} />
        <Route path="/snapshots" element={<Snapshots />} />
        <Route path="/desired-config" element={<DesiredConfig />} />
        <Route path="/reconcile" element={<Reconcile />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/jobs/:id" element={<JobDetail />} />
        <Route path="/wiki/:slug?" element={<Wiki />} />
        <Route
          path="/users"
          element={
            <RequireAdmin>
              <Users />
            </RequireAdmin>
          }
        />
      </Route>
    </Routes>
  );
}
