import { lazy, Suspense } from "react";
import PublicApp from "./public/PublicApp";
import "./public/public.css";

const MerchantApp = lazy(() => import("./MerchantApp"));

export default function App() {
  const path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/host" || path === "/host/login") {
    return <Suspense fallback={<main className="centered"><h1>Opening your workspace…</h1></main>}><MerchantApp /></Suspense>;
  }
  return <PublicApp path={path} />;
}
