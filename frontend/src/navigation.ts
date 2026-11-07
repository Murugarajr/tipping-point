import { useEffect, useState } from "react";

export function navigate(destination: string, replace = false) {
  if (replace) window.history.replaceState(null, "", destination);
  else window.history.pushState(null, "", destination);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
export function useLocation() {
  const read = () => window.location.pathname + window.location.search + window.location.hash;
  const [location, setLocation] = useState(read);
  useEffect(() => {
    const update = () => setLocation(read());
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return location;
}
