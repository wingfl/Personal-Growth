import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  ChartNoAxesCombined,
  LineChart,
  Radar,
  FolderOpen,
  History,
  LayoutDashboard,
  Menu,
  Settings,
  Target,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "首页", icon: LayoutDashboard, end: true },
  { to: "/archive", label: "成长档案", icon: FolderOpen },
  { to: "/insights", label: "数据分析", icon: ChartNoAxesCombined },
  { to: "/capabilities", label: "能力画像", icon: Radar },
  { to: "/market", label: "市场定位", icon: LineChart },
  { to: "/goals", label: "成长目标", icon: Target },
  { to: "/review", label: "复盘", icon: History },
  { to: "/settings", label: "设置", icon: Settings },
];

export const TITLES: Record<string, string> = {
  "/": "首页",
  "/archive": "成长档案",
  "/insights": "数据分析",
  "/capabilities": "能力画像",
  "/market": "市场定位",
  "/goals": "成长目标",
  "/review": "复盘",
  "/settings": "设置",
};

function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation();
  return (
    <>
      <div className="mb-6 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-sm font-semibold text-primary-foreground">
          成
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">个人成长档案</div>
          <div className="text-2xs text-muted-foreground">本地 · 只读</div>
        </div>
      </div>
      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ to, label, icon: Icon, end }) => {
          const active = end ? location.pathname === to : location.pathname.startsWith(to);
          return (
            <NavLink
              key={to}
              to={to}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                active && "bg-primary-weak font-medium text-primary hover:bg-primary-weak hover:text-primary",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </NavLink>
          );
        })}
      </nav>
      <div className="mt-auto px-2 text-2xs leading-5 text-muted-foreground">
        数据来自本地 SQLite
        <br />
        写操作请用命令行
      </div>
    </>
  );
}

/** 桌面侧栏：窄屏隐藏，由 MobileNav 接管 */
export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r border-border bg-card/60 px-3 py-4 md:flex">
      <SidebarBody />
    </aside>
  );
}

/** 窄屏抽屉导航：≤ md 时出现在顶部栏左侧 */
export function MobileNav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = "";
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="打开导航"
        className="mr-1 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
      >
        <Menu className="h-5 w-5" />
      </button>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="导航">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="relative flex h-full w-[264px] flex-col border-r border-border bg-card px-3 py-4 shadow-pop">
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="关闭导航"
              className="absolute right-2 top-3 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
            <SidebarBody onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </>
  );
}
