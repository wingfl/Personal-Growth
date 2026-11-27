import * as React from "react";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4 w-full", className)} aria-hidden />;
}

export function PageSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-4" aria-label="加载中">
      <Skeleton className="h-8 w-56" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-28 rounded-lg" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-24 rounded-lg" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-danger/30 bg-danger/5 px-6 py-10 text-center">
      <AlertTriangle className="h-6 w-6 text-danger" aria-hidden />
      <div>
        <p className="font-medium text-foreground">没能读到数据</p>
        <p className="mt-1 text-sm text-muted-foreground">{message}</p>
      </div>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw className="h-3.5 w-3.5" /> 重试
        </Button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <div className="text-muted-foreground">{icon ?? <Inbox className="h-6 w-6" aria-hidden />}</div>
      <div>
        <p className="font-medium text-foreground">{title}</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}
