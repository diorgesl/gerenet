import React from "react";
import ReactDOM from "react-dom/client";
import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, useNavigate } from "react-router-dom";
import { AuthProvider } from "./auth/auth-context";
import { setOnUnauthorized } from "./api/client";
import App from "./App";
import "./styles/global.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

function Raiz() {
  const navigate = useNavigate();
  useEffect(() => {
    setOnUnauthorized(() => navigate("/login", { replace: true }));
  }, [navigate]);
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Raiz />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
