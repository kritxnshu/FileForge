import type { Metadata } from "next";
import { Suspense } from "react";
import { ToolDirectory } from "@/components/ToolDirectory";

export const metadata: Metadata = { title: "All tools", description: "Every conversion and tool, searchable by format." };

export default function ToolsPage() {
  return (
    <div className="pb-10 pt-4">
      <h1 className="mb-6 font-display text-4xl font-bold sm:text-5xl">All tools</h1>
      <Suspense>
        <ToolDirectory />
      </Suspense>
    </div>
  );
}
