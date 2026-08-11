"use client";

import {
  Bot,
  Database,
  FileText,
  LandmarkIcon,
  LayoutDashboard,
  LineChart,
  LogOut,
  ReceiptText,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { logout } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/dashboard", key: "nav.dashboard", icon: LayoutDashboard },
  { href: "/assets", key: "nav.assets", icon: LineChart },
  { href: "/accounts", key: "nav.accounts", icon: LandmarkIcon },
  { href: "/transactions", key: "nav.transactions", icon: ReceiptText },
  { href: "/documents", key: "nav.documents", icon: FileText },
  { href: "/agent", key: "nav.agent", icon: Bot },
  { href: "/data", key: "nav.data", icon: Database },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { t, locale, setLocale } = useI18n();

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      router.push("/login");
      router.refresh();
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="text-lg font-semibold">WealthPortfolio</div>
          <nav className="order-3 -mx-1 flex w-[calc(100%+0.5rem)] items-center gap-1 overflow-x-auto px-1 pb-0.5 lg:order-none lg:mx-0 lg:w-auto lg:px-0">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = pathname?.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {t(item.key)}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setLocale(locale === "zh" ? "en" : "zh")}>
              {locale === "zh" ? "EN" : "中文"}
            </Button>
            <Button variant="ghost" size="sm" onClick={handleLogout}>
              <LogOut className="h-4 w-4" />
              {t("nav.logout")}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
