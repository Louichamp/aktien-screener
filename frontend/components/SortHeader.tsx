"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { SortBy } from "@/lib/types";

// Klickbarer Spaltenkopf: schaltet sort_by/sort_dir in der URL um.
// Erster Klick -> desc, zweiter -> asc, danach wieder desc.
export default function SortHeader({
  column,
  label,
  align = "left",
  numeric = false,
}: {
  column: SortBy;
  label: string;
  align?: "left" | "right" | "center";
  numeric?: boolean;
}) {
  const router = useRouter();
  const params = useSearchParams();

  const activeCol = params.get("sort_by");
  const activeDir = params.get("sort_dir") ?? "desc";
  const isActive = activeCol === column;

  const onClick = () => {
    const next = new URLSearchParams(params.toString());
    const nextDir = isActive && activeDir === "desc" ? "asc" : "desc";
    next.set("sort_by", column);
    next.set("sort_dir", nextDir);
    router.push(`/?${next.toString()}`);
  };

  const justify =
    align === "right" ? "justify-end" : align === "center" ? "justify-center" : "justify-start";

  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-1 ${justify} ${numeric ? "tabular-nums" : ""} ${
        isActive ? "text-accent" : "text-muted hover:text-slate-200"
      }`}
    >
      <span className="text-[11px] font-semibold uppercase tracking-wide">{label}</span>
      <span className="text-[9px] leading-none">
        {isActive ? (activeDir === "desc" ? "▼" : "▲") : "↕"}
      </span>
    </button>
  );
}
