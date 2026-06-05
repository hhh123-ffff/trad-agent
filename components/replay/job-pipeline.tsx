import { CheckCircle2, CircleDashed, Clock3, XCircle } from "lucide-react";

import { latestPostMarketRun, postMarketPipeline, type PipelineStatus } from "@/lib/job-status";
import type { JobRun } from "@/lib/types";

export function PostMarketPipeline({ jobRuns }: { jobRuns: JobRun[] }) {
  const run = latestPostMarketRun(jobRuns);
  const steps = postMarketPipeline(run);

  return (
    <div className="grid gap-2 md:grid-cols-5">
      {steps.map((step) => (
        <div key={step.key} className="rounded-md border border-ink/10 bg-white px-3 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <PipelineIcon status={step.status} />
            <span>{step.label}</span>
          </div>
          <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted">{step.detail}</p>
        </div>
      ))}
    </div>
  );
}

function PipelineIcon({ status }: { status: PipelineStatus }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-pine" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-danger" />;
  if (status === "skipped") return <CircleDashed className="h-4 w-4 text-muted" />;
  return <Clock3 className="h-4 w-4 text-muted" />;
}
