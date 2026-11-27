import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { MoonStar, RefreshCw, SunMedium } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MobileNav, TITLES } from "./Sidebar";

type Health = { generated_at: string; counts: Record<string, number> };

export function Topbar() {
  const location = useLocation();
  const [health, setHealth] = useState<Health | null>(null);
  const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);

  const load = () => {
    api.get<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
  };
  useEffect(load, [location.pathname]);

  const segments = location.pathname.split("/").filter(Boolean);
  const title = TITLES["/" + (segments[0] ?? "")] ?? TITLES["/"] ?? "个人成长档案";

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b border-border bg-background/80 px-3 backdrop-blur md:px-8">
      <div className="flex min-w-0 items-center gap-2">
        <MobileNav />
        <h1 className="truncate text-base font-semibold md:text-lg">{title}</h1>
        <span className="hidden text-xs text-muted-foreground sm:inline">
          数据更新于 {health ? health.generated_at.slice(0, 16).replace("T", " ") : "…"}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <Button variant="ghost" size="icon" onClick={load} aria-label="刷新">
          <RefreshCw className={cn("h-4 w-4", !health && "animate-spin")} />
        </Button>
        <Button variant="ghost" size="icon" onClick={() => setDark(!dark)} aria-label="切换主题">
          {dark ? <SunMedium className="h-4 w-4" /> : <MoonStar className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  );
}
