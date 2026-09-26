"use client";

import { createContext, useContext } from "react";
import type { Job, Media, ProjectDetail } from "@/lib/api";

export interface ProjectCtx {
  id: string;
  detail: ProjectDetail;
  media: Media | null;
  /** Every job of this project (newest first), refreshed with `version`. */
  jobs: Job[];
  /** Bumped after every mutation / finished job: tabs include it in their data keys to re-fetch. */
  version: number;
  refresh: () => void;
  /** Show a live progress panel for a job started from any tab. */
  track: (job: Job) => void;
  workerOk: boolean;
}

export const ProjectContext = createContext<ProjectCtx | null>(null);

export function useProject(): ProjectCtx {
  const c = useContext(ProjectContext);
  if (!c) throw new Error("useProject outside ProjectContext");
  return c;
}
