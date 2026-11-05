import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/PageHeader";
import { ToolDirectory } from "@/components/ToolDirectory";

export const metadata: Metadata = { title: "All tools", description: "Every conversion and tool, searchable by format." };

export default function ToolsPage() {
  return (
    <>
      <PageHeader eyebrow="Directory" title="All tools" description="Every conversion and tool, searchable by format. Tools marked “In browser” never upload anything." />
      <Suspense>
        <ToolDirectory />
      </Suspense>
    </>
  );
}
