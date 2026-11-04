import { useEffect, useState } from "react";

export type Page = "verify" | "scripts" | "remark" | "how";
export const PAGES: { id: Page; label: string }[] = [
  { id: "verify", label: "Verify" },
  { id: "scripts", label: "Scripts" },
  { id: "remark", label: "Re-mark" },
  { id: "how", label: "How it works" },
];

export interface Route {
  page: Page;
  params: URLSearchParams;
}

function parse(): Route {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const page = PAGES.find((p) => p.id === path)?.id ?? "verify";
  return { page, params: new URLSearchParams(query ?? "") };
}

export const href = (page: Page, params?: Record<string, string>) =>
  `#/${page}${params ? "?" + new URLSearchParams(params).toString() : ""}`;

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const update = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}
