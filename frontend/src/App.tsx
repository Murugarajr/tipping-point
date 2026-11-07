import { lazy, Suspense } from "react";
import PublicApp from "./public/PublicApp";
import "./public/public.css";
import { useLocation } from "./navigation";

const MerchantApp = lazy(() => import("./host/HostApp"));

export default function App() {
  useLocation();
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/host" || path.startsWith("/host/")) {
    return <Suspense fallback={<main className="centered"><h1>Opening your workspace…</h1></main>}><MerchantApp /></Suspense>;
  }
  return <PublicApp path={path} />;
}
